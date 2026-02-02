import asyncio
import glob
import os
import pickle
import shutil
import ssl
import subprocess
import time
from datetime import datetime
from datetime import timedelta

import aiofiles
import aiohttp
import polars as pl
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
            manifest = metagenomes_dir / "manifest.pickle"
            man_succ = metagenomes_dir / "download_successful.pickle"
            man_fail = metagenomes_dir / "download_failed.pickle"
            dir_paths = self.handle_dirs(
                database,
                ["updates", "index", "signatures", "indexing-failed", "manifests"],
            )
            mani_list = set(self.get_manifest(manifest))
            if kwargs["ids"]:
                LOGGER.info(
                    "Only downloading signatures for specific IDs, as requested."
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
                    f"SRA accessions we want from the SRA database: {len(mongo_IDs)}"
                )
            LOGGER.info(
                f"SRA signatures we already have downloaded and are in the branchwater index: {len(mani_list)}"
            )
            LOGGER.info(f"SRA signatures we still need to download: {len(missing_IDs)}")

            # Only try to download accessions that are known to be available from wort
            sra_ids_in_wort = self.get_wort_accessions()
            LOGGER.info(f"SRA signatures in wort: {len(sra_ids_in_wort)}")
            missing_IDs = missing_IDs & sra_ids_in_wort
            LOGGER.info(
                f"SRA signatures we want, that are also in wort: {len(missing_IDs)}"
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
        wort_manifest_url = "https://s3.bi.denbi.de/wort-sra/SOURMASH-MANIFEST.parquet"
        accessions = (
            pl.scan_parquet(wort_manifest_url)
            .select(pl.col("name").str.extract(r"([\w.]+)", 1).alias("accession"))
            .collect()
            .get_column("accession")
            .unique()
            .to_list()
        )
        return set(accessions)

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
            with open(manifest, "rb") as pickle_in:
                mani_list = pickle.load(pickle_in)
        LOGGER.info(f"There are currently {len(mani_list)} IDs in the index manifest.")
        return mani_list

    def get_last_index(self, dir_paths):
        LOGGER.info("Getting last index number and content.")
        last_num = max(
            [
                int(os.path.basename(f).split("db")[1].split(".pickle")[0])
                for f in glob.glob(os.path.join(dir_paths["manifests"], "db*.pickle"))
            ]
        )
        last_sigs = os.path.join(dir_paths["manifests"], f"db{last_num}.pickle")
        with open(last_sigs, "rb") as pickle_in:
            sig_list = pickle.load(pickle_in)
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
            f"There are currently {len(mongo_IDs)} SRA accessions in the mongoDB between {start_date} and {end_date}."
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
        IDs_succ = set(self.load_pickle(man_succ)) if man_succ.exists() else set()
        IDs_fail = set(self.load_pickle(man_fail)) if man_fail.exists() else set()
        LOGGER.info(
            f"SRA accessions that we failed to download in the past: {len(IDs_fail)}"
        )
        LOGGER.info(f"SRA accessions that we successfully downloaded: {len(IDs_succ)}")
        SRA_IDs = SRA_IDs - IDs_succ
        num_requested_ids_without_max = len(SRA_IDs)
        if not retry_failed:
            SRA_IDs = list(SRA_IDs - IDs_fail)
        if settings.MAX_DOWNLOADS and settings.MAX_DOWNLOADS < len(SRA_IDs):
            LOGGER.info(
                f"Subsetting the number of signatures we are going to download to {settings.MAX_DOWNLOADS}"
            )
            SRA_IDs = SRA_IDs[: settings.MAX_DOWNLOADS]
        LOGGER.info(
            f"Initiating download of {len(SRA_IDs)} signatures (already downloaded IDs and failed removed)."
        )
        # Where the downloaded files will be placed
        target_dir = dir_paths["updates"]
        signature_endpoint = "https://wort.sourmash.bio/v1/view/sra"
        urls = [f"{signature_endpoint}/{id}" for id in SRA_IDs]
        LOGGER.info(f"Async download of {len(urls)} starting. First url {urls[0]}")
        start_time = time.time()
        asyncio.run(
            self.fetch_all(urls, target_dir, IDs_succ, IDs_fail, man_succ, man_fail)
        )
        end_time = time.time()
        elapsed_time = end_time - start_time
        time_per_signature = elapsed_time / len(urls)
        LOGGER.info(
            f"Download finished. Total runtime was {elapsed_time:.2f} seconds. {time_per_signature:.2f} per signature. Downloading the full requested set of SRA IDs ({num_requested_ids_without_max}) would have taken {time_per_signature * num_requested_ids_without_max / 60:.2f} minutes, or {time_per_signature * num_requested_ids_without_max / (60 * 60 * 24):.2f} days."
        )

    def save_pickle(self, data, file):
        with open(file, "wb") as out_pickle:
            pickle.dump(data, out_pickle, protocol=4)

    def load_pickle(self, file):
        with open(file, "rb") as in_pickle:
            ID_succ = pickle.load(in_pickle)
        return ID_succ

    async def fetch(
        self,
        session,
        url,
        target_dir,
        IDs_succ,
        IDs_fail,
        man_succ,
        man_fail,
        lock,
    ):
        # We need the SRA identifier to name our output file. This is a bit hacky.
        id = url.split("/")[-1]
        try:
            async with session.get(url, ssl=ssl.SSLContext()) as response:
                status = response.status
                if status < 200 or status >= 300:
                    LOGGER.error(f"Download failed for {url} with status {status}")
                    async with lock:
                        IDs_fail.add(id)
                        await asyncio.to_thread(self.save_pickle, IDs_fail, man_fail)
                    return {
                        "id": id,
                        "url": url,
                        "status": status,
                        "error": "non-success status",
                    }

                # Write to a temporary file and only move it to the final location
                # when the transfer is completed
                async with aiofiles.tempfile.NamedTemporaryFile(
                    "wb", delete=False
                ) as f:
                    async for chunk in response.content.iter_chunked(1024 * 1024):
                        await f.write(chunk)
                    await f.flush()
                    dest = f"{target_dir}/{id}.sig"
                    LOGGER.info(
                        f"Download of {url} complete. Moving {f.name} to {dest}"
                    )
                    await asyncio.to_thread(shutil.move, f.name, dest)
                    async with lock:
                        IDs_succ.add(id)
                        await asyncio.to_thread(self.save_pickle, IDs_succ, man_succ)
                    return {"id": id, "url": url, "status": status, "path": dest}
        except Exception as exc:
            LOGGER.error(f"Download exception for {url}: {exc}")
            async with lock:
                IDs_fail.add(id)
                await asyncio.to_thread(self.save_pickle, IDs_fail, man_fail)
            return {"id": id, "url": url, "status": None, "error": str(exc)}

    async def fetch_all(self, urls, target_dir, IDs_succ, IDs_fail, man_succ, man_fail):
        lock = asyncio.Lock()
        async with aiohttp.ClientSession(trust_env=True) as session:
            tasks = [
                self.fetch(
                    session,
                    url,
                    target_dir,
                    IDs_succ,
                    IDs_fail,
                    man_succ,
                    man_fail,
                    lock,
                )
                for url in urls
            ]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            # Return both successes and any failed downloads/non-success statuses
            return results
