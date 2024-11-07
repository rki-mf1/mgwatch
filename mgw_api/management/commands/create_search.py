# mgw_api/management/commands/create_signature.py

from django.core.management.base import BaseCommand, CommandError
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings

from datetime import datetime
from itertools import product
import subprocess
import os
import csv
import multiprocessing as mp
import glob

from mgw.settings import LOGGER


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('user_id', type=int, help='ID of the user')
        parser.add_argument('name', type=str, help='Name of the fasta file')
        parser.add_argument('watch', type=str, help='Either False or result pk')
    
    def handle(self, *args, **kwargs):
        user_id, name, watch = kwargs['user_id'], kwargs['name'], kwargs['watch']
        search_set = Settings.objects.get(user=user_id) if watch == "False" else Result.objects.get(pk=int(watch))
        kmer, database, containment = search_set.kmer, search_set.database, search_set.containment
        result_pk = None
        try:
            signature = Signature.objects.get(user_id=user_id, name=name, submitted=True)
            LOGGER.info(f"Searching signature {signature.name}.")
            file_list = []
            for k, db in product(kmer, database):
                if db == "RKI" or k != "21": continue
                date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                for idx, index_path in enumerate(self.get_indices(k, db)):
                    user_path = os.path.dirname(signature.file.path)
                    result_file = os.path.join(user_path, f"result_{signature.name}.{db}-{k}-{idx}-{date}.csv")
                    result = self.search_index(result_file, signature.file.path, index_path, k, containment)
                    if result.returncode != 0:
                        LOGGER.error(f"Search failed with exit code {result.returncode}: {result.stderr}.")
                        raise Exception(f"Searching failed with exit code {result.returncode}: {result.stderr}")
                    file_list.append((k, db, containment, result_file))
            combined_file = os.path.join(user_path, f"result_{signature.name}.{date}.csv")
            self.combine_results(file_list, combined_file, signature.name)
            # Save result to django model
            relative_path = os.path.relpath(combined_file, settings.MEDIA_ROOT)
            self.stdout.write(self.style.SUCCESS(relative_path))
            result_model = Result(user=signature.user, signature=signature, name=signature.name)
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
        except Exception as e:
            LOGGER.error(f"Error processing search '{signature.name}': {e}")

    def get_indices(self, k, db):
        index_dir = os.path.join(settings.DATA_DIR, f"{db}", "metagenomes", "index")
        new_files = glob.glob(os.path.join(index_dir, f"wort-{db.lower()}-{k}-db*.rocksdb"))
        LOGGER.debug(f"Found new indexes: {new_files}")
        return new_files

    def search_index(self, result_file, sketch_file, index_path, k, containment):
        cpus = min(8, int(mp.cpu_count()*0.8))
        cmd = ["sourmash", "scripts", "manysearch", "--ksize", f"{k}", "--moltype", "DNA", "--scaled", "1000", "--cores", f"{cpus}", "--threshold", f"{containment}", "--output", result_file, sketch_file, index_path]
        LOGGER.debug(f"Running commands: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result # returncode: 0 = success, 2 = fail
    
    def combine_results(self, file_list, combined_file, query_name):
        header, table_data = "", list()
        for k, db, c, file in file_list:
            if os.stat(file).st_size != 0:
                header, t_data = self.read_table(file, query_name, k, db, c)
                table_data = table_data + t_data
            if os.path.exists(file): os.remove(file)
        with open(combined_file, 'w', newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header)
            for row in table_data:
                writer.writerow(row)
    
    def read_table(self, file, query_name, k, db, c):
        with open(file, newline="") as csvfile:
            reader = csv.reader(csvfile)
            header = next(reader) + ["k-mer", "database", "containment_threshold"]
            table_data = [[query_name] + row[1:] + [f"{k}", f"{db}", f"{c}"] for row in reader]
        return header, table_data

