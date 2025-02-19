import glob
import gzip
import os
import pickle
import subprocess
import time
from datetime import datetime
from datetime import timedelta

import pymongo as pm
from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER

################################################################################
# Download signature files and add them to the search index
################################################################################


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--ids",
            nargs="+",
            help="Only download signatures for these specific SRA IDs",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Ignore the list of IDs that have failed to download in the past",
        )

    def handle(self, *args, **kwargs):
        try:
            # URL for a sample that we know is in wort. This is for the example
            # they provide on the website.
            test_url = "https://wort.sourmash.bio/v1/view/sra/SRR15461028"
            if not self.check_wort_up(test_url):
                return f"The wort server is not accessible (failed to download {test_url}). Aborting."

            # Signatures are small, they shouldn't take long to download. At
            # the same time we have several IDs where wort seems to just hang
            # for a long time and never send anything. Therefore we set a
            # timeout on each download.
            timeout_seconds = 30
            database = "SRA"
            today = datetime.today() - timedelta(days=2)
            today = today.strftime("%Y-%m-%d")
            start_date = today if settings.START_DATE == "auto" else settings.START_DATE
            end_date = today if settings.START_DATE == "auto" else settings.END_DATE
            metagenomes_dir = settings.DATA_DIR / database / "metagenomes"
            manifest = metagenomes_dir / "manifest.pcl"
            man_succ = metagenomes_dir / "update_successful.pcl"
            man_fail = metagenomes_dir / "update_failed.pcl"
            dir_paths = self.handle_dirs(
                database, ["updates", "index", "signatures", "failed", "manifests"]
            )
            if kwargs["ids"]:
                LOGGER.info(
                    "Only downloading signatures for specific IDs, as requested ..."
                )
                missing_IDs = set(kwargs["ids"])
                LOGGER.info(f"Number of missing IDs: {len(missing_IDs)}")
            else:
                mani_list = self.get_manifest(manifest)
                if not mani_list and not settings.INDEX_FROM_SCRATCH:
                    LOGGER.error(
                        "There is no index available and creating one from scratch is disabled."
                    )
                    raise Exception(
                        "There is no index available and creating one from scratch is disabled."
                    )
                mongo_IDs = self.get_mongoIDs(start_date, end_date)
                missing_IDs = set(mongo_IDs) - set(mani_list)
                LOGGER.info(
                    f"There are currently {len(missing_IDs)} IDs that are not in the index manifest."
                )

            retry_failed = kwargs["retry_failed"] or not settings.WORT_SKIP_FAILED
            self.download_from_wort(
                dir_paths,
                missing_IDs,
                man_succ,
                man_fail,
                timeout_seconds,
                retry_failed,
            )
            LOGGER.info("Creating downloads finished.")
        except Exception as e:
            LOGGER.error(f"Error downloading signatures '{settings.DATA_DIR}': {e}")

    def check_wort_up(self, url):
        """Try to download a known-good SRA siganture, to check if the wort
        service is up
        """
        cmd = ["curl", "-sLf", "-r", "0-10", url, "-o", "/dev/null"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
            else:
                return False
        except Exception:
            return False

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

    def get_manifest(self, manifest):
        LOGGER.info("Reading manifest file for signature update.")
        if not os.path.exists(manifest):
            mani_list = list()
        else:
            with open(manifest, "rb") as pcl_in:
                mani_list = pickle.load(pcl_in)
        LOGGER.info(f"There are currently {len(mani_list)} IDs in the index manifest.")
        return mani_list

    def get_last_index(self, dir_paths):
        LOGGER.info("Getting last index number and content.")
        last_num = max(
            [
                int(os.path.basename(f).split("db")[1].split(".pcl")[0])
                for f in glob.glob(
                    os.path.join(dir_paths["manifests"], "wort-sra-kmer-db*.pcl")
                )
            ]
        )
        last_sigs = os.path.join(
            dir_paths["manifests"], f"wort-sra-kmer-db{last_num}.pcl"
        )
        with open(last_sigs, "rb") as pcl_in:
            sig_list = pickle.load(pcl_in)
        return sig_list, last_num

    def get_mongoIDs(self, start_date, end_date):
        # LOGGER.info(f"Getting current SRA IDs from MongoDB.")
        mongo = pm.MongoClient(settings.MONGO_URI)
        db = mongo["sradb"]
        collection = db["sradb_list"]
        # oldest date: 2007-06-05 newest date: 2024-11-13
        # start_date = "2023-09-26" mongo IDs: 104099 shared IDs: 1795
        # start_date = "2023-09-27" mongo IDs: 95092  shared IDs: 54
        # start_date = "2023-09-28" mongo IDs: 67608  shared IDs: 0
        query = {"releasedate": {"$gte": start_date, "$lte": end_date}}
        if settings.LIB_SOURCE:
            query = query | {"librarysource": {"$in": settings.LIB_SOURCE}}
        ids = collection.find(query, {"_id": 1})
        mongo_IDs = [doc["_id"] for doc in ids]
        mongo.close()
        LOGGER.info(
            f"There are currently {len(mongo_IDs)} IDs in the mongoDB between {start_date} and {end_date}."
        )
        return mongo_IDs

    def download_from_wort(
        self,
        dir_paths,
        SRA_IDs,
        man_succ,
        man_fail,
        timeout_seconds,
        retry_failed=False,
    ):
        IDs_succ = self.load_pickle(man_succ) if os.path.exists(man_succ) else set()
        IDs_fail = self.load_pickle(man_fail) if os.path.exists(man_fail) else set()
        SRA_IDs = SRA_IDs - IDs_succ
        if not retry_failed:
            SRA_IDs = list(SRA_IDs - IDs_fail)
        if settings.MAX_DOWNLOADS and settings.MAX_DOWNLOADS < len(SRA_IDs):
            SRA_IDs = SRA_IDs[: settings.MAX_DOWNLOADS]
        slen = len(SRA_IDs)
        for i, SRA_ID in enumerate(SRA_IDs, start=1):
            LOGGER.info(f"... {i} of {slen} ID {SRA_ID} ...")
            attempts, success = 0, False
            while not success:
                attempts += 1
                success = self.call_curl_download(dir_paths, SRA_ID, timeout_seconds)
                if attempts < settings.WORT_ATTEMPTS and not success:
                    time.sleep(1)
                else:
                    break
            if success:
                IDs_succ.add(SRA_ID)
                self.save_pickle(IDs_succ, man_succ)
            else:
                IDs_fail.add(SRA_ID)
                self.save_pickle(IDs_fail, man_fail)
        LOGGER.info(f"Successful downloads: {len(IDs_succ)}")
        LOGGER.info(f"Failed downloads: {len(IDs_fail)}")

    def call_curl_download(self, dir_paths, SRA_ID, timeout_seconds=3600):
        url = f"https://wort.sourmash.bio/v1/view/sra/{SRA_ID}"
        output_file = os.path.join(dir_paths["updates"], f"{SRA_ID}.sig.gz")
        cmd = [
            "curl",
            "--max-time",
            str(timeout_seconds),
            "-JLf",
            url,
            "-o",
            output_file,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # wort sometime returns a .sig.gz file that is a gzipped empty
                # file. Check for this specifically.
                with gzip.open(output_file, "r") as f:
                    is_empty = len(f.read(1)) == 0
                if is_empty:
                    os.remove(output_file)
                    print(f"Downloaded wort file is empty for {SRA_ID}")
                    return False
                return True
            else:
                print(f"Failed to download {SRA_ID}: Exit code {result.returncode}")
                return False
        except Exception as e:
            print(f"Error occurred while downloading {SRA_ID}: {e}")
            return False

    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)

    def load_pickle(self, file):
        with open(file, "rb") as inpcl:
            ID_succ = pickle.load(inpcl)
        return ID_succ
