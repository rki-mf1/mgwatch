from django.core.management.base import BaseCommand

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import INDEX_QUEUE
from mgw_api.tasks import run_index_task


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("-n", "--index-max-signatures", default=None, type=int)
        parser.add_argument("--database", default=DEFAULT_DATABASE_ID)

    def handle(self, *args, **kwargs):
        wait_for_task(
            run_index_task,
            kwargs={
                "index_max_signatures": kwargs["index_max_signatures"],
                "database": kwargs["database"],
            },
            queue=INDEX_QUEUE,
        )
        self.stdout.write(self.style.SUCCESS("Index update completed"))
