# mgw_api/management/commands/runserver.py

import os
import sys
import signal
import subprocess
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunServerCommand
import time


def start_cron_jobs(manage_py_path, command_path):
    print(manage_py_path)
    print(command_path)
    subprocess.call([sys.executable, os.path.join(command_path, f"manage_crons.py"), "start", manage_py_path])

def stop_cron_jobs(manage_py_path, command_path, *args):
    subprocess.call([sys.executable, os.path.join(command_path, f"manage_crons.py"), "stop", manage_py_path])
    sys.exit(1)

class Command(StaticRunServerCommand):
    def run(self, **options):
        # get manage.py location
        manage_py_path = os.path.abspath("manage.py")
        command_path = os.path.dirname(os.path.abspath(__file__))
        # stop running cron jobs
        #stop_cron_jobs(manage_py_path, command_path)
        # stop cron jobs on exit
        signal.signal(signal.SIGINT, lambda signal, frame: stop_cron_jobs(manage_py_path, command_path, signal, frame))
        signal.signal(signal.SIGTERM, lambda signal, frame: stop_cron_jobs(manage_py_path, command_path, signal, frame))
        # start cron jobs on server start
        start_cron_jobs(manage_py_path, command_path)
        # call server
        super().run(**options)
