# mgw_api/management/commands/create_daily.py
import os
import shutil
from django.core.management.base import BaseCommand
from django.core.management import call_command
from datetime import datetime


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_daily - "
        try:
            #call_command("create_metadata")
            #call_command("create_index")
            call_command("create_watch")
            self.stdout.write(self.style.SUCCESS(f"{log}Daily update successful."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"{log}Error processing daily update: {e}"))
