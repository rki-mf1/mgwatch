import inspect
import os
from datetime import datetime
from itertools import product
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from mgw.settings import LOGGER
from mgw.settings import MGW_URL
from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature

from .processes import run_command


def get_search_context(*, user_id, name, watch):
    signature = Signature.objects.get(user_id=user_id, name=name, submitted=True)
    search_set = (
        Settings.objects.get(user=user_id)
        if watch == "False"
        else Result.objects.get(pk=int(watch))
    )
    return signature, search_set


def get_indices(k, db):
    index_dir = settings.DATA_DIR / db / "metagenomes" / "index"
    new_files = list(index_dir.glob(f"{k}mers-db*.rocksdb"))
    LOGGER.info("Found indexes for db=%s k=%s: %s", db, k, new_files)
    return new_files


def build_search_plan(*, user_id, name, watch):
    signature, search_set = get_search_context(user_id=user_id, name=name, watch=watch)
    kmer, database, containment = (
        search_set.kmer,
        search_set.database,
        search_set.containment,
    )
    plan = []
    for k, db in product(kmer, database):
        indices = get_indices(k, db)
        for idx, index_path in enumerate(indices):
            plan.append(
                {
                    "kmer": k,
                    "database": db,
                    "containment": containment,
                    "index_idx": idx,
                    "index_path": str(index_path),
                }
            )
    return signature, search_set, plan


def search_index(*, result_file, sketch_file, index_path, k, containment):
    cores = 1
    run_command(
        [
            "sourmash",
            "scripts",
            "manysearch",
            "--ksize",
            f"{k}",
            "--moltype",
            "DNA",
            "--scaled",
            "1000",
            "--cores",
            f"{cores}",
            "--threshold",
            f"{containment}",
            "--output",
            str(result_file),
            str(sketch_file),
            str(index_path),
        ]
    )


def combine_results(file_list, combined_file, query_name):
    read_files = []
    for k, db, filename in file_list:
        try:
            df = pd.read_csv(
                filename, index_col=None, header=0, dtype={"containment": "float64"}
            )
        except pd.errors.EmptyDataError:
            continue
        df["k-mer"] = str(k)
        df["database"] = str(db)
        read_files.append(df)
    if len(read_files) == 0:
        return 0
    combined_results = pd.concat(read_files, axis=0, ignore_index=True)
    combined_results.drop(columns="query_name", inplace=True)
    combined_results.insert(0, "query_name", query_name)
    sorted_results = combined_results.sort_values(by="containment", ascending=False)
    sorted_results.to_csv(combined_file)
    return sorted_results.shape[0]


def save_result(*, signature, search_set, combined_file, num_results):
    relative_path = os.path.relpath(combined_file, settings.MEDIA_ROOT)
    result_model = Result(user=signature.user, signature=signature, name=signature.name)
    result_model.file.name = relative_path if num_results > 0 else None
    result_model.num_results = num_results
    result_model.kmer = search_set.kmer
    result_model.database = search_set.database
    result_model.containment = search_set.containment
    result_model.save()
    signature.submitted = False
    signature.save(update_fields=["submitted"])
    return result_model


def send_notification(result):
    user = result.user
    absolute_url = reverse("mgw_api:result_table", kwargs={"pk": result.pk})
    result_page = f"{MGW_URL}{absolute_url}"
    subject = f'MetagenomeWatch: Search completed for search named "{result.name}"'
    message = inspect.cleandoc(f"""
    Dear MetagenomeWatch user {user.username},

    Your search "{result.name}" has completed. You can view the results here: {result_page}

    Search details:
        Name: {result.name}
        Number of results: {result.num_results}
        K-mer: {result.kmer}
        Database: {result.database}
        Containment threshold: {result.containment}

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


def run_search(*, user_id, name, watch, progress_callback=None, state_callback=None):
    signature, search_set, plan = build_search_plan(
        user_id=user_id, name=name, watch=watch
    )
    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    user_path = Path(signature.file.path).parent
    file_list = []
    total = len(plan)
    for idx, item in enumerate(plan, start=1):
        result_file = (
            user_path
            / f"result_{signature.name}.{item['database']}-{item['kmer']}-{item['index_idx']}-{date}.csv"
        )
        search_index(
            result_file=result_file,
            sketch_file=signature.file.path,
            index_path=item["index_path"],
            k=item["kmer"],
            containment=item["containment"],
        )
        file_list.append((item["kmer"], item["database"], result_file))
        if progress_callback:
            progress_callback(idx, total)
    if state_callback:
        state_callback("combining_results")
    combined_file = os.path.join(user_path, f"result_{signature.name}.{date}.csv")
    num_results = combine_results(file_list, combined_file, signature.name)
    if state_callback:
        state_callback("saving_result")
    result_model = save_result(
        signature=signature,
        search_set=search_set,
        combined_file=combined_file,
        num_results=num_results,
    )
    send_notification(result_model)
    LOGGER.info("Search finished with result_pk = %s.", result_model.pk)
    return {"result_pk": result_model.pk, "total_indexes": total}
