from django.core.management.base import BaseCommand

from mgw_api.services.maintenance import run_metadata


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--no-download",
            action="store_true",
            help="Do not download latest SRA metadata from S3",
        )
        parser.add_argument(
            "--no-process",
            action="store_true",
            help="Do not process the downloaded SRA data and load it into the mongodb",
        )
        parser.add_argument(
            "--drop-first",
            action="store_true",
            help="Drop the old metadata collection before creating the new one",
        )
        parser.add_argument(
            "--indexed-only",
            action="store_true",
            help="Only save metadata for sequences already in the search index",
        )

    def handle(self, *args, **kwargs):
        run_metadata(
            no_download=kwargs["no_download"],
            no_process=kwargs["no_process"],
            drop_first=kwargs["drop_first"],
            indexed_only=kwargs["indexed_only"],
        )
        self.stdout.write(self.style.SUCCESS("Metadata update completed"))
