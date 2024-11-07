# mgw_api/apps.py

import os
import signal
import sys
from django.apps import AppConfig
from django.core.management import call_command

from mgw.settings import LOGGER


class MgwApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mgw_api'

    def ready(self):
        import mgw_api.signals

        # Extra code to initialize cronjobs. Copied from custom runserver.
        self.manage_py_path = os.path.abspath("manage.py")
        LOGGER.info("Starting cron jobs...")
        call_command('create_crons', 'add', self.manage_py_path)

        # Stop cron jobs on exit
        signal.signal(signal.SIGINT, self.stop_services)
        signal.signal(signal.SIGTERM, self.stop_services)

    def stop_services(self, signum, frame):
        LOGGER.info("Stopping cron jobs...")
        call_command('create_crons', 'remove', self.manage_py_path)
        sys.exit(0)
