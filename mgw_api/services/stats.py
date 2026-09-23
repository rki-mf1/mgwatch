from types import SimpleNamespace

import polars as pl
import pymongo as pm
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mgw.settings import LOGGER
from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import enabled_databases
from mgw_api.database_config import get_database_config
from mgw_api.database_config import normalize_database_list
from mgw_api.database_config import profile_manifest
from mgw_api.database_config import read_accession_parquet
from mgw_api.models import SystemStatistic
from mgw_api.models import SystemStatisticSnapshot


def count_index_samples(database=DEFAULT_DATABASE_ID):
    counts = count_index_samples_by_profile(database=database).values()
    return min(counts) if counts else 0


def count_index_samples_by_profile(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    return {
        profile.key: len(
            read_accession_parquet(profile_manifest(database_config.id, profile))
        )
        for profile in database_config.enabled_profiles
    }


def statistic_scope(database, profile_key=""):
    database = normalize_database_list([database])[0]
    return f"{database}:{profile_key}" if profile_key else database


def _profile_details(database_config, profile):
    return {
        "database": database_config.id,
        "database_label": database_config.label,
        "profile": profile.key,
        "kmer": profile.kmer,
        "scaled": profile.scaled,
    }


def _record_profile_metric(
    *, metric, value, database_config, profile, recorded_at=None
):
    return record_metric(
        metric=metric,
        value=value,
        details=_profile_details(database_config, profile),
        scope=statistic_scope(database_config.id, profile.key),
        recorded_at=recorded_at,
    )


def _delete_database_scope_statistic(metric, database_config):
    SystemStatistic.objects.filter(
        metric=metric,
        scope=statistic_scope(database_config.id),
    ).delete()


def _count_metrics():
    return {
        SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
        SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
        SystemStatistic.Metric.WORT_SIGNATURE_SAMPLE_COUNT,
    }


def _enabled_scope_by_database():
    return {
        database.id: {
            statistic_scope(database.id, profile.key)
            for profile in database.enabled_profiles
        }
        for database in enabled_databases()
    }


def _statistic_database(statistic):
    database = statistic.details.get("database")
    if not database and statistic.scope:
        database = statistic.scope.split(":", 1)[0]
    return normalize_database_list([database or DEFAULT_DATABASE_ID])[0]


def _is_profile_statistic(statistic):
    return bool(statistic.details.get("profile") or ":" in statistic.scope)


def _enabled_count_statistics_by_database(metric):
    enabled_scope_by_database = _enabled_scope_by_database()
    enabled_database_scopes = {
        statistic_scope(database_id) for database_id in enabled_scope_by_database
    }
    statistics_by_database = {}
    for statistic in SystemStatistic.objects.filter(metric=metric):
        database = _statistic_database(statistic)
        if database not in enabled_scope_by_database:
            continue
        profile = statistic.details.get("profile")
        if not profile and ":" in statistic.scope:
            profile = statistic.scope.split(":", 1)[1]
        if profile:
            if statistic.scope not in enabled_scope_by_database[database]:
                continue
        elif statistic.scope and statistic.scope not in enabled_database_scopes:
            continue
        statistics_by_database.setdefault(database, []).append(statistic)
    return enabled_scope_by_database, statistics_by_database


def aggregate_current_stat(metric):
    if metric not in _count_metrics():
        return SystemStatistic.objects.filter(metric=metric, scope="").first()

    enabled_scope_by_database, statistics_by_database = (
        _enabled_count_statistics_by_database(metric)
    )
    if not statistics_by_database:
        return None
    values = []
    included_statistics = []
    for database_id, profile_scopes in enabled_scope_by_database.items():
        database_statistics = statistics_by_database.get(database_id, [])
        profile_statistics = [
            statistic
            for statistic in database_statistics
            if _is_profile_statistic(statistic)
        ]
        if profile_statistics:
            if {statistic.scope for statistic in profile_statistics} != profile_scopes:
                return None
            selected_statistics = profile_statistics
            values.append(min(statistic.value for statistic in selected_statistics))
        else:
            fallback_statistics = [
                statistic
                for statistic in database_statistics
                if not _is_profile_statistic(statistic)
            ]
            if not fallback_statistics:
                return None
            selected_statistics = [
                max(fallback_statistics, key=lambda statistic: statistic.recorded_at)
            ]
            values.append(selected_statistics[0].value)
        included_statistics.extend(selected_statistics)
    return SimpleNamespace(
        value=sum(values),
        observation_count=sum(
            statistic.observation_count for statistic in included_statistics
        ),
        details={},
        recorded_at=max(statistic.recorded_at for statistic in included_statistics),
    )


def get_cached_index_sample_count_for_databases(databases):
    if isinstance(databases, str):
        databases = [databases]
    total = 0
    for database in dict.fromkeys(normalize_database_list(databases)):
        database_config = get_database_config(database)
        profile_scopes = [
            statistic_scope(database_config.id, profile.key)
            for profile in database_config.enabled_profiles
        ]
        profile_statistics = list(
            SystemStatistic.objects.filter(
                metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
                scope__in=profile_scopes,
            )
        )
        if profile_statistics:
            if len(profile_statistics) != len(profile_scopes):
                return None
            total += min(int(statistic.value) for statistic in profile_statistics)
            continue

        database_statistic = SystemStatistic.objects.filter(
            metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
            scope=statistic_scope(database_config.id),
        ).first()
        if database_statistic is not None:
            total += int(database_statistic.value)
            continue

        legacy_statistic = SystemStatistic.objects.filter(
            metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
            scope="",
        ).first()
        if legacy_statistic is None:
            return None
        statistic_database = normalize_database_list(
            [legacy_statistic.details.get("database", DEFAULT_DATABASE_ID)]
        )[0]
        if database_config.id != statistic_database:
            LOGGER.debug(
                "Skipped cached index sample count for unsupported database: %s",
                database_config.id,
            )
            return None
        total += int(legacy_statistic.value)
    return total


def count_wort_signature_samples(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    accessions = (
        pl.scan_parquet(database_config.wort_manifest_url)
        .select(pl.col("name").str.extract(r"([\w.]+)", 1).alias("accession"))
        .collect()
        .get_column("accession")
        .unique()
        .to_list()
    )
    return len(accessions)


def count_metadata_samples(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    mongo = pm.MongoClient(settings.MONGO_URI)
    try:
        db = mongo["sradb"]
        return db[database_config.mongodb_collection].count_documents({})
    finally:
        mongo.close()


def record_metric(
    *, metric, value, observation_count=0, details=None, recorded_at=None, scope=""
):
    recorded_at = recorded_at or timezone.now()
    details = details or {}
    with transaction.atomic():
        statistic, _created = SystemStatistic.objects.update_or_create(
            metric=metric,
            scope=scope,
            defaults={
                "value": value,
                "observation_count": observation_count,
                "details": details,
                "recorded_at": recorded_at,
            },
        )
        SystemStatisticSnapshot.objects.create(
            metric=metric,
            value=statistic.value,
            observation_count=statistic.observation_count,
            details=statistic.details,
            recorded_at=recorded_at,
        )
    return statistic


def record_index_stats(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    recorded_at = timezone.now()
    profile_counts = count_index_samples_by_profile(database=database_config.id)
    _delete_database_scope_statistic(
        SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
        database_config,
    )
    statistics = [
        _record_profile_metric(
            metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
            value=profile_counts[profile.key],
            database_config=database_config,
            profile=profile,
            recorded_at=recorded_at,
        )
        for profile in database_config.enabled_profiles
    ]
    if not statistics:
        return None
    return min(statistics, key=lambda statistic: statistic.value)


def record_metadata_stats(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    sample_count = count_metadata_samples(database=database_config.id)
    recorded_at = timezone.now()
    _delete_database_scope_statistic(
        SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
        database_config,
    )
    statistics = [
        _record_profile_metric(
            metric=SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
            value=sample_count,
            database_config=database_config,
            profile=profile,
            recorded_at=recorded_at,
        )
        for profile in database_config.enabled_profiles
    ]
    return statistics[0] if statistics else None


def record_wort_signature_stats(database=DEFAULT_DATABASE_ID, sample_count=None):
    database_config = get_database_config(database)
    if sample_count is None:
        sample_count = count_wort_signature_samples(database=database_config.id)
    recorded_at = timezone.now()
    _delete_database_scope_statistic(
        SystemStatistic.Metric.WORT_SIGNATURE_SAMPLE_COUNT,
        database_config,
    )
    statistics = [
        _record_profile_metric(
            metric=SystemStatistic.Metric.WORT_SIGNATURE_SAMPLE_COUNT,
            value=sample_count,
            database_config=database_config,
            profile=profile,
            recorded_at=recorded_at,
        )
        for profile in database_config.enabled_profiles
    ]
    return statistics[0] if statistics else None


def get_database_status_rows():
    metrics = [
        SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
        SystemStatistic.Metric.WORT_SIGNATURE_SAMPLE_COUNT,
        SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
    ]
    statistics = {
        (statistic.metric, statistic.scope): statistic
        for statistic in SystemStatistic.objects.filter(metric__in=metrics)
    }
    rows = []
    for database in enabled_databases():
        database_fallbacks = {
            metric: statistics.get((metric, statistic_scope(database.id)))
            for metric in metrics
        }
        profile_statistics_by_metric = {
            metric: [
                statistics.get((metric, statistic_scope(database.id, profile.key)))
                for profile in database.enabled_profiles
            ]
            for metric in metrics
        }
        for profile in database.enabled_profiles:
            scope = statistic_scope(database.id, profile.key)
            profile_statistics = {
                metric: statistics.get((metric, scope)) for metric in metrics
            }
            row_statistics = {}
            for metric in metrics:
                if any(profile_statistics_by_metric[metric]):
                    row_statistics[metric] = profile_statistics[metric]
                else:
                    row_statistics[metric] = database_fallbacks[metric]
            rows.append(
                {
                    "database": database.label,
                    "database_id": database.id,
                    "profile": profile.key,
                    "kmer": profile.kmer,
                    "scaled": profile.scaled,
                    "metadata_samples": row_statistics[
                        SystemStatistic.Metric.METADATA_SAMPLE_COUNT
                    ],
                    "wort_signature_samples": row_statistics[
                        SystemStatistic.Metric.WORT_SIGNATURE_SAMPLE_COUNT
                    ],
                    "index_samples": row_statistics[
                        SystemStatistic.Metric.INDEX_SAMPLE_COUNT
                    ],
                }
            )
    return rows


def record_timed_metric(*, metric, duration_seconds, details=None, recorded_at=None):
    recorded_at = recorded_at or timezone.now()
    duration_seconds = max(float(duration_seconds), 0.0)
    details = {
        **(details or {}),
        "last_runtime_seconds": duration_seconds,
    }
    with transaction.atomic():
        statistic, _created = SystemStatistic.objects.select_for_update().get_or_create(
            metric=metric,
            scope="",
            defaults={
                "value": 0.0,
                "observation_count": 0,
                "details": {},
                "recorded_at": recorded_at,
            },
        )
        statistic.value = duration_seconds
        statistic.observation_count += 1
        statistic.details = details
        statistic.recorded_at = recorded_at
        statistic.save(
            update_fields=["value", "observation_count", "details", "recorded_at"]
        )
        SystemStatisticSnapshot.objects.create(
            metric=metric,
            value=statistic.value,
            observation_count=statistic.observation_count,
            details=details,
            recorded_at=recorded_at,
        )
    return statistic


def record_metadata_update_runtime(*, duration_seconds, metadata_sample_count=None):
    details = {}
    if metadata_sample_count is not None:
        details["metadata_sample_count"] = int(metadata_sample_count)
    return record_timed_metric(
        metric=SystemStatistic.Metric.METADATA_UPDATE_RUNTIME_SECONDS,
        duration_seconds=duration_seconds,
        details=details,
    )


def record_index_update_runtime(
    *,
    duration_seconds,
    samples_added,
    sketches_added,
    database=DEFAULT_DATABASE_ID,
    total_index_sample_count=None,
):
    details = {
        "database": database,
        "samples_added": int(samples_added),
        "sketches_added": int(sketches_added),
    }
    if total_index_sample_count is not None:
        details["total_index_sample_count"] = int(total_index_sample_count)
    return record_timed_metric(
        metric=SystemStatistic.Metric.INDEX_UPDATE_RUNTIME_SECONDS,
        duration_seconds=duration_seconds,
        details=details,
    )


def record_download_index_runtime(
    *,
    duration_seconds,
    downloaded,
    indexes_updated,
):
    details = {
        "downloaded": int(downloaded),
        "indexes_updated": int(indexes_updated),
    }
    return record_timed_metric(
        metric=SystemStatistic.Metric.DOWNLOAD_INDEX_RUNTIME_SECONDS,
        duration_seconds=duration_seconds,
        details=details,
    )


def record_search_rate(
    *,
    duration_seconds,
    index_sample_count,
    result=None,
    total_indexes=None,
):
    recorded_at = timezone.now()
    duration_seconds = max(float(duration_seconds), 0.0)
    index_sample_count = max(int(index_sample_count), 0)
    rate = index_sample_count / duration_seconds if duration_seconds else 0.0
    details = {
        "last_runtime_seconds": duration_seconds,
        "last_index_sample_count": index_sample_count,
        "last_search_rate_sequences_per_second": rate,
        "last_result_id": result.pk if result else None,
        "last_total_indexes": total_indexes,
    }
    metric = SystemStatistic.Metric.AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND
    with transaction.atomic():
        statistic, _created = SystemStatistic.objects.select_for_update().get_or_create(
            metric=metric,
            scope="",
            defaults={
                "value": 0.0,
                "observation_count": 0,
                "details": {
                    "total_runtime_seconds": 0.0,
                    "total_index_sample_count": 0,
                },
                "recorded_at": recorded_at,
            },
        )
        total_runtime_seconds = (
            float(statistic.details.get("total_runtime_seconds", 0.0))
            + duration_seconds
        )
        total_index_sample_count = (
            int(statistic.details.get("total_index_sample_count", 0))
            + index_sample_count
        )
        new_count = statistic.observation_count + 1
        statistic.value = (
            total_index_sample_count / total_runtime_seconds
            if total_runtime_seconds
            else 0.0
        )
        statistic.observation_count = new_count
        statistic.details = {
            **details,
            "total_runtime_seconds": total_runtime_seconds,
            "total_index_sample_count": total_index_sample_count,
        }
        statistic.recorded_at = recorded_at
        statistic.save(
            update_fields=["value", "observation_count", "details", "recorded_at"]
        )
        SystemStatisticSnapshot.objects.create(
            metric=metric,
            value=statistic.value,
            observation_count=statistic.observation_count,
            details=details,
            recorded_at=recorded_at,
        )
    return statistic


def try_record_index_stats(database=DEFAULT_DATABASE_ID):
    try:
        return record_index_stats(database=database)
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped index statistics recording because database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record index statistics")
    return None


def try_record_metadata_stats(database=DEFAULT_DATABASE_ID):
    try:
        return record_metadata_stats(database=database)
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped metadata statistics recording because database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record metadata statistics")
    return None


def try_record_wort_signature_stats(database=DEFAULT_DATABASE_ID, sample_count=None):
    try:
        return record_wort_signature_stats(
            database=database,
            sample_count=sample_count,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped Wort signature statistics recording because database is "
                "unavailable"
            )
        else:
            LOGGER.exception("Failed to record Wort signature statistics")
    return None


def try_record_metadata_update_runtime(*, duration_seconds, metadata_sample_count=None):
    try:
        return record_metadata_update_runtime(
            duration_seconds=duration_seconds,
            metadata_sample_count=metadata_sample_count,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped metadata update runtime statistics recording because "
                "database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record metadata update runtime statistics")
    return None


def try_record_index_update_runtime(
    *,
    duration_seconds,
    samples_added,
    sketches_added,
    database=DEFAULT_DATABASE_ID,
    total_index_sample_count=None,
):
    try:
        return record_index_update_runtime(
            duration_seconds=duration_seconds,
            samples_added=samples_added,
            sketches_added=sketches_added,
            database=database,
            total_index_sample_count=total_index_sample_count,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped index update runtime statistics recording because "
                "database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record index update runtime statistics")
    return None


def try_record_download_index_runtime(
    *,
    duration_seconds,
    downloaded,
    indexes_updated,
):
    try:
        return record_download_index_runtime(
            duration_seconds=duration_seconds,
            downloaded=downloaded,
            indexes_updated=indexes_updated,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped download/index runtime statistics recording because "
                "database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record download/index runtime statistics")
    return None


def try_record_search_rate(
    *,
    duration_seconds,
    databases,
    result=None,
    total_indexes=None,
):
    try:
        index_sample_count = get_cached_index_sample_count_for_databases(databases)
        if index_sample_count is None:
            LOGGER.debug(
                "Skipped search rate statistics recording because index sample "
                "count has not been cached"
            )
            return None
        return record_search_rate(
            duration_seconds=duration_seconds,
            index_sample_count=index_sample_count,
            result=result,
            total_indexes=total_indexes,
        )
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped search rate statistics recording because database is "
                "unavailable"
            )
        else:
            LOGGER.exception("Failed to record search rate statistics")
    return None
