# mgw_api/management/commands/return_command.py

from django.core.management.base import BaseCommand

class CommandWithReturnValue(BaseCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.return_value = None
