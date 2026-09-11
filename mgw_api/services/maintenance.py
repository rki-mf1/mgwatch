import asyncio
import glob
import inspect
import os
import pickle
import shutil
import ssl
import tempfile
from datetime import datetime
from datetime import timedelta
from itertools import batched
from pathlib import Path
from time import monotonic

import aiofiles
import aiohttp
import polars as pl
import pymongo as pm
from aiobotocore.session import get_session
from botocore import UNSIGNED
from botocore.config import Config
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from mgw.settings import LOGGER
from mgw.settings import MGW_URL
from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import batch_manifest
from mgw_api.database_config import database_root
from mgw_api.database_config import failed_downloads_path
from mgw_api.database_config import get_database_config
from mgw_api.database_config import index_path
from mgw_api.database_config import metadata_cache_dir
from mgw_api.database_config import metadata_init_flag
from mgw_api.database_config import profile_manifest
from mgw_api.database_config import profile_root
from mgw_api.database_config import read_accession_parquet
from mgw_api.database_config import signature_dirs
from mgw_api.database_config import write_accession_parquet
from mgw_api.functions import get_results_with_metadata
from mgw_api.models import FilterSetting
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.services.filters import apply_filter_spec
from mgw_api.services.stats import try_record_download_index_runtime
from mgw_api.services.stats import try_record_index_stats
from mgw_api.services.stats import try_record_index_update_runtime
from mgw_api.services.stats import try_record_metadata_stats
from mgw_api.services.stats import try_record_metadata_update_runtime

from .processes import run_command
from .searches import run_search

SRA_METADATA_BUCKET = "sra-pub-metadata-us-east-1"
SRA_METADATA_PREFIX = "sra/metadata/"
SRA_METADATA_MAX_DOWNLOADS = 8


def run_metadata(
    *,
    no_download=False,
    no_process=False,
    drop_first=False,
    indexed_only=False,
    database=DEFAULT_DATABASE_ID,
):
    started_at = monotonic()
    database_config = get_database_config(database)
    LOGGER.info("Starting metadata update")
    metadata_dir = metadata_cache_dir()
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_stat = None

    if drop_first:
        drop_mongo_collection(database_config.mongodb_collection)
        drop_mongo_collection(f"{database_config.mongodb_collection}_temp")

    if not no_download:
        asyncio.run(
            sync_public_s3_prefix(
                SRA_METADATA_BUCKET,
                SRA_METADATA_PREFIX,
                metadata_dir,
            )
        )

    if not no_process:
        import_parquet(
            metadata_dir,
            indexed_only=indexed_only,
            database=database_config.id,
        )
        metadata_stat = try_record_metadata_stats(database=database_config.id)

    init_flag = metadata_init_flag()
    init_flag.parent.mkdir(parents=True, exist_ok=True)
    init_flag.touch()
    if not no_process:
        try_record_metadata_update_runtime(
            duration_seconds=monotonic() - started_at,
            metadata_sample_count=metadata_stat.value if metadata_stat else None,
        )
    return {"metadata_dir": str(metadata_dir)}


async def sync_public_s3_prefix(
    bucket,
    prefix,
    destination,
    *,
    max_simultaneous=SRA_METADATA_MAX_DOWNLOADS,
):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    session = get_session()
    async with session.create_client(
        "s3",
        config=Config(signature_version=UNSIGNED),
    ) as s3:
        remote_objects = await list_public_s3_objects(s3, bucket, prefix)
        pending_downloads = []
        for key, size in remote_objects.items():
            relative_path = Path(key).relative_to(prefix)
            local_path = destination / relative_path
            if local_path.exists() and local_path.stat().st_size == size:
                continue
            pending_downloads.append((key, local_path))

        semaphore = asyncio.Semaphore(max_simultaneous)

        async def download_with_limit(key, local_path):
            async with semaphore:
                await download_public_s3_object(s3, bucket, key, local_path)

        await asyncio.gather(
            *(
                download_with_limit(key, local_path)
                for key, local_path in pending_downloads
            )
        )

    remote_relative_paths = {Path(key).relative_to(prefix) for key in remote_objects}
    for local_file in destination.rglob("*"):
        relative_file = local_file.relative_to(destination)
        if local_file.is_file() and relative_file not in remote_relative_paths:
            local_file.unlink()


