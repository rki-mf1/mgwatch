# mgw_api/functions.py

import time  # Simulate a time-consuming task
from .models import Fasta

def process_pending_files():
    pending_files = Fasta.objects.filter(processed=False)
    for fasta in pending_files:
        # Simulate file processing
        time.sleep(20)  # test
        fasta.processed = True
        fasta.save()
