# mgw_api/management/commands/sourmash_search.py

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from mgw_api.models import Signature, Result, Settings
import sourmash
import re
import csv


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        pending_files = Signature.objects.filter(submitted=True)
        for signature in pending_files:
            try:
                # Read the requested signature
                user = signature.user
                user_settings = Settings.objects.get(user=user)
                search_settings = user_settings.to_dict()
                kmers = [k for k in [21,31,51] if search_settings[f"kmer_{k}"]]
                # Read signature file
                result_list = self.run_sourmash_search(signature.file.path, kmers)
                # Save results to django model
                result_file = f"result_{signature.name}.csv"


                csv_buffer = StringIO()
                csv_writer = csv.writer(csv_buffer)
                for row in data:
                    csv_writer.writerow(row)
                csv_content = csv_buffer.getvalue()
                csv_buffer.close()
                csv_file = ContentFile(csv_content)
                csv_file.name = 'attributes.csv'
                my_instance = MyModel()
                my_instance.csv_file.save(csv_file.name, csv_file)
                my_instance.save()


                loaded_sig = load_one_signature(tempdir + '/genome1.sig')
                

                result = Result.objects.create(
                    user=user,
                    name=f'Result for {signature.name}',
                    signature=signature,
                    file=result_file,
                    settings_used=search_settings,
                    created_at=timezone.now(),
                    size=os.path.getsize(result_file_path),
                    is_watched=False
                )

                # Read fasta and generate signatures
                fasta_dict = self.read_fasta_file(fasta.file.path)
                sig_data = self.calculate_signatures(fasta_dict, [21, 31, 51])
                # Save signatures to django model
                signature_file = f"signature_{fasta.name}.js"
                signature_content = ContentFile(sig_data)
                signature_model = Signature(user=fasta.user, fasta=fasta, name=fasta.name)
                signature_model.file.save(signature_file, signature_content)
                signature_model.size = signature_model.file.size
                signature_model.save()
                # Update the processed status
                self.stdout.write(self.style.SUCCESS(f"Successfully processed file '{fasta.name}'"))
                fasta.delete()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing file '{fasta.name}': {e}"))

    def run_sourmash_search(self, signature_file, kmers):
        index_dir = "/home/desirod/Documents/branchwater/mgw/mgw_api/test/index"
        result_list = ["query", "target", "similarity", "k-mer"]
        for k in kmers:
            SBT_file = os.path.join(index_dir, f"index_{k}.sbt.zip")
            tree = sourmash.load_file_as_index(SBT_file)
            sigs = list(sourmash.load_file_as_signatures(signature_file, ksize=k, select_moltype="DNA"))
            for sig in sigs:
                for similarity, found_sig, filename in tree.search(sig, threshold=0.1):
                    result_list.append([sig, found_sig, similarity, k])
        return result_list


import os
import subprocess
import sys
from django.contrib.auth.models import User
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from your_app.models import Signature, Settings, Result

def process_signature(signature_id):
    signature = Signature.objects.get(pk=signature_id)
    user = signature.user
    user_settings = Settings.objects.get(user=user)
    
    # Create a copy of the user's settings
    settings_copy = user_settings.to_dict()
    
    # Process the signature here
    # For example, we'll just create a dummy file as the result
    result_file_path = os.path.join(settings.MEDIA_ROOT, f'results/{user.username}_result.txt')
    with open(result_file_path, 'w') as f:
        f.write('Signature processing result...')
    
    # Save the result file to the Result model
    with open(result_file_path, 'rb') as f:
        result_file = ContentFile(f.read(), name=f'{user.username}_result.txt')

    result = Result.objects.create(
        user=user,
        name=f'Result for {signature.name}',
        signature=signature,
        file=result_file,
        settings_used=settings_copy,
        created_at=timezone.now(),
        size=os.path.getsize(result_file_path),
        is_watched=False
    )
    
    # Cleanup the dummy result file
    os.remove(result_file_path)

if __name__ == '__main__':
    signature_id = int(sys.argv[1])
    process_signature(signature_id)





from django.core.management.base import BaseCommand
from your_app.scripts.process_signature import process_signature

class Command(BaseCommand):
    help = 'Process signature file'

    def add_arguments(self, parser):
        parser.add_argument('signature_id', type=int)

    def handle(self, *args, **kwargs):
        signature_id = kwargs['signature_id']
        process_signature(signature_id)
        self.stdout.write(self.style.SUCCESS('Successfully processed signature "%s"' % signature_id))