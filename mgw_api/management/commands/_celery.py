from django.conf import settings
from django.core.management.base import CommandError

from mgw_api.tasks import submit_task_and_wait


def wait_for_task(task, *, kwargs=None, queue=None):
    try:
        return submit_task_and_wait(
            task,
            kwargs=kwargs or {},
            queue=queue,
            timeout=settings.CELERY_TASK_RESULT_TIMEOUT,
        )
    except Exception as exc:
        raise CommandError(str(exc)) from exc
