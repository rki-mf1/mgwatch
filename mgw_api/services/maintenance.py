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
from mgw_api.models import Result
from mgw_api.models import Signature

from .processes import run_command
from .searches import run_search

SRA_METADATA_BUCKET = "sra-pub-metadata-us-east-1"
SRA_METADATA_PREFIX = "sra/metadata/"
SRA_METADATA_MAX_DOWNLOADS = 8


def run_metadata(
    *, no_download=False, no_process=False, drop_first=False, indexed_only=False
):
    LOGGER.info("Starting metadata update")
    database = "SRA"
    metadata_dir = settings.DATA_DIR / database / "metadata" / "parquet"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if drop_first:
        drop_mongo_collection("sradb_list")
        drop_mongo_collection("sradb_temp")

    if not no_download:
        asyncio.run(
            sync_public_s3_prefix(
                SRA_METADATA_BUCKET,
                SRA_METADATA_PREFIX,
                metadata_dir,
            )
        )

    if not no_process:
        import_parquet(metadata_dir, indexed_only=indexed_only)

    init_flag = settings.DATA_DIR / "SRA" / "metadata" / "initial_setup.txt"
    init_flag.touch()
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
        "organism",
        "releasedate",
        "librarysource",
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


def import_parquet(parquet_dir, indexed_only=False):
    drop_mongo_collection("sradb_temp")
    column_list, jattr_dtypes, allowed_librarysources = get_filter_data()
    indexed_ids = None
    if indexed_only:
        indexed_ids_file = settings.DATA_DIR / "SRA" / "metagenomes" / "manifest.pickle"
        if indexed_ids_file.exists():
            with open(indexed_ids_file, "rb") as handle:
                indexed_ids = pickle.load(handle)

    for parquet_file in parquet_dir.glob("*"):
        df = pl.scan_parquet(parquet_file)
        sra_lf = df.filter(
            pl.col("librarysource").is_in(allowed_librarysources)
        ).select(column_list + ["jattr"])
        if indexed_ids:
            sra_lf = sra_lf.filter(pl.col("acc").is_in(indexed_ids))
        sra_df = (
            sra_lf.collect()
            .with_columns(pl.col(pl.Date).cast(pl.Datetime))
            .with_columns(
                pl.col("jattr").str.json_decode(jattr_dtypes).alias("jattr_decoded")
            )
            .drop("jattr")
            .unnest("jattr_decoded")
            .with_columns(
                [
                    pl.col("acc").alias("_id"),
                    pl.col("acc").alias("sra_accession"),
                    pl.col("biosample").alias("sra_biosample"),
                    pl.col("bioproject").alias("sra_bioproject"),
                ]
            )
        )
        if sra_df.height > 0:
            mongo = pm.MongoClient(settings.MONGO_URI)
            db = mongo["sradb"]
            db["sradb_temp"].insert_many(sra_df.to_dicts())
            mongo.close()

    drop_mongo_collection("sradb_list")
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    db["sradb_temp"].rename("sradb_list")
    mongo.close()


def run_downloads(
    *,
    max_downloads=None,
    max_simultaneous=100,
    timeout=60,
    ids=None,
    retry_failed=False,
):
    test_url = "https://wort.sourmash.bio/v1/view/sra/SRR15461028"
    run_command(["curl", "-sLf", "-r", "0-10", test_url, "-o", "/dev/null"])
    dir_paths, man_fail, sra_ids = prepare_download_targets(ids=ids)
    selected_ids = select_download_ids(
        sra_ids,
        dir_paths,
        man_fail,
        retry_failed=retry_failed or not settings.WORT_SKIP_FAILED,
        max_downloads=max_downloads,
    )
    results = asyncio.run(
        download_from_wort(
            dir_paths,
            selected_ids,
            man_fail,
            timeout,
            retry_failed=True,
            max_downloads=len(selected_ids),
            max_simultaneous=max_simultaneous,
        )
    )
    downloaded = sum(
        1 for result in results if isinstance(result, dict) and result.get("path")
    )
    return {"downloaded": downloaded}


