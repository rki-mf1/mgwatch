# mgw_api/management/commands/runserver.py

import os
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticRunServerCommand,
)

from mgw.settings import LOGGER


class Command(StaticRunServerCommand):
    def run(self, **options):
        if os.environ.get("RUN_MAIN") != "true":
            # Create initial metadata
            init_flag = (
                Path(settings.DATA_DIR) / "SRA" / "metadata" / "initial_setup.txt"
            )
            if not init_flag.exists():
                LOGGER.info("Creating initial metadata.")
                from mgw_api.services.maintenance import run_metadata

                # Skip downloading to restore the original behaviour we had
                # before arguments were added to create_metadata
                run_metadata(no_download=True)

        # Call Django's runserver
        super().run(**options)
