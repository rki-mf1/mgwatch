from datetime import datetime

from django.db import transaction

from mgw.settings import LOGGER
from mgw_api.models import Job

from .exceptions import JobConflictError


def get_active_job_for_fasta(fasta):
    return (
        Job.objects.filter(
            fasta=fasta,
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state__in=Job.ACTIVE_STATES,
        )
        .order_by("-created_at")
        .first()
    )


def get_active_job_for_signature(signature):
    return (
        Job.objects.filter(
            signature=signature,
            job_type=Job.JobType.SEARCH,
            state__in=Job.ACTIVE_STATES,
        )
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def create_signature_pipeline_job(*, fasta, queue):
    existing = get_active_job_for_fasta(fasta)
    if existing:
        raise JobConflictError(f"An active job already exists for fasta {fasta.pk}.")
    return Job.objects.create(
        job_type=Job.JobType.SIGNATURE_PIPELINE,
        queue=queue,
        user=fasta.user,
        fasta=fasta,
        status_message="Queued",
    )


@transaction.atomic
def create_search_job(*, signature, queue):
    existing = get_active_job_for_signature(signature)
    if existing:
        raise JobConflictError(
            f"An active search job already exists for signature {signature.pk}."
        )
    return Job.objects.create(
        job_type=Job.JobType.SEARCH,
        queue=queue,
        user=signature.user,
        signature=signature,
        fasta=signature.fasta,
        status_message="Queued",
    )


def update_job(
    job,
    *,
    state=None,
    status_message=None,
    progress_current=None,
    progress_total=None,
    celery_task_id=None,
    error_message=None,
    failure_details=None,
    result=None,
    lock_name=None,
    started=False,
    finished=False,
):
    fields = []
    if state is not None:
        job.state = state
        fields.append("state")
    if status_message is not None:
        job.status_message = status_message[:255]
        fields.append("status_message")
    if progress_current is not None:
        job.progress_current = progress_current
        fields.append("progress_current")
    if progress_total is not None:
        job.progress_total = progress_total
        fields.append("progress_total")
    if celery_task_id is not None:
        job.celery_task_id = celery_task_id
        fields.append("celery_task_id")
    if error_message is not None:
        job.error_message = error_message
        fields.append("error_message")
    if failure_details is not None:
        job.failure_details = failure_details
        fields.append("failure_details")
    if result is not None:
        job.result = result
        fields.append("result")
    if lock_name is not None:
        job.lock_name = lock_name
        fields.append("lock_name")
    if started and job.started_at is None:
        job.started_at = datetime.now()
        fields.append("started_at")
    if finished:
        job.finished_at = datetime.now()
        fields.append("finished_at")
    if fields:
        job.save(update_fields=fields)


def sync_fasta_from_job(job):
    fasta = job.fasta
    if not fasta:
        return
    if job.state == Job.State.COMPLETED:
        fasta.status = "Complete"
        fasta.processed = True
    elif job.state == Job.State.FAILED:
        fasta.status = f"Error: {job.error_message or job.status_message}"
        fasta.processed = False
    else:
        fasta.status = job.status_message
        fasta.processed = False
    if job.result_id:
        fasta.result_pk = job.result_id
    fasta.save(update_fields=["status", "processed", "result_pk"])
    LOGGER.debug("Updated fasta %s from job %s", fasta.pk, job.pk)


def mark_job_running(job, *, message, total=0, task_id=None, lock_name=None):
    update_job(
        job,
        state=Job.State.RUNNING,
        status_message=message,
        progress_total=total,
        celery_task_id=task_id,
        lock_name=lock_name,
        started=True,
    )
    sync_fasta_from_job(job)


def mark_job_progress(job, *, message, current, total):
    update_job(
        job,
        state=Job.State.RUNNING,
        status_message=message,
        progress_current=current,
        progress_total=total,
    )
    sync_fasta_from_job(job)


def mark_job_failed(job, exc):
    update_job(
        job,
        state=Job.State.FAILED,
        status_message="Failed",
        error_message=str(exc),
        failure_details={"error": str(exc)},
        finished=True,
    )
    sync_fasta_from_job(job)


def mark_job_completed(job, *, message, result=None):
    update_job(
        job,
        state=Job.State.COMPLETED,
        status_message=message,
        result=result,
        progress_current=job.progress_total,
        finished=True,
    )
    sync_fasta_from_job(job)
