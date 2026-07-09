from django.core.management.base import BaseCommand

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import MAINTENANCE_QUEUE
from mgw_api.tasks import run_download_index_task


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("-n", "--max-downloads", default=None, type=int)
        parser.add_argument("-p", "--max-simultaneous", default=100, type=int)
        parser.add_argument("-t", "--timeout", default=60, type=int)
        parser.add_argument("--ids", nargs="+")
        parser.add_argument("--retry-failed", action="store_true")
        parser.add_argument("--index-max-signatures", default=None, type=int)

    def handle(self, *args, **kwargs):
        wait_for_task(
            run_download_index_task,
            kwargs={
                "max_downloads": kwargs["max_downloads"],
                "max_simultaneous": kwargs["max_simultaneous"],
                "timeout": kwargs["timeout"],
                "ids": kwargs["ids"],
                "retry_failed": kwargs["retry_failed"],
                "index_max_signatures": kwargs["index_max_signatures"],
            },
            queue=MAINTENANCE_QUEUE,
        )
        self.stdout.write(self.style.SUCCESS("Download/index update completed"))
