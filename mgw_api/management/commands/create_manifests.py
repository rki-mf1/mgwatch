from django.core.management.base import BaseCommand

from mgw.settings import LOGGER
from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import batch_manifest
from mgw_api.database_config import get_database_config
from mgw_api.database_config import index_path
from mgw_api.database_config import profile_manifest
from mgw_api.database_config import profile_root
from mgw_api.database_config import read_accession_parquet
from mgw_api.database_config import write_accession_parquet


class Command(BaseCommand):
    help = "Rebuild configured database profile manifests from batch manifests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default=DEFAULT_DATABASE_ID,
            help=f"Configured database id. Defaults to {DEFAULT_DATABASE_ID}.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Allow batches with missing index.rocksdb directories.",
        )

    def handle(self, *args, **options):
        database = get_database_config(options["database"])
        force = options["force"]

        for profile in database.enabled_profiles:
            root = profile_root(database.id, profile)
            root.mkdir(parents=True, exist_ok=True)
            batches = sorted(
                batch
                for batch in root.glob("batch-*")
                if batch.is_dir() and batch.name.removeprefix("batch-").isdigit()
            )
            accessions = []
            for batch in batches:
                batch_number = int(batch.name.removeprefix("batch-"))
                manifest_path = batch_manifest(database.id, profile, batch_number)
                if not manifest_path.exists():
                    LOGGER.warning("Skipping batch without manifest: %s", batch)
                    continue
                if (
                    not force
                    and not index_path(database.id, profile, batch_number).exists()
                ):
                    raise FileNotFoundError(
                        f"Batch manifest has no matching index.rocksdb: {batch}"
                    )
                accessions.extend(read_accession_parquet(manifest_path))

            write_accession_parquet(profile_manifest(database.id, profile), accessions)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Rebuilt {database.id}/{profile.key} manifest with "
                    f"{len(set(accessions))} accessions from {len(batches)} batches."
                )
            )
