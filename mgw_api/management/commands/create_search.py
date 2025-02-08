# mgw_api/management/commands/create_signature.py

import glob
import os
import subprocess
from datetime import datetime
from itertools import product

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
            LOGGER.info(f"Searching signature {signature.name}.")
            file_list = []
            for k, db in product(kmer, database):
                if db == "RKI" or k != "21":
                    continue
                date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                for idx, index_path in enumerate(self.get_indices(k, db)):
                    user_path = os.path.dirname(signature.file.path)
                    result_file = os.path.join(
                        user_path, f"result_{signature.name}.{db}-{k}-{idx}-{date}.csv"
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
            self.combine_results(file_list, combined_file, signature.name)
            # Save result to django model
            relative_path = os.path.relpath(combined_file, settings.MEDIA_ROOT)
            self.stdout.write(self.style.SUCCESS(relative_path))
            result_model = Result(
                user=signature.user, signature=signature, name=signature.name
            )
            result_model.file.name = relative_path
            result_model.size = result_model.file.size
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

    def get_indices(self, k, db):
        index_dir = os.path.join(settings.DATA_DIR, f"{db}", "metagenomes", "index")
        new_files = glob.glob(
            os.path.join(index_dir, f"wort-{db.lower()}-{k}-db*.rocksdb")
        )
        LOGGER.debug(f"Found new indexes: {new_files}")
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
            result_file,
            sketch_file,
            index_path,
        ]
        LOGGER.debug(f"Running search command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def combine_results(self, file_list, combined_file, query_name):
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
            df["containment_threshold"] = str(c)
            read_files.append(df)
            if len(read_files) == 0:
                # TODO: not sure what to do if there are no results
                return
        combined_results = pd.concat(read_files, axis=0, ignore_index=True)
        combined_results.drop(columns="query_name", inplace=True)
        combined_results.insert(0, "query_name", query_name)
        sorted_results = combined_results.sort_values(by="containment", ascending=False)
        sorted_results.to_csv(combined_file)
