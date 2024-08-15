# mgw_api/management/commands/create_signature.py

from django.core.management.base import BaseCommand, CommandError
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings

from datetime import datetime
from itertools import product
import subprocess
import os
import csv


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('user_id', type=int, help='ID of the user')
        parser.add_argument('name', type=str, help='Name of the fasta file')
        parser.add_argument('watch', type=str, help='Either False or result pk')
    
    def handle(self, *args, **kwargs):
        user_id, name, watch = kwargs['user_id'], kwargs['name'], kwargs['watch']
        search_set = Settings.objects.get(user=user_id) if watch == "False" else Result.objects.get(pk=int(watch))
        kmer, database, containment = search_set.kmer, search_set.database, search_set.containment
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_search - "
        result_pk = None
        test_path = os.path.dirname(os.path.abspath(__file__))
        log_file_path = os.path.join(test_path, "test.log")
        with open(log_file_path, "a") as logf:
            try:
                signature = Signature.objects.get(user_id=user_id, name=name, submitted=True)
                file_list = []
                logf.write(f"Debug Search: kmer = {kmer}, database = {database}, containment = {containment}\n")
                for k, db in product(kmer, database):
                    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                    index_path = os.path.join(settings.EXTERNAL_DATA_DIR, db, "index", f"{db}-{k}.rocksdb")
                    user_path = os.path.dirname(signature.file.path)
                    result_file = os.path.join(user_path, f"result_{signature.name}.{db}-{k}-{date}.csv")
                    self.stdout.write(self.style.SUCCESS(result_file))
                    result = self.search_index(result_file, signature.file.path, index_path, k, containment)
                    if result.returncode != 0:
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
                self.stdout.write(self.style.SUCCESS(f"Created at {result_model.date}"))
                result_pk = result_model.pk
                signature.submitted = False
                signature.save()
                logf.write(f"Debug Search: result_pk = {result_pk}\n")
                self.stdout.write(self.style.SUCCESS(f"RESULT_PK: {result_pk}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"{log}Error processing search '{signature.name}': {e}"))

    def search_index(self, result_file, sketch_file, index_path, k, containment):
        cmd = ["sourmash", "scripts", "manysearch", "--ksize", f"{k}", "--moltype", "DNA", "--scaled", "1000", "--cores", "20", "--threshold", f"{containment}", "--output", result_file, sketch_file, index_path]
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



## added result combination functionality
## todo: fix result_list search