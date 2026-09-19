import pymongo as pm
from django.conf import settings
from django.core.management.base import BaseCommand

from mgw_api.database_config import enabled_databases
from mgw_api.database_config import get_database_config
from mgw_api.services.maintenance import run_metadata


def metadata_collection_has_documents(database_id):
    database = get_database_config(database_id)
    mongo = pm.MongoClient(settings.MONGO_URI)
    try:
        db = mongo["sradb"]
        collection = db[database.mongodb_collection]
        return collection.estimated_document_count() > 0
    finally:
        mongo.close()


class Command(BaseCommand):
    help = "Initialize configured metadata collections from the mounted parquet cache."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            action="append",
            dest="databases",
            help=(
                "Database id to initialize. May be passed multiple times. "
                "Defaults to every enabled database."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Import metadata even when the target collection already has documents.",
        )

    def handle(self, *args, **kwargs):
        database_ids = kwargs["databases"] or [
            database.id for database in enabled_databases()
        ]
        initialized = []
        skipped = []
        for database_id in database_ids:
            if kwargs["force"] or not metadata_collection_has_documents(database_id):
                run_metadata(no_download=True, database=database_id)
                initialized.append(database_id)
            else:
                skipped.append(database_id)

        if initialized:
            self.stdout.write(
                self.style.SUCCESS(
                    "Initialized metadata for: " + ", ".join(initialized)
                )
            )
        if skipped:
            self.stdout.write("Metadata already initialized for: " + ", ".join(skipped))
