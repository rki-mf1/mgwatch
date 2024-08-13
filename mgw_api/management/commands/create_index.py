# mgw_api/management/commands/create_index.py
import os
import shutil
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

from datetime import datetime
import subprocess
import glob
import pickle


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_index - "
        call_command('create_watch')
        try:
            kmers = [21,31,51]
            database = "SRA"
            sig_list = os.path.join(settings.EXTERNAL_DATA_DIR, database, f"sig-list.txt")
            manifest = os.path.join(settings.EXTERNAL_DATA_DIR, database, f"manifest.pcl")
            dir_paths = self.handle_dirs(database)
            sig_files = self.get_manifest(manifest, dir_paths)
            new_files = self.check_updates(sig_files, dir_paths)
            if new_files:
                self.create_list(new_files, sig_list)
                results = [self.update_index(dir_paths, sig_list, database, k) for k in kmers]
                td, rs = ("failed", ".err") if sum([int(r.returncode) for r in results]) else ("signatures", "")
                self.move_files(new_files, dir_paths, td, rs)
                self.update_manifest(new_files, sig_files, manifest)
                self.stdout.write(self.style.SUCCESS(f"{log}Updated index and moved new signatures."))
                call_command('create_watch')
            else:
                self.stdout.write(self.style.SUCCESS(f"{log}No new files to process in {dir_paths['updates']}."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"{log}Error processing directory '{settings.EXTERNAL_DATA_DIR}': {e}"))

    def handle_dirs(self, database):
        dir_names = ["updates", "index", "signatures", "failed"]
        dir_paths = {n:os.path.join(settings.EXTERNAL_DATA_DIR, database, n) for n in dir_names}
        ## check data directories
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
        return dir_paths

    def get_manifest(self, manifest, dir_paths):
        if not os.path.exists(manifest):
            sig_files = [os.path.basename(f) for f in glob.glob(os.path.join(dir_paths["signatures"], "*.sig.gz"))]
            with open(manifest, "wb") as pcl_out:
                pickle.dump(sig_files, pcl_out , protocol=4)
        else:
            with open(manifest, "rb") as pcl_in:
                sig_files = pickle.load(pcl_in)
        return sig_files

    def check_updates(self, sig_files, dir_paths):
        new_files = glob.glob(os.path.join(dir_paths["updates"], "*.sig.gz"))
        dup_files = [file for file in new_files if os.path.basename(file) in sig_files]
        new_files = [file for file in new_files if file not in dup_files]
        self.move_files(dup_files, dir_paths, "failed", ".dup")
        return new_files

    def move_files(self, file_list, dir_paths, target_dir, reason):
        for file in file_list:
            base_name = os.path.basename(file)
            name, ext = os.path.splitext(base_name)
            if target_dir == "failed":
                now = datetime.now()
                dt = now.strftime(".%Y%m%d-%H%M%S")
            else: dt = ""
            destination = os.path.join(dir_paths[target_dir], f"{name}{dt}{reason}{ext}")
            shutil.move(file, destination)

    def create_list(self, new_files, sig_list):
        with open(sig_list, "w") as sl:
            sl.writelines(f"{fp}\n" for fp in new_files)

    def update_index(self, dir_paths, sig_list, database, k):
        idx = os.path.join(dir_paths["index"], f"{database}-{k}.rocksdb")
        cmd = ["sourmash", "scripts", "index", "--ksize", f"{k}", sig_list, "--moltype", "DNA", "--scaled", "1000", "--cores", "20", "--output", idx]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result # returncode: 0 = success, 255 = fail

    def update_manifest(self, new_files, sig_files, manifest):
        new_files = [os.path.basename(file) for file in new_files]
        sig_files = sig_files + new_files
        with open(manifest, "wb") as pcl_out:
            pickle.dump(sig_files, pcl_out , protocol=4)
