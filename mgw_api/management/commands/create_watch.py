from django.core.management.base import BaseCommand

from mgw_api.services.maintenance import run_watch


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        run_watch()
        self.stdout.write(self.style.SUCCESS("Watches completed"))
