# mgw_api/functions.py

import time  # Simulate a time-consuming task
from .models import Fasta, Settings, Signature
from .forms import SettingsForm
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
import subprocess
from django.core.management import call_command
from .management.commands.return_command import CommandWithReturnValue



import csv
import re
import sys
import os
import io


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

def run_create_signature_and_search(user_id, name, fasta_id, do_sketching):
    try:
        fasta = Fasta.objects.get(id=fasta_id)
        print(f"WTF: {fasta_id}")
        if do_sketching: call_command('create_signature', user_id, name)
        output = io.StringIO()
        call_command('create_search', user_id, name, "False", stdout=output)
        output.seek(0)
        match = re.search(r'RESULT_PK:\s*(\d+)', output.getvalue())
        result_pk = int(match.group(1)) if match else None
        print(f"WTF: {result_pk}")
        if result_pk:
            fasta.result_pk = result_pk
            fasta.processed = True
            fasta.status = "Complete"
            fasta.save()
    except Exception as e:
        print(f"Error during background processing: {e}")
        fasta.status = f"Error: {e}"
        fasta.save()

def human_sort_key(text):
    return [int(c) if c.isdigit() else c.lower() for c in re.split('\\d+)', str(text))]