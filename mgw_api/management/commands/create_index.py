import glob
import multiprocessing as mp
import os
import pickle
import shutil
import subprocess
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        try:
            kmers = [21, 31, 51]
            database = "SRA"
            metagenomes_dir = settings.DATA_DIR / database / "metagenomes"
            sig_list = metagenomes_dir / "sig-list.txt"
            manifest = metagenomes_dir / "manifest.pcl"
            dir_paths = self.handle_dirs(
                database, ["updates", "index", "signatures", "failed", "manifests"]
            )
            mani_list = self.get_manifest(manifest)
            last_sig_files, last_num = self.get_last_index(dir_paths)
            LOGGER.debug(f"Already in most recent index: {last_sig_files}")
            new_sig_files = self.check_updates(dir_paths)
            LOGGER.debug(
                f"Will be added to the above and index rebuilt: {new_sig_files}"
            )
            if new_sig_files:
                sig_files = last_sig_files + new_sig_files
                indexing_ever_failed = False
                for i in range(0, len(sig_files), settings.INDEX_MAX_SIGNATURES):
                    new_files = sig_files[i : i + settings.INDEX_MAX_SIGNATURES]
                    self.create_list(new_files, sig_list)
                    LOGGER.info(f"Sigs: {len(new_files)} | Num: {last_num+i}")
                    retvals = [
                        self.update_index(
                            dir_paths, sig_list, database, k, last_num + i
                        )
                        for k in kmers
                    ]
                    indexing_succeeded = all([val == 0 for val in retvals])
                    target_dir = "signatures" if indexing_succeeded else "failed"
                    self.move_files(new_files, dir_paths, target_dir)
                    if indexing_succeeded:
                        self.update_manifests(
                            new_files, mani_list, manifest, dir_paths, last_num + i
                        )
                        LOGGER.info(
                            f"Updated index #{last_num+i} with {len(last_sig_files)} recalculated signatures and {len(new_sig_files)} new added signatures."
                        )
                    indexing_ever_failed = (
                        indexing_ever_failed or not indexing_succeeded
                    )
                if not indexing_ever_failed:
                    # Empty the list of signatures that were downloaded but not
                    # yet indexed, since all signatures have now been added to
                    # the index
                    self.save_pickle(
                        set(),
                        os.path.join(
                            settings.DATA_DIR,
                            database,
                            "metagenomes",
                            "update_successful.pcl",
                        ),
                    )
                LOGGER.info(f"Updating index finished, current index is #{last_num+i}.")
            else:
                LOGGER.info(f"No new files to process in {dir_paths['updates']}.")
        except Exception as e:
            LOGGER.error(f"Error processing directory '{settings.DATA_DIR}': {e}")

    def handle_dirs(self, database, dir_names):
        dir_paths = {
            n: settings.DATA_DIR / database / "metagenomes" / n for n in dir_names
        }
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o700)
        return dir_paths

    def get_manifest(self, manifest):
        LOGGER.info("Reading manifest file for signature update.")
        if not os.path.exists(manifest):
            mani_list = list()
        else:
            with open(manifest, "rb") as pcl_in:
                mani_list = pickle.load(pcl_in)
        return mani_list

    def get_last_index(self, dir_paths):
        LOGGER.info("Getting last index number and content.")
        manifests = list(dir_paths["manifests"].glob("wort-sra-kmer-db*.pcl"))
        print(manifests)
        if not manifests:
            # There is no manifest. We start it at 0 or the minimum value specified in the settings
            last_num = max(settings.INDEX_MIN_ITERATOR, 0)
            last_sig_files = []
            return last_sig_files, last_num

        last_num = max([int(f.name.split("db")[1].split(".pcl")[0]) for f in manifests])
        last_num = max(settings.INDEX_MIN_ITERATOR, last_num)
        last_sigs = os.path.join(
            dir_paths["manifests"], f"wort-sra-kmer-db{last_num}.pcl"
        )
        with open(last_sigs, "rb") as pcl_in:
            last_sig_IDs = pickle.load(pcl_in)
        last_sig_files = [
            os.path.join(dir_paths["signatures"], f"{ID}.sig.gz") for ID in last_sig_IDs
        ]
        return last_sig_files, last_num

    def check_updates(self, dir_paths):
        return glob.glob(os.path.join(dir_paths["updates"], "*.sig.gz"))

    def create_list(self, new_files, sig_list):
        with open(sig_list, "w") as sl:
            sl.writelines(f"{fp}\n" for fp in new_files)

    def update_index(self, dir_paths, sig_list, database, k, last_num):
        database_lower = database.lower()
        idx = os.path.join(
            dir_paths["index"], f"wort-{database_lower}-{k}-db{last_num}.rocksdb"
        )
        LOGGER.info(f"Creating index {idx}.")
        LOGGER.info(f"Signature list {sig_list}.")
        if os.path.isdir(idx) and idx[-8:] == ".rocksdb":
            shutil.rmtree(idx)
        cpus = min(8, int(mp.cpu_count() * 0.8))
        cmd = [
            "sourmash",
            "scripts",
            "index",
            "--ksize",
            f"{k}",
            sig_list,
            "--moltype",
            "DNA",
            "--scaled",
            "1000",
            "--cores",
            f"{cpus}",
            "--output",
            idx,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        LOGGER.debug(
            f"sourmash branchwater index building output:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return result.returncode  # returncode: 0 = success, anything else = fail

    def move_files(self, file_list, dir_paths, target_dir):
        for file in file_list:
            base_name = os.path.basename(file)
            name, ext = os.path.splitext(base_name)
            if target_dir == "failed":
                now = datetime.now()
                now.strftime(".%Y%m%d-%H%M%S")
            else:
                pass
            destination = os.path.join(dir_paths[target_dir], base_name)
            shutil.move(file, destination)

    def update_manifests(self, new_files, mani_list, manifest, dir_paths, last_num):
        new_files = [os.path.basename(file).split(".sig.gz")[0] for file in new_files]
        last_sigs = os.path.join(
            dir_paths["manifests"], f"wort-sra-kmer-db{last_num}.pcl"
        )
        with open(last_sigs, "wb") as pcl_out:
            pickle.dump(new_files, pcl_out, protocol=4)
        sig_files = list(set(mani_list) | set(new_files))
        with open(manifest, "wb") as pcl_out:
            pickle.dump(sig_files, pcl_out, protocol=4)

    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)
