# mgw_api/management/commands/create_signature.py

import os
import subprocess
from datetime import datetime
from itertools import product
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER
from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")
        parser.add_argument("watch", type=str, help="Either False or result pk")

    def handle(self, *args, **kwargs):
        user_id, name, watch = kwargs["user_id"], kwargs["name"], kwargs["watch"]
        search_set = (
            Settings.objects.get(user=user_id)
            if watch == "False"
            else Result.objects.get(pk=int(watch))
        )
        kmer, database, containment = (
            search_set.kmer,
            search_set.database,
            search_set.containment,
        )
        result_pk = None
        try:
            signature = Signature.objects.get(
                user_id=user_id, name=name, submitted=True
            )
            user_path = Path(signature.file.path).parent
            date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            file_list = []
            for k, db in product(kmer, database):
                LOGGER.info(f"Args: {db} {k}")
                if db == "RKI" or str(k) != "21":
                    continue
                indices = self.get_indices(k, db)
                for idx, index_path in enumerate(indices):
                    result_file = (
                        user_path / f"result_{signature.name}.{db}-{k}-{idx}-{date}.csv"
                    )
                    result = self.search_index(
                        result_file, signature.file.path, index_path, k, containment
                    )
                    if result.returncode != 0:
                        LOGGER.error(
                            f"Search failed with exit code {result.returncode}: {result.stderr}."
                        )
                        raise Exception(
                            f"Searching failed with exit code {result.returncode}: {result.stderr}"
                        )
                    file_list.append((k, db, containment, result_file))
            combined_file = os.path.join(
                user_path, f"result_{signature.name}.{date}.csv"
            )
            num_results = self.combine_results(file_list, combined_file, signature.name)
            # Save result to django model
            relative_path = os.path.relpath(combined_file, settings.MEDIA_ROOT)
            result_model = Result(
                user=signature.user, signature=signature, name=signature.name
            )
            result_model.file.name = relative_path if num_results > 0 else None
            result_model.num_results = num_results
            result_model.kmer = kmer
            result_model.database = database
            result_model.containment = containment
            result_model.save()
            LOGGER.debug(f"Created at {result_model.date}")
            result_pk = result_model.pk
            signature.submitted = False
            signature.save()
            LOGGER.info(f"Search finished with result_pk = {result_pk}.")
            ## Do NOT remove this line:
            self.stdout.write(self.style.SUCCESS(f"RESULT_PK: {result_pk}"))
        except Exception as e:
            LOGGER.error(f"Error processing search '{signature.name}': {e}")
            self.stdout.write(self.style.SUCCESS("RESULT_PK: failed"))

    def get_indices(self, k, db):
        index_dir = settings.DATA_DIR / db / "metagenomes" / "index"
        new_files = list(index_dir.glob(f"wort-{db.lower()}-{k}-db*.rocksdb"))
        LOGGER.info(f"Found new indexes: {new_files}")
        return new_files

    def search_index(self, result_file, sketch_file, index_path, k, containment):
        # Limit this to 1 cpu per search for now, because we were overloading
        # the server with the default
        cores = 1
        cmd = [
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
        LOGGER.info(f"Running search command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def combine_results(self, file_list, combined_file, query_name):
        """Returns the number of results"""
        read_files = []
        for k, db, c, filename in file_list:
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
        num_results = sorted_results.shape[0]
        return num_results
