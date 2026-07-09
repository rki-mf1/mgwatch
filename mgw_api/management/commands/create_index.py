from django.core.management.base import BaseCommand

from mgw_api.services.maintenance import run_index


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        run_index()
        self.stdout.write(self.style.SUCCESS("Index update completed"))
