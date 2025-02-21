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
        "releasedate": 0,
        "librarysource": 0,
    }
    mongo_df = search_mongodb(headers, rows)
    csv_df = search_csv(headers, rows, column_dict)
    combined_df = pd.DataFrame()
    for column, in_csv in column_dict.items():
        if in_csv == 1 and column in csv_df.columns:
            combined_df[column] = csv_df[column]
        elif in_csv == 0 and column in mongo_df.columns:
            combined_df[column] = mongo_df[column]
        else:
            LOGGER.warning(
                "Metadata column '%s' missing. Returning an empty string.", column
            )
            combined_df[column] = ""
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


def get_numeric_columns_pandas(df):
    return df.select_dtypes(include="number")


def get_branchwater_table(result, max_rows=None):
    """Read in the branchwater search result csv"""
    # These column names are accurate as of branchwater 0.9.5
    # match_name is an SRA identifier when querying the SRA indexes
    data_types = {
        "query_name": "string",
        "query_md5": "string",
        "match_name": "string",
        "containment": "float64",
        "intersect_hashes": "int64",
        "match_md5": "string",
        "jaccard": "float64",
        "max_containment": "float64",
        "query_containment_ani": "float64",
    }
    branchwater_columns_for_output = [
        "query_containment_ani",
        "containment",
    ]
    # LOGGER.info(f"Reading branchwater results file: {result.file.path}")
    branchwater_results = pd.read_csv(
        result.file.path, index_col="match_name", nrows=max_rows, dtype=data_types
    )
    branchwater_subset = branchwater_results[branchwater_columns_for_output]
    LOGGER.info(f"{branchwater_subset}")
    return branchwater_subset


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
        if do_sketching:
            LOGGER.info(f"Calling create_signature with args: {user_id} {name}")
            call_command("create_signature", user_id, name)
        output = io.StringIO()
        LOGGER.info(
            f"Calling create_search with args: user_id={user_id} name={name} False"
        )
        call_command("create_search", user_id, name, "False", stdout=output)
        output.seek(0)
        match = re.search(r"RESULT_PK:\s*(\d+)", output.getvalue())
        result_pk = int(match.group(1)) if match else None
        LOGGER.info(f"Search Result pk: {result_pk}")
        if result_pk:
            fasta.result_pk = result_pk
            fasta.processed = True
            fasta.status = "Complete"
            fasta.save()
        else:
            raise Exception("Search failed.")
    except Exception as e:
        LOGGER.error(f"Error during background processing: {e}")
        fasta.status = f"Error: {e}"
        fasta.save()


def human_sort_key(text):
    return [
        int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", str(text)) if c
    ]


def prettify_column_names(df):
    """Make column names look "nicer"

    1. Replace underscores with spaces.
    2. Convert to capital case

    e.g. 'match_name' -> 'Match Name'

    This won't universally give the perfect results but it should be good enough
    """
    # FIXME: temporarily remove capitalization because some downstream code
    # relies on the column names being exactly as they were before
    # df.columns = [c.replace("_", " ").capitalize() for c in df.columns.to_list()]
    df.columns = [c.replace("_", " ") for c in df.columns.to_list()]
    return df


def add_sra_metadata(branchwater_results):
    branchwater_results.rename_axis("sra_accession", inplace=True)
    sra_columns = [
        "sra_link",
        "assay_type",
        "bioproject",
        "biosample_link",
        "collection_date_sam",
        "geo_loc_name_country_calc",
        "lat_lon",
        "organism",
        "releasedate",
        "librarysource",
    ]
    sra_accessions = branchwater_results.index.to_list()
    sra_metadata = get_sra_fields(sra_accessions, sra_columns)
    results_with_metadata = branchwater_results.join(sra_metadata, on="sra_accession")
    LOGGER.info(f"branchwater_results: {branchwater_results}")
    LOGGER.info(f"sra_metadata: {sra_metadata}")
    LOGGER.info(f"joined: {results_with_metadata}")
    return results_with_metadata


def reorder_result_columns_sra(df):
    output_ordering = [
        "sra_link",
        "assay_type",
        "bioproject",
        "biosample_link",
        "query_containment_ani",
        "collection_date_sam",
        "containment",
        "geo_loc_name_country_calc",
        "lat_lon",
        "organism",
        "releasedate",
        "librarysource",
    ]
    return df[output_ordering]


def get_sra_fields(sra_accessions, fields):
    mongo = pm.MongoClient(settings.MONGO_URI)
    db = mongo["sradb"]
    collection = db["sradb_list"]
    query = {"_id": {"$in": sra_accessions}}
    results = list(collection.find(query))
    if len(results) == 0:
        LOGGER.info(
            "No SRA accessions found in the metadata mongodb. Returning an empty metadata set."
        )
        # Return a dataframe with just the ID column we can't find anything in
        # the mongodb
        empty_df = pd.DataFrame.from_dict({"sra_accession": sra_accessions})
        empty_df.set_index("sra_accession", inplace=True)
        empty_df[fields] = ""
        return empty_df
    elif len(results) < len(sra_accessions):
        LOGGER.info(
            "Not all SRA accessions were found in the mongodb. Returning metadata for {len(results)} samples instead of {len(sra_accessions)}"
        )
    mongo.close()
    sra_metadata = pd.DataFrame(results)
    sra_metadata.set_index("_id", inplace=True)
    sra_metadata.rename_axis("sra_accession", inplace=True)
    missing_columns = set(fields) - set(sra_metadata.columns)
    if len(missing_columns) > 0:
        LOGGER.warning(
            "Not all SRA metadata fields were found in the SRA mongodb. Returning the subset of columns that were found."
        )
        sra_metadata[list(missing_columns)] = ""
    LOGGER.info(f"get_sra_fields: {sra_metadata}")
    return sra_metadata.map(convert_to_string)


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
