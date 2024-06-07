# mgw_api/management/commands/runserver.py

import os
import sys
import signal
import subprocess
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunServerCommand
import time


def start_cron_jobs(manage_py_path, *args):
    subprocess.call(["python", "manage_crons.py", "start", manage_py_path])

def stop_cron_jobs(manage_py_path, *args):
    subprocess.call(["python", "manage_crons.py", "stop", manage_py_path])
    sys.exit(1)

class Command(StaticRunServerCommand):
    def run(self, **options):
        # get manage.py location
        manage_py_path = os.path.abspath("manage.py")
        # stop cron jobs on exit
        ####signal.signal(signal.SIGINT, lambda signal, frame: stop_cron_jobs(manage_py_path, signal, frame))
        ####signal.signal(signal.SIGTERM, lambda signal, frame: stop_cron_jobs(manage_py_path, signal, frame))
        # start cron jobs on server start
        ####start_cron_jobs(manage_py_path)
        # call server
        super().run(**options)
