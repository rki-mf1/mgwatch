from django.core.management.base import BaseCommand

from mgw_api.models import Signature
from mgw_api.services.searches import run_search


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")
        parser.add_argument("watch", type=str, nargs="?", default="False")

    def handle(self, *args, **kwargs):
        user_id = kwargs["user_id"]
        name = kwargs["name"]
        watch = kwargs["watch"]
        if watch == "False":
            signature = Signature.objects.get(user_id=user_id, name=name)
            signature.submitted = True
            signature.save(update_fields=["submitted"])
        result = run_search(user_id=user_id, name=name, watch=watch)
        self.stdout.write(self.style.SUCCESS(f"RESULT_PK: {result['result_pk']}"))