async def list_public_s3_objects(s3, bucket, prefix):
    objects = {}
    paginator = s3.get_paginator("list_objects_v2")
    async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for entry in page.get("Contents", []):
            key = entry["Key"]
            if key and not key.endswith("/"):
                objects[key] = entry["Size"]
    return objects


async def download_public_s3_object(s3, bucket, key, local_path):
    local_path.parent.mkdir(parents=True, exist_ok=True)
    response = await s3.get_object(Bucket=bucket, Key=key)
    async with response["Body"] as stream:
        async with aiofiles.open(local_path, "wb") as handle:
            while True:
                chunk = await stream.read(1024 * 1024)
                if not chunk:
                    break
                await handle.write(chunk)


def get_filter_data():
    column_list = [
        "acc",
        "assay_type",
        "bioproject",
        "biosample",
        "collection_date_sam",
        "geo_loc_name_country_calc",
        "geo_loc_name",
        "organism",
        "releasedate",
        "librarysource",
        "sample_name",
        "sample_title",
        "experiment_title",
        "study_title",
        "description",
        "host",
        "isolation_source",
    ]
    jattr_dtypes = pl.Struct([pl.Field("lat_lon", dtype=pl.String)])
    allowed_librarysources = ["METAGENOMIC", "GENOMIC", "METATRANSCRIPTOMIC"]
    return column_list, jattr_dtypes, allowed_librarysources


def drop_mongo_collection(collection):
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    if collection in db.list_collection_names():
        db[collection].drop()
    mongo.close()


