# mgw_api/management/commands/create_signature.py

from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from mgw_api.models import Fasta, Signature

import sourmash
import re


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        pending_files = Fasta.objects.filter(processed=False)
        kmers = [21,31,51]
        for fasta in pending_files:
            try:
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

    def read_fasta_file(self, fasta_file):
        fasta_dict, seq = dict(), ""
        with open(fasta_file, "r") as infa:
            for line in infa:
                line = line.strip()
                if re.match(r">", line):
                    if seq: fasta_dict[name] = seq
                    seq, name = "", line[1:]
                else:
                    seq += line
            fasta_dict[name] = seq
        return fasta_dict

    def calculate_signatures(self, fasta_dict, kmers):
        signature_list = list()
        #mh = MinHash(n=0, ksize=K, is_protein=True, scaled=1)
        #sourmash_args.SaveSignaturesToFile
        for k in kmers:
            mh = sourmash.MinHash(n=0, ksize=k, scaled=1000)
            for name,seq in fasta_dict.items():
                mh.add_sequence(seq,force=True)
            sig = sourmash.SourmashSignature(mh, name=name)
            signature_list.append(sig)
        return sourmash.save_signatures(signature_list)
