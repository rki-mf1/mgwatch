# mgw_api/management/commands/create_signature.py

from django.core.management.base import BaseCommand
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings

from datetime import datetime
from itertools import product
import subprocess
import os



class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_search - "
        pending_files = Signature.objects.filter(submitted=True)
        for signature in pending_files:
            try:
                uset = signature.settings_used
                for k,db in product(uset["kmer"], uset["database"]):
                    # Search signatures in rocksdb
                    date = datetime.now().strftime("%Y%m%d")
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
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"{log}Error processing search '{signature.name}': {e}"))
            signature.submitted = False
            signature.save()

    def search_index(self, result_file, sketch_file, index_path, k, containment):
        cmd = ["sourmash", "scripts", "manysearch", "--ksize", f"{k}", "--moltype", "DNA", "--scaled", "1000", "--cores", "20", "--threshold", f"{containment}", "--output", result_file, sketch_file, index_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result # returncode: 0 = success, 2 = fail
    
    def combine_results(self, k, db):
        pass



#            sig_list = os.path.join(settings.EXTERNAL_DATA_DIR, database, f"sig-list.txt")
#            manifest = os.path.join(settings.EXTERNAL_DATA_DIR, database, f"manifest.pcl")
#            dir_paths = self.handle_dirs(database)
#            sig_files = self.get_manifest(manifest, dir_paths)
#            new_files = self.check_updates(sig_files, dir_paths)
#            if new_files:
#                self.create_list(new_files, sig_list)
#                results = [self.update_index(dir_paths, sig_list, database, k) for k in kmers]
#                td, rs = ("failed", ".err") if sum([int(r.returncode) for r in results]) else ("signatures", "")
#                self.move_files(new_files, dir_paths, td, rs)
#                self.update_manifest(new_files, sig_files, manifest)
#                self.stdout.write(self.style.SUCCESS(f"{log}Updated index and moved new signatures."))
#
#
#
#
#
#
#
#                # Save signatures to django model
#                relative_path = os.path.relpath(signature_file, settings.MEDIA_ROOT)
#                self.stdout.write(self.style.SUCCESS(relative_path))
#                signature_model = Signature(user=fasta.user, fasta=fasta, name=fasta.name)
#                signature_model.file.name = relative_path
#                signature_model.size = signature_model.file.size
#                signature_model.save()
#                ## Update the processed status
#                self.stdout.write(self.style.SUCCESS(f"Successfully processed file '{fasta.name}'"))
#                fasta.delete()
#            except Exception as e:
#                self.stdout.write(self.style.ERROR(f"Error processing file '{fasta.name}': {e}"))
#            signature.submitted = False
#            signature.save()
#
#
#
#
#
#
#
#
#                self.stdout.write(self.style.SUCCESS(f"{log}Updated index and moved new signatures."))
#            else:
#                self.stdout.write(self.style.SUCCESS(f"{log}No new files to process in {dir_paths['updates']}."))
#        except Exception as e:
#            self.stdout.write(self.style.ERROR(f"{log}Error processing directory '{settings.EXTERNAL_DATA_DIR}': {e}"))
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#    time_s = get_time()
#    kmers = [21,31,51]
#    database = "old"
#    pending_files = glob.glob(os.path.join(EXTERNAL_DATA_DIR, "old", "sketches", "*.sig.gz"))
#    print(pending_files)
#    sig_data = list()
#    for sketch_file in pending_files:
#        for k in kmers:
#            sketch_name = os.path.basename(os.path.splitext(os.path.splitext(sketch_file)[0])[0])
#            search_file = os.path.join(EXTERNAL_DATA_DIR, "old", "search", f"{sketch_name}.csv")
#            index_path = os.path.join(EXTERNAL_DATA_DIR, "old", "index", f"{database}-{k}.rocksdb")
#            sig_data.append(search_index(index_path, sketch_file, search_file, k))
#    print([r.returncode for r in sig_data])
#    print(sum([int(r.returncode) for r in sig_data]))
#    exit()
