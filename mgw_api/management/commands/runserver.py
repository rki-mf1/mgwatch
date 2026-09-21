# mgw_api/management/commands/runserver.py

import os

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticRunServerCommand,
)

from mgw.settings import LOGGER
from mgw_api.database_config import enabled_databases
from mgw_api.database_config import metadata_init_flag


class Command(StaticRunServerCommand):
    def run(self, **options):
        if os.environ.get("RUN_MAIN") != "true":
            # Create initial metadata
            legacy_init_flag = (
                settings.DATA_DIR / "SRA" / "metadata" / "initial_setup.txt"
            )
            from mgw_api.services.maintenance import run_metadata

            # Skip downloading to restore the original behaviour we had
            # before arguments were added to create_metadata
            for database in enabled_databases():
                init_flag = metadata_init_flag(database.id)
                if not init_flag.exists():
                    LOGGER.info("Creating initial metadata for %s.", database.id)
                    if legacy_init_flag.exists():
                        LOGGER.info(
                            "Legacy metadata flag exists, importing metadata into the "
                            "configured collection."
                        )
                    run_metadata(no_download=True, database=database.id)

        # Call Django's runserver
        super().run(**options)
