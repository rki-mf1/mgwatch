import os
from datetime import datetime

from django.conf import settings

from mgw.settings import LOGGER
from mgw_api.models import Fasta
from mgw_api.models import Signature

from .processes import run_command


def create_signature(*, user_id, name):
    fasta = Fasta.objects.get(user_id=user_id, name=name, processed=False)
    LOGGER.info("Creating a signature for %s.", fasta.name)
    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    user_path = os.path.dirname(fasta.file.path)
    signature_file = os.path.join(user_path, f"signature_{fasta.name}.{date}.sig")
    pstring = "k=21,k=31,k=51,scaled=1000,noabund"
    run_command(
        [
            "sourmash",
            "sketch",
            "dna",
            "--param-string",
            pstring,
            "--output",
            signature_file,
            fasta.file.path,
        ]
    )
    relative_path = os.path.relpath(signature_file, settings.MEDIA_ROOT)
    signature_model = Signature(user=fasta.user, fasta=fasta, name=fasta.name)
    signature_model.file.name = relative_path
    signature_model.size = signature_model.file.size
    signature_model.submitted = True
    signature_model.save()
    fasta.processed = True
    fasta.file.delete()
    fasta.save(update_fields=["processed"])
    LOGGER.info("Successfully processed file '%s'", fasta.name)
    return signature_model
