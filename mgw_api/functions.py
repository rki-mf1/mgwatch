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
import pymongo as pm
import pandas as pd




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
        print(f"TEST fasta id: {fasta_id}")
        if do_sketching: call_command('create_signature', user_id, name)
        output = io.StringIO()
        call_command('create_search', user_id, name, "False", stdout=output)
        output.seek(0)
        match = re.search(r'RESULT_PK:\s*(\d+)', output.getvalue())
        result_pk = int(match.group(1)) if match else None
        print(f"TEST result pk: {result_pk}")
        if result_pk:
            fasta.result_pk = result_pk
            fasta.processed = True
            fasta.status = "Complete"
            fasta.save()
        else:
            raise Exception(f"Search failed, result_pk is empty!")
    except Exception as e:
        print(f"Error during background processing: {e}")
        fasta.status = f"Error: {e}"
        fasta.save()

def human_sort_key(text):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(text)) if c]

def get_metadata(headers, rows):
    column_dict = {"acc":0, "assay_type":0, "bioproject":0, "sra_link":0, "biosample_link":0, "query_containment_ani":1, "collection_date_sam":0, "containment":1, "geo_loc_name_country_calc":0, "lat_lon":0, "organism":0, "k-mer":1, "database":1, "containment_threshold":1}
    mongo_df = search_mongodb(headers, rows)
    csv_df = search_csv(headers, rows, column_dict)
    combined_df = pd.DataFrame()
    for column, in_csv in column_dict.items():
        if in_csv:
            combined_df[column] = csv_df[column]
        else:
            combined_df[column] = mongo_df[column]
    new_headers = combined_df.columns.tolist()
    new_rows = combined_df.values.tolist()
    return new_headers, new_rows

def search_mongodb(headers, rows):
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    collection = db["sradb_list"]
    qidx = headers.index("match_name")
    query = {"_id": {"$in": [row[qidx] for row in rows]}}
    mongo_df = pd.DataFrame(list(collection.find(query)))
    mongo.close()
    return mongo_df.map(convert_to_string)

def convert_to_string(value):
    if isinstance(value, list):
        return ', '.join(map(str, value))
    return str(value)

def search_csv(headers, rows, column_dict):
    qidx = [headers.index(d_head) for d_head, in_csv in column_dict.items() if in_csv]
    csv_df = pd.DataFrame(rows)
    csv_df = csv_df.iloc[:, qidx]
    csv_df.columns = [headers[i] for i in csv_df.columns]
    return csv_df
