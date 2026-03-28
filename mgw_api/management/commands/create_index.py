from django.core.management.base import BaseCommand

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import INDEX_QUEUE
from mgw_api.tasks import run_index_task


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        wait_for_task(run_index_task, queue=INDEX_QUEUE)
        self.stdout.write(self.style.SUCCESS("Index update completed"))
