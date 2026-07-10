from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from mgw_api.management.commands._celery import wait_for_task
from mgw_api.models import Job
from mgw_api.models import Signature
from mgw_api.services.jobs import create_search_job
from mgw_api.tasks import INTERACTIVE_QUEUE
from mgw_api.tasks import run_search_task


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")
        parser.add_argument("watch", type=str, nargs="?", default="False")

    def handle(self, *args, **kwargs):
        user_id, name, watch = kwargs["user_id"], kwargs["name"], kwargs["watch"]
        if watch == "False":
            signature = Signature.objects.get(user_id=user_id, name=name)
            signature.submitted = True
            signature.save(update_fields=["submitted"])
            try:
                job = create_search_job(signature=signature, queue=INTERACTIVE_QUEUE)
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            result = wait_for_task(
                run_search_task,
                kwargs={
                    "job_id": job.pk,
                    "user_id": user_id,
                    "name": name,
                    "watch": watch,
                },
                queue=INTERACTIVE_QUEUE,
            )
        else:
            temp_job = Job.objects.create(
                job_type=Job.JobType.WATCH,
                queue=INTERACTIVE_QUEUE,
                user_id=user_id,
                status_message="Queued",
            )
            result = wait_for_task(
                run_search_task,
                kwargs={
                    "job_id": temp_job.pk,
                    "user_id": user_id,
                    "name": name,
                    "watch": watch,
                },
                queue=INTERACTIVE_QUEUE,
            )
        self.stdout.write(self.style.SUCCESS(f"RESULT_PK: {result['result_pk']}"))
