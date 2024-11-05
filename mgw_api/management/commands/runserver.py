# mgw_api/management/commands/runserver.py

import os
import sys
import signal
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunServerCommand
from django.core.management import call_command
from django.conf import settings


class Command(StaticRunServerCommand):
    def run(self, **options):
        self.manage_py_path = os.path.abspath("manage.py")
        if os.environ.get('RUN_MAIN') != 'true':
            # Start cron jobs
            print("Starting cron jobs...")
            call_command('create_crons', 'start', self.manage_py_path)
            # Start the mail server
            print("Starting mail server...")
            call_command('create_mail', 'start')
            # Create initial metadata
            init_flag = os.path.join(settings.DATA_DIR, "SRA", "metadata", "initial_setup.txt")
            if not os.path.exists(init_flag):
                print("Creating initial metadata...")
                # Skip downloading to restore the original behaviour we had
                # before arguments were added to create_metadata
                call_command('create_metadata', '--no-download')

        # Stop cron jobs and mail server on exit
        signal.signal(signal.SIGINT, self.stop_services)
        signal.signal(signal.SIGTERM, self.stop_services)
        
        # Call Django's runserver
        super().run(**options)

    def stop_services(self, signum, frame):
        print("Stopping cron jobs...")
        call_command('create_crons', 'stop', self.manage_py_path)
        print("Stopping mail server...")
        call_command('create_mail', 'stop')
        sys.exit(0)
