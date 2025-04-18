# mgw_api/management/commands/create_signature.py

import os
import subprocess
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER
from mgw_api.models import Fasta
from mgw_api.models import Signature


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("user_id", type=int, help="ID of the user")
        parser.add_argument("name", type=str, help="Name of the fasta file")

    def handle(self, *args, **kwargs):
        user_id = kwargs["user_id"]
        name = kwargs["name"]
        fasta = Fasta.objects.get(user_id=user_id, name=name, processed=False)
        LOGGER.info(f"Creating a signature for {fasta.name}.")
        try:
            date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            user_path = os.path.dirname(fasta.file.path)
            signature_file = os.path.join(
                user_path, f"signature_{fasta.name}.{date}.sig.gz"
            )
            LOGGER.debug(signature_file)
            result = self.calculate_signatures(fasta.file.path, signature_file)
            if result.returncode != 0:
                raise Exception(
                    f"Sketching failed with exit code {result.returncode}: {result.stderr}"
                )
            relative_path = os.path.relpath(signature_file, settings.MEDIA_ROOT)
            LOGGER.debug(relative_path)
            signature_model = Signature(user=fasta.user, fasta=fasta, name=fasta.name)
            signature_model.file.name = relative_path
            signature_model.size = signature_model.file.size
            signature_model.submitted = True
            signature_model.save()
            LOGGER.info(f"Successfully processed file '{fasta.name}'")
        except Exception as e:
            LOGGER.error(f"Error processing file '{fasta.name}': {e}")
        fasta.processed = True
        fasta.file.delete()
        fasta.save()

    def calculate_signatures(self, fasta_file, sig_file):
        pstring = "k=21,k=31,k=51,scaled=1000,noabund"
        cmd = [
            "sourmash",
            "sketch",
            "dna",
            "--param-string",
            pstring,
            "--output",
            sig_file,
            fasta_file,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result  # returncode: 0 = success, 2 = fail
