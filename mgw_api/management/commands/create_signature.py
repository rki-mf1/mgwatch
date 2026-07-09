from django.core.management.base import BaseCommand

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.tasks import INTERACTIVE_QUEUE
from mgw_api.tasks import run_create_signature_task


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")

    def handle(self, *args, **kwargs):
        result = wait_for_task(
            run_create_signature_task,
            kwargs={"user_id": kwargs["user_id"], "name": kwargs["name"]},
            queue=INTERACTIVE_QUEUE,
        )
        self.stdout.write(self.style.SUCCESS(f"SIGNATURE_PK: {result['signature_id']}"))
