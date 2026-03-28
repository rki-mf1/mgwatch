from django.core.management.base import BaseCommand

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import MAINTENANCE_QUEUE
from mgw_api.tasks import run_daily_pipeline_task


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        wait_for_task(run_daily_pipeline_task, queue=MAINTENANCE_QUEUE)
        self.stdout.write(self.style.SUCCESS("Daily update completed"))
