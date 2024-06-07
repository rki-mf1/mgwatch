# mgw_api/management/commands/manage_crons.py

import sys
import os
import subprocess
from crontab import CronTab

def get_conda_path():
    try:
        conda_path = subprocess.check_output(["which", "conda"], text=True).strip()
        return conda_path
    except subprocess.CalledProcessError:
        print("Error: Conda not found in the system PATH.")
        sys.exit(1)

def get_cron_jobs():
    conda_path = get_conda_path()
    conda_activate_path = os.path.join(os.path.dirname(conda_path), "activate")
    env_name = "mgw"
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "process_fasta.py")
    log_file_path = "Documents/branchwater/mgw/mgw_api/management/commands/cronlog.log"
    sleep_command = "sleep 10"
    python_command = f"{conda_path} run -n {env_name} python {script_path} >> {log_file_path} 2>&1"
    cron_jobs = [{"schedule":"*/1 * * * *", "command":f"{sleep_command}; {python_command}"},]
    return cron_jobs

def start_cron_jobs(cron_jobs):
    cron = CronTab(user=True)
    for job in cron_jobs:
        if not any(job["command"] in str(existing_job) for existing_job in cron):
            new_job = cron.new(command=job["command"])
            new_job.setall(job["schedule"])
            print(f"Adding cron job: {job["schedule"]} {job["command"]}")
    cron.write()
    print("Cron jobs started.")

def stop_cron_jobs(cron_jobs):
    cron = CronTab(user=True)
    for job in cron_jobs:
        cron.remove_all(command=job["command"])
        print(f"Removing cron job: {job["schedule"]} {job["command"]}")
    cron.write()
    print("Cron jobs stopped.")

if __name__ == "__main__":
    action = sys.argv[1].lower()
    manage_py_path = sys.argv[2]
    cron_jobs = get_cron_jobs()
    if action == "start":
        start_cron_jobs()
    elif action == "stop":
        stop_cron_jobs()
