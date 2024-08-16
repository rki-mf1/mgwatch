# mgw_api/management/commands/manage_crons.py

import sys
import os
import subprocess
from crontab import CronTab
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'stop'], help="Action to perform: start or stop cron jobs")
        parser.add_argument('manage', type=str, help="Full manage.py path.")

    def handle(self, *args, **options):
        action = options['action'].lower()
        manage_py_path = options['manage']
        try:
            cron_jobs = self.get_cron_jobs(manage_py_path)
            if action == "start":
                self.start_cron_jobs(cron_jobs)
            elif action == "stop":
                self.stop_cron_jobs(cron_jobs)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error starting cron jobs: {e}"))

    def get_conda_path(self):
        conda_path = subprocess.check_output(["which", "mamba"], text=True).strip()
        return conda_path

    def get_cron_jobs(self, manage_py_path):
        cron_jobs, env_name = list(), "mgw"
        conda_path = self.get_conda_path()
        cron_path = os.path.dirname(os.path.abspath(__file__))
        log_file_path = os.path.join(cron_path, "cronlog.log")
        for script in ["create_index",]:
            python_command = f"{conda_path} run -n {env_name} {sys.executable} {manage_py_path} {script} >> {log_file_path} 2>&1"
            cron_jobs.append({"schedule":"0 * * * *", "command":f"{python_command}"})
        ##0 - At minute 0 | 1 - At 1 AM | * - Every day of the month | * - Every month | 6 - On Saturday
        return cron_jobs
    
    def start_cron_jobs(self, cron_jobs):
        cron = CronTab(user=True)
        for job in cron_jobs:
            if not any(job["command"] in str(existing_job) for existing_job in cron):
                new_job = cron.new(command=job["command"])
                new_job.setall(job["schedule"])
                print(f"Adding cron job: {job["schedule"]} {job["command"]}")
        cron.write()
        print("Cron jobs started.")

    def stop_cron_jobs(self, cron_jobs):
        cron = CronTab(user=True)
        for job in cron_jobs:
            cron.remove_all(command=job["command"])
            print(f"Removing cron job: {job["schedule"]} {job["command"]}")
        cron.write()
        print("Cron jobs stopped.")
