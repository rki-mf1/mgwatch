# mgw_api/management/commands/runserver.py

import os

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticRunServerCommand,
)
from django.core.management import call_command

from mgw.settings import LOGGER


class Command(StaticRunServerCommand):
    def run(self, **options):
        if os.environ.get("RUN_MAIN") != "true":
            # Create initial metadata
            init_flag = os.path.join(
                settings.DATA_DIR, "SRA", "metadata", "initial_setup.txt"
            )
            if not os.path.exists(init_flag):
                LOGGER.info("Creating initial metadata.")
                # Skip downloading to restore the original behaviour we had
                # before arguments were added to create_metadata
                call_command("create_metadata", "--no-download")

        # Call Django's runserver
        super().run(**options)