def prepare_download_targets(ids=None):
    database = "SRA"
    dir_paths = handle_dirs(
        database, ["updates", "index", "signatures", "indexing-failed", "manifests"]
    )
    man_fail = settings.DATA_DIR / database / "metagenomes" / "download_failed.pickle"
    manifest = settings.DATA_DIR / database / "metagenomes" / "manifest.pickle"
    if not ids and not manifest.exists() and not settings.INDEX_FROM_SCRATCH:
        raise RuntimeError(
            "manifest.pickle is missing and INDEX_FROM_SCRATCH is disabled; "
            "create manifests first or provide explicit IDs"
        )
    mani_list = set(get_manifest(manifest))
    if ids:
        wanted_ids = set(ids) - mani_list
    else:
        start_date, end_date = get_download_date_range()
        mongo_ids = get_mongo_ids(start_date, end_date)
        wanted_ids = set(mongo_ids) - mani_list
    sra_ids_in_wort = get_wort_accessions()
    return dir_paths, man_fail, sorted(wanted_ids & sra_ids_in_wort)


def get_download_date_range():
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
    return start_date, end_date


def select_download_ids(
    sra_ids, dir_paths, man_fail, *, retry_failed=False, max_downloads=None
):
    selected_ids = set(sra_ids) - get_update_accessions(dir_paths["updates"])
    ids_fail = set(load_pickle(man_fail)) if man_fail.exists() else set()
    if not retry_failed:
        selected_ids -= ids_fail
    selected_ids = sorted(selected_ids)
    if max_downloads is None and settings.MAX_DOWNLOADS:
        max_downloads = settings.MAX_DOWNLOADS
    if max_downloads and max_downloads < len(selected_ids):
        selected_ids = selected_ids[:max_downloads]
    return selected_ids


def handle_dirs(database, dir_names):
    dir_paths = {n: settings.DATA_DIR / database / "metagenomes" / n for n in dir_names}
    for dir_path in dir_paths.values():
        dir_path.mkdir(parents=True, exist_ok=True)
        os.chmod(dir_path, 0o700)
    return dir_paths


def get_manifest(manifest):
    if not os.path.exists(manifest):
        return []
    with open(manifest, "rb") as handle:
        return pickle.load(handle)


def get_mongo_ids(start_date, end_date):
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    collection = db["sradb_list"]
    query = {"releasedate": {"$gte": start_date, "$lte": end_date}}
    if settings.LIB_SOURCE:
        query = query | {"librarysource": {"$in": settings.LIB_SOURCE}}
    ids = [doc["_id"] for doc in collection.find(query, {"_id": 1})]
    mongo.close()
    return ids


def get_wort_accessions():
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


async def download_from_wort(
    dir_paths,
    sra_ids,
    man_fail,
    timeout_seconds,
    retry_failed=False,
    max_downloads=None,
    max_simultaneous=100,
):
    ids_fail = set(load_pickle(man_fail)) if man_fail.exists() else set()
    sra_ids = select_download_ids(
        sra_ids,
        dir_paths,
        man_fail,
        retry_failed=retry_failed,
        max_downloads=max_downloads,
    )
    target_dir = dir_paths["updates"]
    signature_endpoint = "https://wort.sourmash.bio/v1/view/sra"
    urls = [f"{signature_endpoint}/{id_}" for id_ in sra_ids]
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
                    await asyncio.to_thread(save_pickle, ids_fail, man_fail)
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
            await asyncio.to_thread(save_pickle, ids_fail, man_fail)
        return {"id": accession, "status": None}


def save_pickle(data, file):
    with open(file, "wb") as handle:
        pickle.dump(data, handle, protocol=4)


def load_pickle(file):
    with open(file, "rb") as handle:
        return pickle.load(handle)


def get_update_accessions(updates_dir):
    return {sig_path.stem for sig_path in Path(updates_dir).glob("*.sig")}


def run_index(*, index_max_signatures=None):
    tmp_dir = settings.DATA_DIR / "tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mgwatch-index-", dir=tmp_dir) as work_dir:
        result = run_index_batches(
            work_dir,
            index_max_signatures=index_max_signatures,
            max_batches=None,
            delete_indexed_sigs=getattr(settings, "DELETE_INDEXED_SIGS", False),
        )
    return {"indexes_updated": result["indexes_updated"]}


