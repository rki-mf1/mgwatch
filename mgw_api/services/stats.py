import pickle

import pymongo as pm
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mgw.settings import LOGGER
from mgw_api.models import SystemStatistic
from mgw_api.models import SystemStatisticSnapshot


def count_index_samples(database="SRA"):
    manifest = settings.DATA_DIR / database / "metagenomes" / "manifest.pickle"
    if not manifest.exists():
        return 0
    with open(manifest, "rb") as handle:
        return len(pickle.load(handle))


def count_index_samples_for_databases(databases):
    if isinstance(databases, str):
        databases = [databases]
    return sum(count_index_samples(database=database) for database in set(databases))


def count_metadata_samples():
    mongo = pm.MongoClient(settings.MONGO_URI)
    try:
        db = mongo["sradb"]
        return db["sradb_list"].count_documents({})
    finally:
        mongo.close()


def record_metric(
    *, metric, value, observation_count=0, details=None, recorded_at=None
):
    recorded_at = recorded_at or timezone.now()
    details = details or {}
    with transaction.atomic():
        statistic, _created = SystemStatistic.objects.update_or_create(
            metric=metric,
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


def record_index_stats(database="SRA"):
    sample_count = count_index_samples(database=database)
    return record_metric(
        metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
        value=sample_count,
        details={"database": database},
    )


def record_metadata_stats():
    sample_count = count_metadata_samples()
    return record_metric(
        metric=SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
        value=sample_count,
        details={"database": "SRA"},
    )


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
    database="SRA",
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


def try_record_index_stats(database="SRA"):
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


def try_record_metadata_stats():
    try:
        return record_metadata_stats()
    except Exception as exc:
        if exc.__class__.__name__ == "DatabaseOperationForbidden":
            LOGGER.debug(
                "Skipped metadata statistics recording because database is unavailable"
            )
        else:
            LOGGER.exception("Failed to record metadata statistics")
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
    database="SRA",
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
        index_sample_count = count_index_samples_for_databases(databases)
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
