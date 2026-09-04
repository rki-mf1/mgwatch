from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from mgw_api.services.stats import record_index_stats
from mgw_api.services.stats import record_metadata_stats


class Command(BaseCommand):
    help = (
        "Refresh cached index and metadata statistics from the current local "
        "index manifest and metadata collection. Use --index-only to force "
        "the cached index sample count to match the manifest on disk after "
        "manual index changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="SRA",
            help="Database name to use for the index manifest. Defaults to SRA.",
        )
        parser.add_argument(
            "--index-only",
            action="store_true",
            help=(
                "Only refresh the cached index sample count from the on-disk "
                "manifest."
            ),
        )
        parser.add_argument(
            "--metadata-only",
            action="store_true",
            help="Only refresh the cached metadata sample count.",
        )

    def handle(self, *args, **kwargs):
        if kwargs["index_only"] and kwargs["metadata_only"]:
            raise CommandError("--index-only and --metadata-only cannot be combined")

        update_index = not kwargs["metadata_only"]
        update_metadata = not kwargs["index_only"]

        if update_index:
            index_stat = record_index_stats(database=kwargs["database"])
            self.stdout.write(
                self.style.SUCCESS(f"Index samples: {int(index_stat.value):,}")
            )

        if update_metadata:
            metadata_stat = record_metadata_stats()
            self.stdout.write(
                self.style.SUCCESS(f"Metadata samples: {int(metadata_stat.value):,}")
            )
