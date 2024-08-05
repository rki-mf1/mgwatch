# mgw_api/management/commands/create_signature.py

from django.core.management.base import BaseCommand
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings

from datetime import datetime
from itertools import product
import subprocess
import os


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('user_id', type=int, help='ID of the user')
        parser.add_argument('name', type=str, help='Name of the fasta file')
    
    def handle(self, *args, **kwargs):
        user_id = kwargs['user_id']
        name = kwargs['name']
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_search - "
        signature = Signature.objects.get(user_id=user_id, name=name, submitted=True)
        try:
            uset = Settings.objects.get(user=user_id).to_dict()
            result_pks = []
            for k,db in product(uset["kmer"], uset["database"]):
                # Search signatures in rocksdb
                date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                index_path = os.path.join(settings.EXTERNAL_DATA_DIR, db, "index", f"{db}-{k}.rocksdb")
                user_path = os.path.dirname(signature.file.path)
                result_file = os.path.join(user_path, f"result_{signature.name}-{db}-{k}-{date}.csv")
                self.stdout.write(self.style.SUCCESS(result_file))
                result = self.search_index(result_file, signature.file.path, index_path, k, uset["containment"])
                if result.returncode != 0:
                    raise Exception(f"Searching failed with exit code {result.returncode}: {result.stderr}")
                # Save result to django model
                relative_path = os.path.relpath(result_file, settings.MEDIA_ROOT)
                self.stdout.write(self.style.SUCCESS(relative_path))
                result_model = Result(user=signature.user, signature=signature, name=signature.name)
                result_model.file.name = relative_path
                result_model.size = result_model.file.size
                result_model.settings_used = uset
                result_model.save()
                self.stdout.write(self.style.SUCCESS(f"Created at {result_model.created_date}'"))
                ## Update the processed status
                #self.stdout.write(self.style.SUCCESS(f"Successfully processed file '{fasta.name}'"))
                #self.stdout.write(self.style.SUCCESS(f"{log}Searching signature in database successful."))
                result_pks.append(result_model.pk)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"{log}Error processing search '{signature.name}': {e}"))
        signature.submitted = False
        signature.save()
        if result_pks:
            self.stdout.write(f"Result PKs: {result_pks}")

    def search_index(self, result_file, sketch_file, index_path, k, containment):
        cmd = ["sourmash", "scripts", "manysearch", "--ksize", f"{k}", "--moltype", "DNA", "--scaled", "1000", "--cores", "20", "--threshold", f"{containment}", "--output", result_file, sketch_file, index_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result # returncode: 0 = success, 2 = fail
    
    def combine_results(self, k, db):
        pass
