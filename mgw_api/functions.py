# mgw_api/functions.py

import time  # Simulate a time-consuming task
from .models import Fasta, Settings
from .forms import SettingsForm
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
import subprocess

import csv
import re
import sys
import os

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

def apply_regex(rows, column, value):
    try:
        regex = re.compile(fr"{value}", re.IGNORECASE)
        return [row for row in rows if regex.search(row[int(column)])]
    except:
        return rows

def is_float(value):
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False
    
def apply_compare(modifier, rows, column, value):
    try:
        if modifier * float(rows[int(column)]) >= modifier * float(value): return True
        else: return False
    except (ValueError, TypeError):
        return True

def run_create_signature_and_search(user_id, name, fasta_id):
    try:
        manage_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'manage.py')
        fasta = Fasta.objects.get(id=fasta_id)
        subprocess.run([sys.executable, manage_py_path, "create_signature", str(user_id), name], check=True)
        result = subprocess.run([sys.executable, manage_py_path, "create_search", str(user_id), name], capture_output=True, text=True, check=True)
        print(result)
        result_pks = []
        for line in result.stdout.split('\n'):
            if line.startswith("Result PKs:"):
                result_pks = line.split(':')[1].strip().strip('[]').split(', ')
        if result_pks:
            result_pk = int(result_pks[0])
            fasta.result_pk = result_pk
            fasta.processed = True
            fasta.status = "Complete"
            fasta.save()
    except subprocess.CalledProcessError as e:
        print(f"Error during background processing: {e}")
        fasta.status = f"Error: {e}"
        fasta.save()
