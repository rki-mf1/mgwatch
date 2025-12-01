import asyncio
import glob
import os
import pickle
import shutil
import ssl
import subprocess
from datetime import datetime
from datetime import timedelta

import aiofiles
import aiohttp
import httpx
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
            start_date = (
                today
                if settings.START_DATE == "auto"
                else datetime.fromisoformat(settings.START_DATE)
            )
            end_date = (
                today
                if settings.START_DATE == "auto"
                else datetime.fromisoformat(settings.END_DATE)
            )
            metagenomes_dir = settings.DATA_DIR / database / "metagenomes"
            manifest = metagenomes_dir / "manifest.pcl"
            man_succ = metagenomes_dir / "update_successful.pcl"
            man_fail = metagenomes_dir / "update_failed.pcl"
            dir_paths = self.handle_dirs(
                database, ["updates", "index", "signatures", "failed", "manifests"]
            )
            mani_list = set(self.get_manifest(manifest))
            if kwargs["ids"]:
                LOGGER.info(
                    "Only downloading signatures for specific IDs, as requested ..."
                )
                missing_IDs = set(kwargs["ids"]) - mani_list
                LOGGER.info(f"Number of missing IDs: {len(missing_IDs)}")
            else:
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

            # Only try to download accessions that are known to be available from wort
            wra_ids_in_wort = self.get_wort_accessions()
            missing_IDs = missing_IDs & wra_ids_in_wort

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
            LOGGER.error(f"Error downloading signatures to '{settings.DATA_DIR}': {e}")

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

    def get_wort_accessions(self):
        wort_accessions_endpoint = (
            "https://api.branchwater-dev.sourmash.bio/metadata/accessions"
        )
        r = httpx.get(wort_accessions_endpoint)
        accessions = set(r.raise_for_status().text.split())
        return accessions

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
        LOGGER.info(f"Requesting download of {len(SRA_IDs)} signatures.")
        IDs_succ = self.load_pickle(man_succ) if man_succ.exists() else set()
        IDs_fail = self.load_pickle(man_fail) if man_fail.exists() else set()
        SRA_IDs = SRA_IDs - IDs_succ
        if not retry_failed:
            SRA_IDs = list(SRA_IDs - IDs_fail)
        if settings.MAX_DOWNLOADS and settings.MAX_DOWNLOADS < len(SRA_IDs):
            SRA_IDs = SRA_IDs[: settings.MAX_DOWNLOADS]
        LOGGER.info(
            f"Initiating download of {len(SRA_IDs)} signatures (already downloaded IDs and failed removed)."
        )
        # Where the downloaded files will be placed
        target_dir = dir_paths["updates"]
        signature_endpoint = "https://wort.sourmash.bio/v1/view/sra"
        urls = [f"{signature_endpoint}/{id}" for id in SRA_IDs]
        LOGGER.info(f"Async download of {len(urls)} starting... first url {urls[0]}")
        retval = asyncio.run(self.fetch_all(urls, target_dir))
        LOGGER.info(f"Return values: {retval}")
        # TODO: Update success and failure pickle files before finishing

    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)

    def load_pickle(self, file):
        with open(file, "rb") as inpcl:
            ID_succ = pickle.load(inpcl)
        return ID_succ

    async def fetch(self, session, url, target_dir):
        # We need the SRA identifier to name our output file. This is a bit hacky.
        id = url.split("/")[-1]
        async with session.get(url, ssl=ssl.SSLContext()) as response:
            # Write to a temporary file and only move it to the final location
            # when the transfer is completed
            async with aiofiles.tempfile.NamedTemporaryFile("wb", delete=False) as f:
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    await f.write(chunk)
                await f.flush()
                LOGGER.info(
                    f"Download of {url} complete. Moving {f.name} to {target_dir}/{id}.sig"
                )
                return await asyncio.to_thread(
                    shutil.move, f.name, f"{target_dir}/{id}.sig"
                )

    async def fetch_all(self, urls, target_dir):
        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *[self.fetch(session, url, target_dir) for url in urls],
                return_exceptions=True,
            )
            return results
