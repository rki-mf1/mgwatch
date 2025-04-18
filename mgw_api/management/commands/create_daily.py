# mgw_api/management/commands/create_daily.py
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        try:
            # call_command("create_metadata")
            # call_command("create_downloads")
            # call_command("create_index")
            # call_command("create_watch")
            LOGGER.info("Daily update successful")
        except Exception as e:
            LOGGER.error(f"Error processing daily update: {e}")
