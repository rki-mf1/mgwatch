from django.core.management.base import BaseCommand

from mgw_api.services.maintenance import run_downloads
from mgw_api.services.maintenance import run_index
from mgw_api.services.maintenance import run_metadata
from mgw_api.services.maintenance import run_watch


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        run_metadata()
        run_downloads()
        run_index()
        run_watch()
        self.stdout.write(self.style.SUCCESS("Daily update completed"))
