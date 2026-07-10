from django.core.management.base import BaseCommand

from mgw_api.services.signatures import create_signature


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")

    def handle(self, *args, **kwargs):
        signature = create_signature(user_id=kwargs["user_id"], name=kwargs["name"])
        self.stdout.write(self.style.SUCCESS(f"SIGNATURE_PK: {signature.pk}"))
