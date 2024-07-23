# mgw_api/functions.py

import time  # Simulate a time-consuming task
from .models import Fasta

import csv

def process_pending_files():
    pending_files = Fasta.objects.filter(processed=False)
    for fasta in pending_files:
        # Simulate file processing
        time.sleep(20)  # test
        fasta.processed = True
        fasta.save()

def get_table_data(result):
    table_data = []
    with open(result.file.path, newline="") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            table_data.append(row)
    return table_data[0], table_data[1:]

def get_numeric_columns(rows):
    all_columns, string_columns, not_empty = set(), set(), set()
    for row in rows:
        for index, value in enumerate(row):
            all_columns.add(index)
            if value: not_empty.add(index)
            try:
                float(value)
            except ValueError:
                if value: string_columns.add(index)
    return not_empty.intersection(all_columns - string_columns)
