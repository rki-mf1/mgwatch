# mgw_api/management/commands/manage_crons.py

import os
import subprocess
import threading
from django.core.management.base import BaseCommand
from django.conf import settings

from datetime import datetime

class Command(BaseCommand):
    help = "Start or stop the mongodb server"

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'stop'])

    def handle(self, *args, **options):
        action = options['action']
        if action == 'start':
            self.start_mongodb_server()
        elif action == 'stop':
            self.stop_mongodb_server()

    def start_mongodb_server(self):
        database = "SRA"
        dir_paths = self.handle_dirs(database, ["mongodb"])
        #mongodb_log = os.path.join(settings.EXTERNAL_DATA_DIR, database, f"mongod.log")
        start_command = ["mongod", "--dbpath", dir_paths["mongodb"], "--port", "27017", "--quiet"]
        #, "--logpath", mongodb_log, "--logappend"]
        def run_mongo():
            with open(os.devnull, 'wb') as devnull:
                subprocess.run(start_command, check=True, stdout=devnull, stderr=devnull)
        self.thread = threading.Thread(target=run_mongo)
        self.thread.start()
        self.write_log(f"MongoDB server started on port 27017.")
        self.stdout.write(self.style.SUCCESS('MongoDB server started on port 27017'))

    def stop_mongodb_server(self):
        database = "SRA"
        dir_paths = self.handle_dirs(database, ["mongodb"])
        if hasattr(self, 'thread') and self.thread.is_alive():
            stop_command = ["mongod", "--shutdown", "--dbpath", dir_paths["mongodb"]]
            with open(os.devnull, 'wb') as devnull:
                subprocess.run(stop_command, check=True, stdout=devnull, stderr=devnull)
            self.thread.join()
            self.stdout.write(self.style.SUCCESS('MongoDB server stopped'))
            self.write_log(f"MongoDB server stopped.")
        else:
            self.stdout.write(self.style.WARNING('MongoDB server is not running'))

    def handle_dirs(self, database, dir_names):
        dir_paths = {n:os.path.join(settings.EXTERNAL_DATA_DIR, database, "metadata", n) for n in dir_names}
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o700)
        return dir_paths
    
    def write_log(self, message):
        logfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log_mongodb.log")
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        with open(logfile, "a") as logf:
            logf.write(f"{dt} - Status: {message}\n")