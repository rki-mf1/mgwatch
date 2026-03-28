from django.core.management.base import BaseCommand

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import WATCH_QUEUE
from mgw_api.tasks import run_watch_task


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        wait_for_task(run_watch_task, queue=WATCH_QUEUE)
        self.stdout.write(self.style.SUCCESS("Watches completed"))
