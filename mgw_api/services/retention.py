import re
from datetime import datetime
from datetime import timedelta
from datetime import timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from mgw.settings import LOGGER
from mgw_api.models import Fasta
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Signature

SUMMARY_KEYS = (
    "completed_jobs",
    "failed_jobs",
    "unprocessed_fastas",
    "unwatched_results",
    "watched_results",
    "result_shard_files",
    "orphaned_signatures",
    "temp_files",
    "failed_index_files",
    "log_files",
    "empty_dirs",
)


def _summary():
    return {key: 0 for key in SUMMARY_KEYS}


def _cutoff(now, days):
    if days < 0:
        return None
    return now - timedelta(days=days)


def _old_mtime(path, cutoff):
    if cutoff is None:
        return False
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=datetime_timezone.utc)
    except FileNotFoundError:
        return False
    return mtime <= cutoff


def _delete_objects(queryset, *, dry_run):
    count = 0
    for obj in queryset.iterator():
        count += 1
        if not dry_run:
            obj.delete()
    return count


def _result_search_output_dir(result):
    if result.file and result.file.name:
        return Path(result.file.path).parent
    if result.signature and result.signature.file and result.signature.file.name:
        return Path(result.signature.file.path).parent
    return None


def _result_file_date(result):
    if not result.file or not result.file.name:
        return None
    filename = Path(result.file.name).name
    prefix = f"result_{result.name}."
    if not filename.startswith(prefix) or not filename.endswith(".csv"):
        return None
    return filename.removeprefix(prefix).removesuffix(".csv")


def _is_result_shard_file(path, *, result, result_date, cutoff):
    filename = path.name
    prefix = f"result_{result.name}."
    if not filename.startswith(prefix) or not filename.endswith(".csv"):
        return False
    if result.file and Path(result.file.name).name == filename:
        return False
    if result_date:
        return filename.endswith(f"-{result_date}.csv")

    escaped_prefix = re.escape(prefix)
    shard_pattern = re.compile(
        rf"^{escaped_prefix}.+-\d+-\d+-\d{{8}}-\d{{6}}-\d{{6}}\.csv$"
    )
    return bool(shard_pattern.match(filename)) and _old_mtime(path, cutoff)


def _delete_result_shard_files(result, *, cutoff, dry_run):
    output_dir = _result_search_output_dir(result)
    if not output_dir or not output_dir.exists():
        return 0

    result_date = _result_file_date(result)
    count = 0
    for path in output_dir.iterdir():
        if not path.is_file():
            continue
        if not _is_result_shard_file(
            path,
            result=result,
            result_date=result_date,
            cutoff=cutoff,
        ):
            continue
        count += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return count


def _delete_result_objects(queryset, *, cutoff, dry_run):
    result_count = 0
    shard_count = 0
    for result in queryset.select_related("signature").iterator():
        result_count += 1
        shard_count += _delete_result_shard_files(
            result,
            cutoff=cutoff,
            dry_run=dry_run,
        )
        if not dry_run:
            result.delete()
    return result_count, shard_count


def _delete_old_files(root, *, cutoff, dry_run, suffixes=None):
    root = Path(root)
    if not root.exists():
        return 0

    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        if not _old_mtime(path, cutoff):
            continue
        count += 1
        if not dry_run:
            path.unlink(missing_ok=True)
    return count


def _remove_empty_dirs(root, *, dry_run):
    root = Path(root)
    if not root.exists():
        return 0

    count = 0
    directories = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            next(directory.iterdir())
        except StopIteration:
            count += 1
            if not dry_run:
                directory.rmdir()
        except FileNotFoundError:
            continue
    return count


def _cleanup_job_rows(now, *, dry_run, summary):
    completed_cutoff = _cutoff(now, settings.RETENTION_COMPLETED_JOBS_DAYS)
    failed_cutoff = _cutoff(now, settings.RETENTION_FAILED_JOBS_DAYS)

    if completed_cutoff is not None:
        summary["completed_jobs"] = _delete_objects(
            Job.objects.filter(
                state=Job.State.COMPLETED,
                finished_at__isnull=False,
                finished_at__lte=completed_cutoff,
            ).order_by("pk"),
            dry_run=dry_run,
        )
    if failed_cutoff is not None:
        summary["failed_jobs"] = _delete_objects(
            Job.objects.filter(
                state=Job.State.FAILED,
                finished_at__isnull=False,
                finished_at__lte=failed_cutoff,
            ).order_by("pk"),
            dry_run=dry_run,
        )


