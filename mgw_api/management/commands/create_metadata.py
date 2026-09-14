from django.core.management.base import BaseCommand

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import MAINTENANCE_QUEUE
from mgw_api.tasks import run_metadata_task


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--no-download", action="store_true")
        parser.add_argument("--no-process", action="store_true")
        parser.add_argument("--drop-first", action="store_true")
        parser.add_argument("--indexed-only", action="store_true")
        parser.add_argument("--database", default=DEFAULT_DATABASE_ID)

    def handle(self, *args, **kwargs):
        wait_for_task(
            run_metadata_task,
            kwargs={
                "no_download": kwargs["no_download"],
                "no_process": kwargs["no_process"],
                "drop_first": kwargs["drop_first"],
                "indexed_only": kwargs["indexed_only"],
                "database": kwargs["database"],
            },
            queue=MAINTENANCE_QUEUE,
        )
        self.stdout.write(self.style.SUCCESS("Metadata update completed"))
