# mgw_api/management/commands/create_manifests.py

import os
import pickle
import re

from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER

################################################################################
## django command class
################################################################################


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        try:
            database = "SRA"
            manifest = os.path.join(
                settings.DATA_DIR, database, "metagenomes", "manifest.pcl"
            )
            dir_paths = self.handle_dirs(
                database,
                ["updates", "index", "signatures", "failed", "lists", "manifests"],
            )
            self.create_initial_manifests(manifest, dir_paths)
            LOGGER.info("Creating manifests finished.")
        except Exception as e:
            LOGGER.error(f"Error creating manifests '{settings.DATA_DIR}': {e}")

    def handle_dirs(self, database, dir_names):
        dir_paths = {
            n: os.path.join(settings.DATA_DIR, database, "metagenomes", n)
            for n in dir_names
        }
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o700)
        return dir_paths

    def create_initial_manifests(self, manifest, dir_paths):
        manifest_IDs, index_paths, index_lists = (
            list(),
            os.listdir(dir_paths["index"]),
            os.listdir(dir_paths["lists"]),
        )
        if os.path.exists(manifest):
            LOGGER.info("Manifest found, reading ...")
            with open(manifest, "rb") as pcl_in:
                manifest_IDs = pickle.load(pcl_in)
            LOGGER.info(f"Manifest has {len(manifest_IDs)} IDs ...")
        if not manifest_IDs and not index_paths:
            LOGGER.info("No index and no manifest, creating empty manifest ...")
            self.save_pickle([], manifest)
        if not manifest_IDs and index_paths:
            LOGGER.info("Index found, but no manifest, creating manifest ...")
            if len(index_paths) != len(index_lists):
                raise Exception(
                    "The number of indices and index lists are not the same."
                )
            index_lists = sorted(index_lists, key=lambda x: self.extract_number(x))
            manifest_dict = dict()
            for index_list in index_lists:
                with open(os.path.join(dir_paths["lists"], index_list), "r") as list_in:
                    i = self.extract_number(index_list)
                    ID_list = [
                        os.path.splitext(os.path.split(line.strip())[1])[0]
                        for line in list_in
                    ]
                    manifest_dict[i] = ID_list
            LOGGER.info(
                f"Extracted SRA IDs from index list files, found {len(manifest_dict)} list files beloning to indices."
            )
            SRA_IDs = [v for val in manifest_dict.values() for v in val]
            LOGGER.info(f"Saving manifest with {len(SRA_IDs)} SRA IDs.")
            self.save_pickle(SRA_IDs, manifest)
            for i, IDs in manifest_dict.items():
                self.save_pickle(
                    IDs,
                    os.path.join(dir_paths["manifests"], f"wort-sra-kmer-db{i}.pcl"),
                )
            LOGGER.info(
                f"Finished, creating new starting manifest {len(manifest_dict)} for further updates."
            )
            self.save_pickle(
                [],
                os.path.join(
                    dir_paths["manifests"], f"wort-sra-kmer-db{len(manifest_dict)}.pcl"
                ),
            )

    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)

    def extract_number(self, s):
        return int(re.search(r"\d+", s).group())

    def get_manifest(self, manifest):
        with open(manifest, "rb") as pcl_in:
            mani_list = pickle.load(pcl_in)
        return mani_list
