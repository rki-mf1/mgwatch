# mgw_api/functions.py

import csv
import io
import re

import pandas as pd
import pymongo as pm
from django.conf import settings
from django.core.management import call_command

from mgw.settings import LOGGER

from .models import Fasta


def get_table_data(result, max_rows=None):
    table_data = []
    with open(result.file.path, newline="") as csvfile:
        reader = csv.reader(csvfile)
        # The first row is a header, we don't count it
        n_rows = -1
        for row in reader:
            table_data.append(row)
            n_rows += 1
            if max_rows and n_rows >= max_rows:
                break
    return table_data[0], table_data[1:]


def get_numeric_columns(rows):
    all_columns, string_columns, not_empty = set(), set(), set()
    for row in rows:
        for index, value in enumerate(row):
            all_columns.add(index)
            if value:
                not_empty.add(index)
            try:
                float(value)
            except ValueError:
                if value:
                    string_columns.add(index)
    return not_empty.intersection(all_columns - string_columns)


def apply_regex(rows, column, value):
    try:
        regex = re.compile(rf"{value}", re.IGNORECASE)
        return [row for row in rows if regex.search(row[int(column)])]
    except Exception:
        return rows


def is_float(value):
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def apply_compare(modifier, rows, column, value):
    try:
        if modifier * float(rows[int(column)]) >= modifier * float(value):
            return True
        else:
            return False
    except (ValueError, TypeError):
        return True


def run_create_signature_and_search(user_id, name, fasta_id, do_sketching):
    try:
        fasta = Fasta.objects.get(id=fasta_id)
        LOGGER.info(f"TEST fasta id: {fasta_id}")
        if do_sketching:
            call_command("create_signature", user_id, name)
        output = io.StringIO()
        call_command("create_search", user_id, name, "False", stdout=output)
        output.seek(0)
        match = re.search(r"RESULT_PK:\s*(\d+)", output.getvalue())
        result_pk = int(match.group(1)) if match else None
        LOGGER.info(f"TEST result pk: {result_pk}")
        if result_pk:
            fasta.result_pk = result_pk
            fasta.processed = True
            fasta.status = "Complete"
            fasta.save()
        else:
            raise Exception("Search failed, result_pk is empty!")
    except Exception as e:
        LOGGER.error(f"Error during background processing: {e}")
        fasta.status = f"Error: {e}"
        fasta.save()


def human_sort_key(text):
    return [
        int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", str(text)) if c
    ]


def get_metadata(headers, rows):
    # 0 = in the SRA mongodb database
    # 1 = in the search result csv file
    column_dict = {
        "sra_link": 0,
        "assay_type": 0,
        "bioproject": 0,
        "biosample_link": 0,
        "query_containment_ani": 1,
        "collection_date_sam": 0,
        "containment": 1,
        "geo_loc_name_country_calc": 0,
        "lat_lon": 0,
        "organism": 0,
        "containment_threshold": 1,
        "releasedate": 0,
        "librarysource": 0,
    }
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
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    collection = db["sradb_list"]
    qidx = headers.index("match_name")
    query = {"_id": {"$in": [row[qidx] for row in rows]}}
    mongo_df = pd.DataFrame(list(collection.find(query)))
    mongo.close()
    return mongo_df.map(convert_to_string)


def convert_to_string(value):
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return str(value)


def search_csv(headers, rows, column_dict):
    qidx = [headers.index(d_head) for d_head, in_csv in column_dict.items() if in_csv]
    csv_df = pd.DataFrame(rows)
    csv_df = csv_df.iloc[:, qidx]
    csv_df.columns = [headers[i] for i in csv_df.columns]
    return csv_df
