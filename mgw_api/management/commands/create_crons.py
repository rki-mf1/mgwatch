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
        try:
            if action == "add":
                # Clear out old jobs before adding our new jobs, to avoid
                # duplicates
                self.remove_cron_jobs()
                manage_py_path = options['manage']
                cron_jobs = self.get_cron_jobs(manage_py_path)
                self.add_cron_jobs(cron_jobs)
            elif action == "remove":
                self.remove_cron_jobs()
        except Exception as e:
            LOGGER.error(f"Error adding cron jobs: {e}")

    def get_conda_path(self):
        conda_path = subprocess.check_output(["which", "conda"], text=True).strip()
        return conda_path

    def get_cron_jobs(self, manage_py_path):
        """Generate the crontab lines we want to add for each command"""
        cron_jobs, env_name = list(), "mgw"
        conda_path = self.get_conda_path()
        cron_path = os.path.dirname(os.path.abspath(__file__))
        log_file_path = LOG_DIR / "log_crons.log"
        for script in ["create_daily",]:
            python_command = f"{conda_path} run -n {env_name} {sys.executable} {manage_py_path} {script} >> {log_file_path} 2>&1"
            # 0 - At minute 0 | 1 - At 1 AM | * - Every day of the month | * - Every month | 6 - On Saturday
            cron_jobs.append({"schedule":"0 1 * * *", "command":f"{python_command}"})
        return cron_jobs

    def add_cron_jobs(self, cron_jobs):
        """Add cron jobs to the crontab

        We tag each job with the 'mgwatch' comment, so we can easily identify
        mgwatch-related commands at a later time, even if the command itself
        changes. This helps us avoid adding duplicate crontab entries.
        """
        cron = CronTab(user=True)
        for job in cron_jobs:
            if not any(job["command"] in str(existing_job) for existing_job in cron):
                # Add the comment 'mgwatch' so that we can easily remove these commands as needed
                new_job = cron.new(command=job["command"], comment="mgwatch")
                new_job.setall(job["schedule"])
                LOGGER.info(f"Adding cron job: {job["schedule"]} {job["command"]}")
        cron.write()
        LOGGER.info("Cron jobs added.")

    def remove_cron_jobs(self):
        """Remove all mgwatch cron jobs from the crontab
        """
        cron = CronTab(user=True)
        cron.remove_all(comment="mgwatch")
        cron.write()
        LOGGER.info("mgwatch cron jobs removed from crontab.")
