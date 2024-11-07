# mgw_api/management/commands/create_crons.py

import sys
import os
import subprocess
from crontab import CronTab
from django.core.management.base import BaseCommand

from mgw.settings import LOG_DIR
from mgw.settings import LOGGER


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['add', 'remove'], help="Action to perform: add or remove cron jobs from crontab")
        parser.add_argument('manage', type=str, help="Full manage.py path.")

    def handle(self, *args, **options):
        action = options['action'].lower()
        manage_py_path = options['manage']
        try:
            cron_jobs = self.get_cron_jobs(manage_py_path)
            if action == "add":
                self.add_cron_jobs(cron_jobs)
            elif action == "remove":
                self.remove_cron_jobs(cron_jobs)
        except Exception as e:
            LOGGER.error(f"Error adding cron jobs: {e}")

    def get_conda_path(self):
        conda_path = subprocess.check_output(["which", "conda"], text=True).strip()
        return conda_path

    def get_cron_jobs(self, manage_py_path):
        cron_jobs, env_name = list(), "mgw"
        conda_path = self.get_conda_path()
        cron_path = os.path.dirname(os.path.abspath(__file__))
        log_file_path = LOG_DIR / "log_crons.log"
        for script in ["create_daily",]:
            python_command = f"{conda_path} run -n {env_name} {sys.executable} {manage_py_path} {script} >> {log_file_path} 2>&1"
            cron_jobs.append({"schedule":"0 1 * * *", "command":f"{python_command}"})
        # 0 - At minute 0 | 1 - At 1 AM | * - Every day of the month | * - Every month | 6 - On Saturday
        return cron_jobs

    def add_cron_jobs(self, cron_jobs):
        cron = CronTab(user=True)
        for job in cron_jobs:
            if not any(job["command"] in str(existing_job) for existing_job in cron):
                new_job = cron.new(command=job["command"])
                new_job.setall(job["schedule"])
                LOGGER.info(f"Adding cron job: {job["schedule"]} {job["command"]}")
        cron.write()
        LOGGER.info("Cron jobs added.")

    def remove_cron_jobs(self, cron_jobs):
        cron = CronTab(user=True)
        for job in cron_jobs:
            cron.remove_all(command=job["command"])
            LOGGER.info(f"Removed cron job: {job["schedule"]} {job["command"]}")
        cron.write()
        LOGGER.info("Cron jobs removed.")