def _cleanup_fastas(now, *, dry_run, summary):
    cutoff = _cutoff(now, settings.RETENTION_UNPROCESSED_FASTA_DAYS)
    if cutoff is None:
        return
    active_fasta_ids = Job.objects.filter(
        state__in=Job.ACTIVE_STATES,
        fasta__isnull=False,
    ).values("fasta_id")
    summary["unprocessed_fastas"] = _delete_objects(
        Fasta.objects.filter(
            processed=False,
            upload_date__lte=cutoff,
        )
        .exclude(pk__in=active_fasta_ids)
        .order_by("pk"),
        dry_run=dry_run,
    )


def _cleanup_results(now, *, dry_run, summary):
    active_result_ids = Job.objects.filter(
        state__in=Job.ACTIVE_STATES,
        result__isnull=False,
    ).values("result_id")

    unwatched_cutoff = _cutoff(now, settings.RETENTION_UNWATCHED_RESULTS_DAYS)
    if unwatched_cutoff is not None:
        result_count, shard_count = _delete_result_objects(
            Result.objects.filter(
                is_watched=False,
                time__lte=unwatched_cutoff,
            )
            .exclude(pk__in=active_result_ids)
            .order_by("pk"),
            cutoff=unwatched_cutoff,
            dry_run=dry_run,
        )
        summary["unwatched_results"] = result_count
        summary["result_shard_files"] += shard_count

    watched_cutoff = _cutoff(now, settings.RETENTION_WATCHED_RESULTS_DAYS)
    if watched_cutoff is not None:
        result_count, shard_count = _delete_result_objects(
            Result.objects.filter(
                is_watched=True,
                time__lte=watched_cutoff,
            )
            .exclude(pk__in=active_result_ids)
            .order_by("pk"),
            cutoff=watched_cutoff,
            dry_run=dry_run,
        )
        summary["watched_results"] = result_count
        summary["result_shard_files"] += shard_count


def _cleanup_signatures(now, *, dry_run, summary):
    cutoff = _cutoff(now, settings.RETENTION_SIGNATURES_DAYS)
    if cutoff is None:
        return
    active_signature_ids = Job.objects.filter(
        state__in=Job.ACTIVE_STATES,
        signature__isnull=False,
    ).values("signature_id")
    summary["orphaned_signatures"] = _delete_objects(
        Signature.objects.filter(date__lte=cutoff)
        .annotate(result_count=Count("result"))
        .filter(result_count=0)
        .exclude(pk__in=active_signature_ids)
        .order_by("pk"),
        dry_run=dry_run,
    )


def _cleanup_files(now, *, dry_run, summary):
    data_dir = Path(settings.DATA_DIR)
    log_dir = Path(settings.LOG_DIR)
    temp_cutoff = _cutoff(now, settings.RETENTION_TEMP_FILES_DAYS)
    failed_index_cutoff = _cutoff(now, settings.RETENTION_FAILED_INDEX_FILES_DAYS)
    log_cutoff = _cutoff(now, settings.RETENTION_LOG_FILES_DAYS)

    for root in (
        data_dir / "tmp",
        data_dir / "SRA" / "metagenomes" / "tmp",
    ):
        summary["temp_files"] += _delete_old_files(
            root,
            cutoff=temp_cutoff,
            dry_run=dry_run,
        )
        summary["empty_dirs"] += _remove_empty_dirs(root, dry_run=dry_run)

    failed_index_root = data_dir / "SRA" / "metagenomes" / "indexing-failed"
    summary["failed_index_files"] += _delete_old_files(
        failed_index_root,
        cutoff=failed_index_cutoff,
        dry_run=dry_run,
    )
    summary["empty_dirs"] += _remove_empty_dirs(failed_index_root, dry_run=dry_run)

    summary["log_files"] += _delete_old_files(
        log_dir,
        cutoff=log_cutoff,
        dry_run=dry_run,
        suffixes={".log"},
    )
    summary["empty_dirs"] += _remove_empty_dirs(log_dir, dry_run=dry_run)


def run_retention_cleanup(*, dry_run=False, now=None):
    now = now or timezone.now()
    summary = _summary()

    _cleanup_job_rows(now, dry_run=dry_run, summary=summary)
    _cleanup_fastas(now, dry_run=dry_run, summary=summary)
    _cleanup_results(now, dry_run=dry_run, summary=summary)
    _cleanup_signatures(now, dry_run=dry_run, summary=summary)
    _cleanup_files(now, dry_run=dry_run, summary=summary)

    LOGGER.info(
        "Retention cleanup completed dry_run=%s summary=%s",
        dry_run,
        summary,
    )
    return summary