def import_parquet(parquet_dir, indexed_only=False, database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    temp_collection = f"{database_config.mongodb_collection}_temp"
    drop_mongo_collection(temp_collection)
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    db.create_collection(temp_collection)
    mongo.close()

    column_list, jattr_dtypes, allowed_librarysources = get_filter_data()
    indexed_ids = None
    if indexed_only:
        indexed_ids = set()
        for profile in database_config.enabled_profiles:
            indexed_ids.update(
                read_accession_parquet(profile_manifest(database_config.id, profile))
            )

    for parquet_file in parquet_dir.glob("*"):
        df = pl.scan_parquet(parquet_file)
        available_columns = set(df.collect_schema().names())
        selected_columns = [
            column for column in column_list if column in available_columns
        ]
        sra_lf = df
        if "librarysource" in available_columns:
            sra_lf = sra_lf.filter(
                pl.col("librarysource").is_in(allowed_librarysources)
            )
        include_filters = database_config.metadata_filter.get("include", {})
        librarysource = include_filters.get("librarysource")
        if librarysource and "librarysource" in available_columns:
            sra_lf = sra_lf.filter(pl.col("librarysource") == librarysource)
        if "jattr" in available_columns:
            sra_lf = sra_lf.select(selected_columns + ["jattr"])
        else:
            sra_lf = sra_lf.select(selected_columns)
        if indexed_ids:
            sra_lf = sra_lf.filter(pl.col("acc").is_in(indexed_ids))
        sra_df = sra_lf.collect().with_columns(pl.col(pl.Date).cast(pl.Datetime))
        if "jattr" in sra_df.columns:
            sra_df = (
                sra_df.with_columns(
                    pl.col("jattr").str.json_decode(jattr_dtypes).alias("jattr_decoded")
                )
                .drop("jattr")
                .unnest("jattr_decoded")
            )
        alias_expressions = [pl.col("acc").alias("_id")]
        if "acc" in sra_df.columns:
            alias_expressions.append(pl.col("acc").alias("sra_accession"))
        if "biosample" in sra_df.columns:
            alias_expressions.append(pl.col("biosample").alias("sra_biosample"))
        if "bioproject" in sra_df.columns:
            alias_expressions.append(pl.col("bioproject").alias("sra_bioproject"))
        sra_df = sra_df.with_columns(alias_expressions)
        excluded_terms = database_config.metadata_filter.get("exclude", {}).get(
            "descriptive_fields_contain",
            [],
        )
        if excluded_terms and sra_df.height > 0:
            text_columns = [
                column
                for column in [
                    "assay_type",
                    "organism",
                    "librarysource",
                    "sample_name",
                    "sample_title",
                    "experiment_title",
                    "study_title",
                    "description",
                    "host",
                    "isolation_source",
                ]
                if column in sra_df.columns
            ]
            if text_columns:
                for term in excluded_terms:
                    term_expr = pl.any_horizontal(
                        [
                            pl.col(column)
                            .cast(pl.String)
                            .str.to_lowercase()
                            .str.contains(str(term).lower())
                            .fill_null(False)
                            for column in text_columns
                        ]
                    )
                    sra_df = sra_df.filter(~term_expr)
        if sra_df.height > 0:
            mongo = pm.MongoClient(settings.MONGO_URI)
            db = mongo["sradb"]
            db[temp_collection].insert_many(sra_df.to_dicts())
            mongo.close()

    drop_mongo_collection(database_config.mongodb_collection)
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    db[temp_collection].rename(database_config.mongodb_collection)
    mongo.close()


def run_downloads(
    *,
    max_downloads=None,
    max_simultaneous=None,
    timeout=None,
    ids=None,
    retry_failed=False,
    database=DEFAULT_DATABASE_ID,
):
    database_config = get_database_config(database)
    if max_simultaneous is None:
        max_simultaneous = database_config.download.get("max_simultaneous", 100)
    if timeout is None:
        timeout = database_config.download.get("timeout_seconds", 60)
    test_url = f"{database_config.wort_signature_endpoint}/SRR15461028"
    run_command(["curl", "-sLf", "-r", "0-10", test_url, "-o", "/dev/null"])
    dir_paths, man_fail, sra_ids = prepare_download_targets(
        ids=ids,
        database=database_config.id,
    )
    selected_ids = select_download_ids(
        sra_ids,
        dir_paths,
        man_fail,
        retry_failed=retry_failed
        or database_config.download.get("retry_failed", False),
        max_downloads=max_downloads,
        database=database_config.id,
    )
    results = asyncio.run(
        download_from_wort(
            dir_paths,
            selected_ids,
            man_fail,
            timeout,
            endpoint=database_config.wort_signature_endpoint,
            database=database_config.id,
            retry_failed=True,
            max_downloads=len(selected_ids),
            max_simultaneous=max_simultaneous,
        )
    )
    downloaded = sum(
        1 for result in results if isinstance(result, dict) and result.get("path")
    )
    return {"downloaded": downloaded}


def prepare_download_targets(ids=None, database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    dir_paths = handle_dirs(database_config.id)
    man_fail = failed_downloads_path(database_config.id)
    indexed_ids = get_all_profile_indexed_accessions(database_config.id)
    if not ids and not indexed_ids and not settings.INDEX_FROM_SCRATCH:
        raise RuntimeError(
            "profile manifest is missing and INDEX_FROM_SCRATCH is disabled; "
            "create indexes first or provide explicit IDs"
        )
    if ids:
        wanted_ids = set(ids) - indexed_ids
    else:
        start_date, end_date = get_download_date_range(database_config)
        mongo_ids = get_mongo_ids(start_date, end_date, database_config.id)
        wanted_ids = set(mongo_ids) - indexed_ids
    sra_ids_in_wort = get_wort_accessions(database_config.id)
    return dir_paths, man_fail, sorted(wanted_ids & sra_ids_in_wort)


def get_download_date_range(database_config=None):
    database_config = database_config or get_database_config(DEFAULT_DATABASE_ID)
    today = datetime.today() - timedelta(
        days=database_config.download.get("date_lag_days", 2)
    )
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
    return start_date, end_date


def select_download_ids(
    sra_ids,
    dir_paths,
    man_fail,
    *,
    retry_failed=False,
    max_downloads=None,
    database=DEFAULT_DATABASE_ID,
):
    selected_ids = set(sra_ids) - get_update_accessions(dir_paths["updates"])
    ids_fail = load_failed_downloads(man_fail)
    if not retry_failed:
        selected_ids -= ids_fail
    selected_ids = sorted(selected_ids)
    if max_downloads is None:
        max_downloads = get_configured_max_downloads(get_database_config(database))
    if max_downloads and max_downloads < len(selected_ids):
        selected_ids = selected_ids[:max_downloads]
    return selected_ids


def get_configured_max_downloads(database_config):
    max_downloads = database_config.download.get(
        "max_downloads", settings.MAX_DOWNLOADS
    )
    return max_downloads or None


def handle_dirs(database=DEFAULT_DATABASE_ID):
    dirs = signature_dirs(database)
    dir_paths = {
        "updates": dirs["pending"],
        "pending": dirs["pending"],
        "signatures": dirs["indexed"],
        "indexed": dirs["indexed"],
        "indexing-failed": dirs["failed-indexing"],
        "failed-indexing": dirs["failed-indexing"],
    }
    dir_paths["tmp"] = database_root(database) / "tmp"
    for dir_path in dir_paths.values():
        dir_path.mkdir(parents=True, exist_ok=True)
        os.chmod(dir_path, 0o700)
    return dir_paths


def get_manifest(manifest):
    if not os.path.exists(manifest):
        return []
    with open(manifest, "rb") as handle:
        return pickle.load(handle)


def get_mongo_ids(start_date, end_date, database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    collection = db[database_config.mongodb_collection]
    query = {"releasedate": {"$gte": start_date, "$lte": end_date}}
    ids = [doc["_id"] for doc in collection.find(query, {"_id": 1})]
    mongo.close()
    return ids


def get_wort_accessions(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    accessions = (
        pl.scan_parquet(database_config.wort_manifest_url)
        .select(pl.col("name").str.extract(r"([\w.]+)", 1).alias("accession"))
        .collect()
        .get_column("accession")
        .unique()
        .to_list()
    )
    return set(accessions)


async def download_from_wort(
    dir_paths,
    sra_ids,
    man_fail,
    timeout_seconds,
    *,
    endpoint=None,
    database=DEFAULT_DATABASE_ID,
    retry_failed=False,
    max_downloads=None,
    max_simultaneous=100,
):
    database_config = get_database_config(database)
    endpoint = (endpoint or database_config.wort_signature_endpoint).rstrip("/")
    ids_fail = load_failed_downloads(man_fail)
    sra_ids = select_download_ids(
        sra_ids,
        dir_paths,
        man_fail,
        retry_failed=retry_failed,
        max_downloads=max_downloads,
        database=database_config.id,
    )
    target_dir = dir_paths["updates"]
    urls = [f"{endpoint}/{id_}" for id_ in sra_ids]
    if not urls:
        return []
    lock = asyncio.Lock()
    conn = aiohttp.TCPConnector(limit=max_simultaneous)
    timeout = aiohttp.ClientTimeout(
        sock_connect=timeout_seconds, sock_read=timeout_seconds
    )
    async with aiohttp.ClientSession(
        connector=conn, trust_env=True, timeout=timeout
    ) as session:
        tasks = [
            fetch_signature(session, url, target_dir, ids_fail, man_fail, lock)
            for url in urls
        ]
        return await asyncio.gather(*tasks, return_exceptions=False)


async def fetch_signature(session, url, target_dir, ids_fail, man_fail, lock):
    accession = url.split("/")[-1]
    tmp_name = None
    try:
        async with session.get(url, ssl=ssl.SSLContext()) as response:
            status = response.status
            if status < 200 or status >= 300:
                async with lock:
                    ids_fail.add(accession)
                    await asyncio.to_thread(save_failed_downloads, man_fail, ids_fail)
                return {"id": accession, "status": status, "error": "non-success"}
            async with aiofiles.tempfile.NamedTemporaryFile(
                "wb",
                delete=False,
                dir=target_dir,
                prefix=f".{accession}.",
                suffix=".tmp",
            ) as handle:
                tmp_name = handle.name
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    await handle.write(chunk)
                await handle.flush()
                dest = target_dir / f"{accession}.sig"
                await asyncio.to_thread(os.replace, handle.name, dest)
                tmp_name = None
            return {"id": accession, "status": status, "path": str(dest)}
    except Exception:
        if tmp_name:
            await asyncio.to_thread(Path(tmp_name).unlink, missing_ok=True)
        LOGGER.exception("Download exception for %s", url)
        async with lock:
            ids_fail.add(accession)
            await asyncio.to_thread(save_failed_downloads, man_fail, ids_fail)
        return {"id": accession, "status": None}


def save_pickle(data, file):
    with open(file, "wb") as handle:
        pickle.dump(data, handle, protocol=4)


def load_pickle(file):
    with open(file, "rb") as handle:
        return pickle.load(handle)


def load_failed_downloads(path):
    path = Path(path)
    if not path.exists():
        return set()
    if path.suffix == ".pickle":
        return set(load_pickle(path))
    return set(read_accession_parquet(path))


def save_failed_downloads(path, accessions):
    path = Path(path)
    if path.suffix == ".pickle":
        save_pickle(set(accessions), path)
        return
    write_accession_parquet(path, accessions)


def get_any_profile_indexed_accessions(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    indexed = set()
    for profile in database_config.enabled_profiles:
        indexed.update(
            read_accession_parquet(profile_manifest(database_config.id, profile))
        )
    return indexed


def get_all_profile_indexed_accessions(database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    profile_accessions = [
        set(read_accession_parquet(profile_manifest(database_config.id, profile)))
        for profile in database_config.enabled_profiles
    ]
    if not profile_accessions:
        return set()
    return set.intersection(*profile_accessions)


def get_update_accessions(updates_dir):
    return {sig_path.stem for sig_path in Path(updates_dir).glob("*.sig")}


def run_index(*, index_max_signatures=None, database=DEFAULT_DATABASE_ID):
    database_config = get_database_config(database)
    tmp_dir = settings.DATA_DIR / "tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mgwatch-index-", dir=tmp_dir) as work_dir:
        result = run_index_batches(
            work_dir,
            database=database_config.id,
            index_max_signatures=index_max_signatures,
            max_batches=None,
            delete_indexed_sigs=not database_config.indexing.get(
                "retain_indexed_signatures",
                True,
            ),
        )
    return {"indexes_updated": result["indexes_updated"]}


def run_index_batches(
    work_dir,
    *,
    database=DEFAULT_DATABASE_ID,
    index_max_signatures=None,
    max_batches=None,
    delete_indexed_sigs=False,
):
    started_at = monotonic()
    database_config = get_database_config(database)
    profiles = database_config.enabled_profiles
    sig_list = Path(work_dir) / "sig-list.txt"
    dir_paths = handle_dirs(database_config.id)
    mani_list = set(get_any_profile_indexed_accessions(database_config.id))
    last_sig_files, last_num, has_existing_index = get_last_index(
        database_config.id,
        profiles[0],
        dir_paths,
    )
    max_signatures = index_max_signatures or database_config.indexing.get(
        "batch_size",
        settings.INDEX_MAX_SIGNATURES,
    )
    batch_specs = get_index_batch_specs(
        dir_paths,
        last_sig_files,
        last_num,
        has_existing_index,
        max_signatures,
    )
    if max_batches is not None:
        batch_specs = batch_specs[:max_batches]
    if not batch_specs:
        return {"indexes_updated": 0, "batches_processed": 0}
    update_sig_files = set(glob.glob(os.path.join(dir_paths["updates"], "*.sig")))
    indexing_ever_failed = False
    indexing_ever_succeeded = False
    samples_added = 0
    for index_number, new_files in batch_specs:
        indexing_succeeded, mani_list = process_index_batch(
            work_dir,
            dir_paths,
            sig_list,
            database_config.id,
            profiles,
            index_number,
            new_files,
            mani_list,
            max_signatures,
            delete_indexed_sigs,
        )
        indexing_ever_failed = indexing_ever_failed or not indexing_succeeded
        indexing_ever_succeeded = indexing_ever_succeeded or indexing_succeeded
        if indexing_succeeded:
            samples_added += sum(
                1 for sig_file in new_files if sig_file in update_sig_files
            )
    if indexing_ever_succeeded:
        index_stat = try_record_index_stats(database=database_config.id)
        try_record_index_update_runtime(
            duration_seconds=monotonic() - started_at,
            samples_added=samples_added,
            sketches_added=samples_added * len(profiles),
            database=database_config.id,
            total_index_sample_count=index_stat.value if index_stat else None,
        )
    return {
        "indexes_updated": 1,
        "batches_processed": len(batch_specs),
        "indexing_failed": indexing_ever_failed,
    }


def get_index_batch_specs(
    dir_paths, last_sig_files, last_num, has_existing_index, max_signatures
):
    new_sig_files = sorted(glob.glob(os.path.join(dir_paths["updates"], "*.sig")))
    if not new_sig_files:
        return []
    reuse_last_index = can_reuse_last_index(last_sig_files, has_existing_index)
    if reuse_last_index:
        sig_files = last_sig_files + new_sig_files
        start_index_number = last_num
    else:
        sig_files = new_sig_files
        start_index_number = last_num + 1
    return [
        (start_index_number + idx_offset, list(batch_files))
        for idx_offset, batch_files in enumerate(
            batched(sig_files, n=max_signatures), 0
        )
    ]


def process_index_batch(
    work_dir,
    dir_paths,
    sig_list,
    database,
    profiles,
    index_number,
    new_files,
    mani_list,
    max_signatures,
    delete_indexed_sigs,
):
    write_signature_list(new_files, sig_list)
    try:
        retvals = [
            update_index(work_dir, database, profile, sig_list, index_number)
            for profile in profiles
        ]
        indexing_succeeded = all(val == 0 for val in retvals)
    except Exception:
        LOGGER.exception("Index batch %s failed", index_number)
        indexing_succeeded = False
    delete_after_indexing = (
        indexing_succeeded and delete_indexed_sigs and len(new_files) == max_signatures
    )
    if delete_after_indexing:
        delete_files(new_files)
    else:
        target_dir = "signatures" if indexing_succeeded else "indexing-failed"
        move_files(new_files, dir_paths, target_dir)
    if indexing_succeeded:
        mani_list = update_manifests(
            new_files,
            mani_list,
            database,
            profiles,
            index_number,
        )
    return indexing_succeeded, mani_list


def run_download_index(
    *,
    max_downloads=None,
    max_simultaneous=None,
    timeout=None,
    ids=None,
    retry_failed=False,
    index_max_signatures=None,
    database=DEFAULT_DATABASE_ID,
):
    started_at = monotonic()
    database_config = get_database_config(database)
    if max_simultaneous is None:
        max_simultaneous = database_config.download.get("max_simultaneous", 100)
    if timeout is None:
        timeout = database_config.download.get("timeout_seconds", 60)
    test_url = f"{database_config.wort_signature_endpoint}/SRR15461028"
    run_command(["curl", "-sLf", "-r", "0-10", test_url, "-o", "/dev/null"])
    dir_paths, man_fail, remaining_ids = prepare_download_targets(
        ids=ids,
        database=database_config.id,
    )
    max_signatures = index_max_signatures or database_config.indexing.get(
        "batch_size",
        settings.INDEX_MAX_SIGNATURES,
    )
    retry_failed = retry_failed or database_config.download.get("retry_failed", False)
    total_downloaded = 0
    total_batches = 0
    remaining_download_budget = (
        max_downloads
        if max_downloads is not None
        else get_configured_max_downloads(database_config)
    )

    while True:
        updates_count = len(get_update_accessions(dir_paths["updates"]))
        batch_capacity = max(0, max_signatures - updates_count)
        selected_ids = []
        if (
            batch_capacity > 0
            and remaining_ids
            and (remaining_download_budget is None or remaining_download_budget > 0)
        ):
            selected_ids = select_download_ids(
                remaining_ids,
                dir_paths,
                man_fail,
                retry_failed=retry_failed,
                max_downloads=min(remaining_download_budget, batch_capacity)
                if remaining_download_budget is not None
                else batch_capacity,
                database=database_config.id,
            )
            if selected_ids:
                results = asyncio.run(
                    download_from_wort(
                        dir_paths,
                        selected_ids,
                        man_fail,
                        timeout,
                        endpoint=database_config.wort_signature_endpoint,
                        database=database_config.id,
                        retry_failed=True,
                        max_downloads=len(selected_ids),
                        max_simultaneous=max_simultaneous,
                    )
                )
                total_downloaded += sum(
                    1
                    for result in results
                    if isinstance(result, dict) and result.get("path")
                )
                remaining_id_set = set(remaining_ids)
                remaining_id_set -= set(selected_ids)
                remaining_ids = sorted(remaining_id_set)
                if remaining_download_budget is not None:
                    remaining_download_budget -= len(selected_ids)

        if not get_update_accessions(dir_paths["updates"]):
            if not remaining_ids or not selected_ids:
                break
            continue

        tmp_dir = settings.DATA_DIR / "tmp"
        os.makedirs(tmp_dir, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="mgwatch-index-", dir=tmp_dir
        ) as work_dir:
            index_result = run_index_batches(
                work_dir,
                database=database_config.id,
                index_max_signatures=max_signatures,
                max_batches=1,
                delete_indexed_sigs=True,
            )
        total_batches += index_result["batches_processed"]

        if index_result["indexes_updated"] == 0:
            break

    try_record_download_index_runtime(
        duration_seconds=monotonic() - started_at,
        downloaded=total_downloaded,
        indexes_updated=total_batches,
    )
    return {"downloaded": total_downloaded, "indexes_updated": total_batches}


def get_last_index(database, profile, dir_paths):
    database_config = get_database_config(database)
    profile_dir = profile_root(database_config.id, profile)
    batch_dirs = list(profile_dir.glob("batch-*"))
    if not batch_dirs:
        return [], max(database_config.indexing.get("first_batch_number", 38), 0), False
    manifest_num = max(
        int(batch_dir.name.removeprefix("batch-")) for batch_dir in batch_dirs
    )
    last_num = max(database_config.indexing.get("first_batch_number", 38), manifest_num)
    last_sig_ids = read_accession_parquet(
        batch_manifest(database_config.id, profile, manifest_num)
    )
    last_sig_files = [
        os.path.join(dir_paths["signatures"], f"{identifier}.sig")
        for identifier in last_sig_ids
    ]
    available = [sig_file for sig_file in last_sig_files if os.path.exists(sig_file)]
    return available, last_num, True


def can_reuse_last_index(last_sig_files, has_existing_index):
    if not has_existing_index:
        return True
    if not last_sig_files:
        return False
    return all(os.path.exists(sig_file) for sig_file in last_sig_files)


def write_signature_list(sig_file_names, output_file):
    with open(output_file, "w") as handle:
        handle.writelines(f"{fp}\n" for fp in sig_file_names)


def update_index(work_dir, database, profile, sig_list, last_num):
    old_idx = index_path(database, profile, last_num)
    new_idx = Path(work_dir) / "index.rocksdb"
    cpus = min(8, int(os.cpu_count() * 0.8))
    run_command(
        [
            "sourmash",
            "scripts",
            "index",
            "--ksize",
            f"{profile.kmer}",
            "--moltype",
            profile.moltype,
            "--scaled",
            f"{profile.scaled}",
            "--cores",
            f"{cpus}",
            "--no-store-sketches",
            "--output",
            str(new_idx),
            f"{sig_list}",
        ]
    )
    if old_idx.is_dir() and old_idx.name.endswith(".rocksdb"):
        shutil.rmtree(old_idx)
    old_idx.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(new_idx), str(old_idx))
    return 0


def move_files(file_list, dir_paths, target_dir):
    for file in file_list:
        base_name = os.path.basename(file)
        destination = os.path.join(dir_paths[target_dir], base_name)
        shutil.move(file, destination)


def delete_files(file_list):
    for file in file_list:
        if os.path.exists(file):
            os.remove(file)


def update_manifests(new_files, mani_list, database, profiles, last_num):
    new_files = [os.path.basename(file).split(".sig")[0] for file in new_files]
    sig_files = sorted(set(mani_list) | set(new_files))
    for profile in profiles:
        write_accession_parquet(
            batch_manifest(database, profile, last_num),
            new_files,
            batch=last_num,
        )
        write_accession_parquet(
            profile_manifest(database, profile),
            sig_files,
        )
    return sig_files


def run_watch():
    results = Result.objects.filter(is_watched=True)
    processed = 0
    failed = 0
    for result in results:
        try:
            signature = Signature.objects.get(user_id=result.user.id, name=result.name)
            signature.submitted = True
            signature.save(update_fields=["submitted"])
            new_result = search_watch(signature.name, signature.user.id, result.pk)
            copy_watch_filters(result, new_result)
            if compare_results(result, new_result):
                # Watch searches are expected to create a fresh result row. If an
                # existing watched result is returned instead, avoid deleting it.
                if new_result.pk != result.pk and not new_result.is_watched:
                    new_result.delete()
            else:
                result.is_watched = False
                new_result.is_watched = True
                result.save(update_fields=["is_watched"])
                new_result.save(update_fields=["is_watched"])
                send_watch_notification(result.user, result, new_result)
            processed += 1
        except Exception:
            failed += 1
            LOGGER.exception(
                "Watch run failed for result_pk=%s user_id=%s name=%s",
                result.pk,
                result.user_id,
                result.name,
            )
    return {"processed_watches": processed, "failed_watches": failed}


def search_watch(name, user_id, watch_pk):
    search_result = run_search(user_id=user_id, name=name, watch=str(watch_pk))
    return Result.objects.get(pk=search_result["result_pk"], user_id=user_id)


def copy_watch_filters(result, new_result):
    filter_setting = FilterSetting.objects.filter(
        user=result.user, result=result
    ).first()
    if not filter_setting:
        return
    FilterSetting.objects.update_or_create(
        user=new_result.user,
        result=new_result,
        defaults={"filter_spec": filter_setting.filter_spec},
    )


def compare_results(result, new_result):
    filter_setting = FilterSetting.objects.filter(
        user=result.user, result=result
    ).first()
    filter_spec = filter_setting.filter_spec if filter_setting else {}
    return filtered_result_records(result, filter_spec) == filtered_result_records(
        new_result, filter_spec
    )


def filtered_result_records(result, filter_spec):
    if not result.file:
        return []
    df = get_results_with_metadata(result)
    filtered = apply_filter_spec(df, filter_spec)
    if filtered.empty:
        return []
    normalized = filtered.fillna("").astype(str)
    sort_columns = [
        column
        for column in ["sra_accession", "containment", "query_containment_ani"]
        if column in normalized.columns
    ]
    if sort_columns:
        normalized = normalized.sort_values(by=sort_columns)
    return normalized.to_dict("records")


def send_watch_notification(user, result, new_result):
    absolute_url = reverse("mgw_api:result_table", kwargs={"pk": new_result.pk})
    result_page = f"{MGW_URL}{absolute_url}"
    subject = f"MetagenomeWatch: Found new results for watch {new_result.name}"
    message = inspect.cleandoc(f"""
    Dear MetagenomeWatch user {user.username},

    New results have been found for your watch named "{result.name}".

    You can view the results here: {result_page}

    Watch details:
        Name: {new_result.name}
        K-mer: {new_result.kmer}
        Database: {new_result.database}
        Containment threshold: {new_result.containment}

    Best wishes,
    The MetagenomeWatch Team
    """)
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
