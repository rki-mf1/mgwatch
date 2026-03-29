from celery import shared_task
from django.db import transaction

from mgw_api.locking import acquire_lock
from mgw_api.models import Job
from mgw_api.models import Signature
from mgw_api.services.exceptions import JobConflictError
from mgw_api.services.jobs import create_search_job
from mgw_api.services.jobs import create_signature_pipeline_job
from mgw_api.services.jobs import mark_job_completed
from mgw_api.services.jobs import mark_job_failed
from mgw_api.services.jobs import mark_job_progress
from mgw_api.services.jobs import mark_job_running
from mgw_api.services.jobs import sync_fasta_from_job
from mgw_api.services.jobs import update_job
from mgw_api.services.searches import run_search
from mgw_api.services.signatures import create_signature

INTERACTIVE_QUEUE = "interactive"
MAINTENANCE_QUEUE = "maintenance"
INDEX_QUEUE = "indexing"
WATCH_QUEUE = "watches"
NO_RETRY_TASK_OPTIONS = {
    "bind": True,
    "autoretry_for": (),
    "retry_backoff": False,
    "max_retries": 0,
}


def _queue_for_job_type(job_type):
    return {
        Job.JobType.SIGNATURE_PIPELINE: INTERACTIVE_QUEUE,
        Job.JobType.SEARCH: INTERACTIVE_QUEUE,
        Job.JobType.CREATE_SIGNATURE: INTERACTIVE_QUEUE,
        Job.JobType.METADATA: MAINTENANCE_QUEUE,
        Job.JobType.DOWNLOADS: MAINTENANCE_QUEUE,
        Job.JobType.INDEX: INDEX_QUEUE,
        Job.JobType.WATCH: WATCH_QUEUE,
        Job.JobType.DAILY: MAINTENANCE_QUEUE,
    }[job_type]


def submit_signature_pipeline_job(*, fasta):
    try:
        job = create_signature_pipeline_job(fasta=fasta, queue=INTERACTIVE_QUEUE)
    except JobConflictError:
        return (
            Job.objects.filter(
                fasta=fasta,
                job_type=Job.JobType.SIGNATURE_PIPELINE,
                state__in=Job.ACTIVE_STATES,
            )
            .order_by("-created_at")
            .first()
        )

    def enqueue():
        async_result = run_signature_pipeline.apply_async(
            kwargs={"job_id": job.pk, "user_id": fasta.user_id, "name": fasta.name},
            queue=INTERACTIVE_QUEUE,
        )
        update_job(job, celery_task_id=async_result.id)
        sync_fasta_from_job(job)

    transaction.on_commit(enqueue)
    return job


def submit_search_job(*, signature):
    try:
        job = create_search_job(signature=signature, queue=INTERACTIVE_QUEUE)
    except JobConflictError:
        return (
            Job.objects.filter(
                signature=signature,
                job_type=Job.JobType.SEARCH,
                state__in=Job.ACTIVE_STATES,
            )
            .order_by("-created_at")
            .first()
        )

    def enqueue():
        async_result = run_search_task.apply_async(
            kwargs={
                "job_id": job.pk,
                "user_id": signature.user_id,
                "name": signature.name,
                "watch": "False",
            },
            queue=INTERACTIVE_QUEUE,
        )
        update_job(job, celery_task_id=async_result.id)
        sync_fasta_from_job(job)

    transaction.on_commit(enqueue)
    return job


def submit_task_and_wait(task, *, kwargs, queue=None, timeout=None):
    async_result = task.apply_async(kwargs=kwargs, queue=queue)
    return async_result.get(timeout=timeout)


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_signature_pipeline(self, *, job_id, user_id, name):
    job = Job.objects.get(pk=job_id)
    mark_job_running(
        job,
        message="Creating signature",
        task_id=self.request.id,
    )
    try:
        create_signature(user_id=user_id, name=name)

        def progress_callback(current, total):
            mark_job_progress(
                job,
                message=f"Searching indexes {current}/{total}",
                current=current,
                total=total,
            )

        def state_callback(state):
            if state == Job.State.COMBINING_RESULTS:
                update_job(
                    job,
                    state=Job.State.COMBINING_RESULTS,
                    status_message="Combining results",
                )
            elif state == Job.State.SAVING_RESULT:
                update_job(
                    job,
                    state=Job.State.SAVING_RESULT,
                    status_message="Saving result",
                )

        result = run_search(
            user_id=user_id,
            name=name,
            watch="False",
            progress_callback=progress_callback,
            state_callback=state_callback,
        )
        signature = Signature.objects.get(user_id=user_id, name=name)
        result_obj = signature.result_set.latest("time")
        mark_job_completed(job, message="Complete", result=result_obj)
        return result
    except Exception as exc:
        mark_job_failed(job, exc)
        raise


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_search_task(self, *, job_id, user_id, name, watch="False", parent_job_id=None):
    job = Job.objects.get(pk=job_id)
    mark_job_running(
        job,
        message="Preparing search",
        task_id=self.request.id,
    )

    def progress_callback(current, total):
        mark_job_progress(
            job,
            message=f"Searching indexes {current}/{total}",
            current=current,
            total=total,
        )
        if parent_job_id:
            parent_job = Job.objects.get(pk=parent_job_id)
            mark_job_progress(
                parent_job,
                message=f"Searching indexes {current}/{total}",
                current=current,
                total=total,
            )

    def state_callback(state):
        if state == Job.State.COMBINING_RESULTS:
            update_job(
                job,
                state=Job.State.COMBINING_RESULTS,
                status_message="Combining results",
            )
        elif state == Job.State.SAVING_RESULT:
            update_job(
                job,
                state=Job.State.SAVING_RESULT,
                status_message="Saving result",
            )

    try:
        result = run_search(
            user_id=user_id,
            name=name,
            watch=watch,
            progress_callback=progress_callback,
            state_callback=state_callback,
        )
        signature = Signature.objects.get(user_id=user_id, name=name)
        result_obj = signature.result_set.latest("time")
        mark_job_completed(job, message="Complete", result=result_obj)
        return result
    except Exception as exc:
        mark_job_failed(job, exc)
        raise


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_create_signature_task(self, *, user_id, name):
    return {"signature_id": create_signature(user_id=user_id, name=name).pk}


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_metadata_task(self, **kwargs):
    from mgw_api.services.maintenance import run_metadata

    with acquire_lock("maintenance-pipeline-lock"):
        return run_metadata(**kwargs)


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_downloads_task(self, **kwargs):
    from mgw_api.services.maintenance import run_downloads

    with acquire_lock("downloads-lock"):
        with acquire_lock("download-index-exclusive-lock"):
            return run_downloads(**kwargs)


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_index_task(self, **kwargs):
    from mgw_api.services.maintenance import run_index

    with acquire_lock("index-lock"):
        with acquire_lock("download-index-exclusive-lock"):
            return run_index(**kwargs)


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_watch_task(self, **kwargs):
    from mgw_api.services.maintenance import run_watch

    return run_watch(**kwargs)


@shared_task(**NO_RETRY_TASK_OPTIONS)
def run_daily_pipeline_task(self):
    run_metadata_task.apply(kwargs={}).get()
    run_downloads_task.apply(kwargs={}).get()
    run_index_task.apply(kwargs={}).get()
    return run_watch_task.apply(kwargs={}).get()