def run_index_batches(
    work_dir,
    *,
    index_max_signatures=None,
    max_batches=None,
    delete_indexed_sigs=False,
):
    kmers = [21, 31, 51]
    database = "SRA"
    metagenomes_dir = settings.DATA_DIR / database / "metagenomes"
    sig_list = Path(work_dir) / "sig-list.txt"
    manifest = metagenomes_dir / "manifest.pickle"
    dir_paths = handle_dirs(
        database, ["updates", "index", "signatures", "indexing-failed", "manifests"]
    )
    mani_list = get_manifest(manifest)
    last_sig_files, last_num, has_existing_index = get_last_index(dir_paths)
    max_signatures = index_max_signatures or settings.INDEX_MAX_SIGNATURES
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
    indexing_ever_failed = False
    for index_number, new_files in batch_specs:
        indexing_succeeded, mani_list = process_index_batch(
            work_dir,
            dir_paths,
            sig_list,
            kmers,
            index_number,
            new_files,
            mani_list,
            manifest,
            max_signatures,
            delete_indexed_sigs,
        )
        indexing_ever_failed = indexing_ever_failed or not indexing_succeeded
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
    kmers,
    index_number,
    new_files,
    mani_list,
    manifest,
    max_signatures,
    delete_indexed_sigs,
):
    write_signature_list(new_files, sig_list)
    try:
        retvals = [
            update_index(work_dir, dir_paths["index"], sig_list, k, index_number)
            for k in kmers
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
            new_files, mani_list, manifest, dir_paths, index_number
        )
    return indexing_succeeded, mani_list


def run_download_index(
    *,
    max_downloads=None,
    max_simultaneous=100,
    timeout=60,
    ids=None,
    retry_failed=False,
    index_max_signatures=None,
):
    test_url = "https://wort.sourmash.bio/v1/view/sra/SRR15461028"
    run_command(["curl", "-sLf", "-r", "0-10", test_url, "-o", "/dev/null"])
    dir_paths, man_fail, remaining_ids = prepare_download_targets(ids=ids)
    max_signatures = index_max_signatures or settings.INDEX_MAX_SIGNATURES
    retry_failed = retry_failed or not settings.WORT_SKIP_FAILED
    total_downloaded = 0
    total_batches = 0
    remaining_download_budget = max_downloads

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
            )
            if selected_ids:
                results = asyncio.run(
                    download_from_wort(
                        dir_paths,
                        selected_ids,
                        man_fail,
                        timeout,
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
                index_max_signatures=max_signatures,
                max_batches=1,
                delete_indexed_sigs=True,
            )
        total_batches += index_result["batches_processed"]

        if index_result["indexes_updated"] == 0:
            break

    return {"downloaded": total_downloaded, "indexes_updated": total_batches}


def get_last_index(dir_paths):
    manifests = list(dir_paths["manifests"].glob("db*.pickle"))
    if not manifests:
        return [], max(settings.INDEX_MIN_ITERATOR, 0), False
    manifest_num = max(
        [int(f.name.split("db")[1].split(".pickle")[0]) for f in manifests]
    )
    last_num = max(settings.INDEX_MIN_ITERATOR, manifest_num)
    last_sigs = os.path.join(dir_paths["manifests"], f"db{manifest_num}.pickle")
    with open(last_sigs, "rb") as handle:
        last_sig_ids = pickle.load(handle)
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


def update_index(work_dir, index_dir, sig_list, k, last_num):
    old_idx = os.path.join(index_dir, f"{k}mers-db{last_num}.rocksdb")
    new_idx = os.path.join(work_dir, f"{k}mers-db{last_num}.rocksdb")
    cpus = min(8, int(os.cpu_count() * 0.8))
    run_command(
        [
            "sourmash",
            "scripts",
            "index",
            "--ksize",
            f"{k}",
            "--moltype",
            "DNA",
            "--scaled",
            "1000",
            "--cores",
            f"{cpus}",
            "--no-store-sketches",
            "--output",
            f"{new_idx}",
            f"{sig_list}",
        ]
    )
    if os.path.isdir(old_idx) and old_idx.endswith(".rocksdb"):
        shutil.rmtree(old_idx)
    shutil.move(new_idx, old_idx)
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


def update_manifests(new_files, mani_list, manifest, dir_paths, last_num):
    new_files = [os.path.basename(file).split(".sig")[0] for file in new_files]
    last_sigs = os.path.join(dir_paths["manifests"], f"db{last_num}.pickle")
    with open(last_sigs, "wb") as handle:
        pickle.dump(new_files, handle, protocol=4)
    sig_files = list(set(mani_list) | set(new_files))
    with open(manifest, "wb") as handle:
        pickle.dump(sig_files, handle, protocol=4)
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


def compare_results(result, new_result):
    df1 = pl.read_csv(result.file.path)
    df2 = pl.read_csv(new_result.file.path)
    return df1.equals(df2)


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
