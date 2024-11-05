# mgw_api/management/commands/create_metadata.py
import os
import shutil
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

import subprocess
import glob
import pickle
import os
import re
import shutil
import random
import json
import subprocess
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pymongo as pm
import multiprocessing as mp
from datetime import datetime
from datetime import date
import gc

try:
    import multiprocessingPickle4
    import multiprocessing as mp
    ctxx = mp.get_context()
    ctxx.reducer = multiprocessingPickle4.MultiprocessingPickle4()
except:
    import multiprocessing as mp


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--no-download",
            action="store_true",
            help="Do not download latest SRA metadata from S3",
        )
        parser.add_argument(
            "--no-process",
            action="store_true",
            help="Do not process the downloaded SRA data and load it into the mongodb",
        )


    def handle(self, *args, **kwargs):
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        log = f"{dt} - create_metadata - "
        try:
            self.clean_log()
            self.write_log(f"Starting metadata update!")
            re_download = not kwargs["no_download"]
            re_process = not kwargs["no_process"]
            database = "SRA"
            dir_paths = self.handle_dirs(database, ["parquet"])
            column_list, jattr_list = self.get_filter_data()
            if re_download: self.download_parquet(dir_paths["parquet"])
            if re_process:  self.process_parquet(dir_paths["parquet"], column_list, jattr_list)
            self.set_initial_flag()
            self.write_log(f"Downloaded and imported new metadata to {dir_paths['parquet']}.")
            self.stdout.write(self.style.SUCCESS(f"{log}Downloaded and imported new metadata to {dir_paths['parquet']}."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"{log}Error processing metadata update': {e}"))
        gc.collect()

    def handle_dirs(self, database, dir_names):
        dir_paths = {n:os.path.join(settings.DATA_DIR, database, "metadata", n) for n in dir_names}
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o700)
        return dir_paths

    def get_filter_data(self):
        ## data taken from branchwater attrcounts_4.5percent.csv
        column_list = ["sample_name", "sample_name_sam", "acc", "assay_type", "avgspotlen", "bioproject", "biosample", "biosamplemodel_sam", "center_name", "collection_date_sam", "consent", "datastore_filetype", "datastore_provider", "datastore_region", "ena_first_public_run", "ena_last_update_run", "experiment", "geo_loc_name_country_calc", "geo_loc_name_country_continent_calc", "geo_loc_name_sam", "insertsize", "instrument", "library_name", "librarylayout", "libraryselection", "librarysource", "loaddate", "mbases", "mbytes", "organism", "platform", "releasedate", "sample_acc", "sra_study"]
        jattr_list = ["bases", "bytes", "run_file_create_date", "run_file_version", "primary_search", "age", "altitude", "body_habitat", "body_product", "collection_date", "depth", "env_biome", "env_broad_scale", "env_feature", "env_local_scale", "env_material", "env_medium", "env_package", "host", "host_age", "host_body_habitat", "host_body_product", "host_common_name", "host_sex", "host_subject_id", "host_taxid", "investigation_type", "isolate", "lat_lon", "project_name", "race", "sample_type", "source_material_id"]
        return column_list, jattr_list

    def download_parquet(self, parquet_dir):
        self.remove_old_parquet(parquet_dir)
        command = ["aws", "s3", "cp", "--recursive", "s3://sra-pub-metadata-us-east-1/sra/metadata/", parquet_dir, "--no-sign-request"]
        result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = result.communicate()
        if result.returncode == 0:
            self.stdout.write(self.style.SUCCESS("Download metadata succeeded!"))
            self.write_log(f"Download metadata succeeded!")
        else:
            self.stdout.write(self.style.WARNING(f"Download metadata failed with error {stderr}"))
            self.write_log(f"Download metadata failed with error {stderr}!")

    def remove_old_parquet(self, parquet_dir):
        for root, dirs, files in os.walk(parquet_dir):
            for file in files:
                os.remove(os.path.join(root, file))

    def process_parquet(self, parquet_dir, column_list, jattr_list):
        self.clean_mongo("sradb_temp")
        self.write_log(f"Cleaned mongodb sradb_temp")
        cpus = min(1, int(mp.cpu_count()*0.8))
        self.write_log(f"Using {cpus} cores")
        for file in os.listdir(parquet_dir):
            self.write_log(f"Processing parquet file {file}")
            self.add_to_mongo(parquet_dir, file, column_list, jattr_list)
            gc.collect()
        self.clean_mongo("sradb_list")
        self.write_log(f"Cleaned mongodb sradb_list")
        self.finish_mongo()

    def clean_mongo(self, collection):
        mongo = pm.MongoClient(settings.MONGO_URI)
        db = mongo["sradb"]
        if collection in db.list_collection_names(): db[collection].drop()
        mongo.close()

    def add_to_mongo(self, parquet_dir_path, file, column_list, jattr_list):
        pf = pq.ParquetFile(os.path.join(parquet_dir_path, file))
        cpus = max(1, int(mp.cpu_count()*0.8))
        # Default batch size for iter_batches() is 64k records
        for data in pf.iter_batches(columns = column_list + ["jattr"]):
            df = data.to_pandas()
            res_list = self.multi_parsing(df.to_dict(orient='records'), self.process_row, cpus, *[column_list, jattr_list], shuffle=False)
            mongo = pm.MongoClient(settings.MONGO_URI)
            db = mongo["sradb"]
            for meta_list in res_list:
                db["sradb_temp"].insert_many(meta_list)
            mongo.close()

    def finish_mongo(self):
        mongo = pm.MongoClient(settings.MONGO_URI)
        db = mongo["sradb"]
        db["sradb_temp"].rename("sradb_list")
        collection_stats = db.command("collstats", "sradb_list")
        acc_count, total_size, avg_doc_size = collection_stats["count"], collection_stats["size"], collection_stats["avgObjSize"]
        self.write_log(f"{acc_count} acc documents imported to mongoDB collection")
        self.write_log(f"MongoDB size is {total_size} bytes, average document size is {avg_doc_size} bytes")
        self.stdout.write(self.style.SUCCESS(f"{acc_count} acc documents imported to mongoDB collection"))
        self.stdout.write(self.style.SUCCESS(f"MongoDB size is {total_size} bytes, average document size is {avg_doc_size} bytes"))
        mongo.close()

    def multi_parsing(self, data_list, parseFunction, threads, *argv, shuffle=True):
        ## shared data
        total, res_map, res_list = len(data_list), list(), mp.Manager().list()
        split, rest = max(total//threads,1), total%threads
        if threads > 1 and threads > total:
            in_split = [(s,s+1) for s in range(0,total)]
        elif threads > 1:
            in_split = [(s+1*i, s+split+1*(i+1)) if i < rest else (s+rest, s+split+rest) for i,s in enumerate(range(0,total-rest,split))]
        else:
            in_split = [(0,total)]
        if shuffle: random.shuffle(data_list)
        for run,(i,j) in enumerate(in_split,1):
            p = mp.Process(target=parseFunction, args=(data_list[i:j], run, split, res_list, *argv))
            res_map.append(p)
            p.start()
        for res in res_map:
            res.join()
        return res_list

    def process_row(self, attr_list, run, split, res_list, column_list, jattr_list):
        new_attr = list()
        for it,attr_dict in enumerate(attr_list):
            #if int(it*10000/split) % 10 == 0 and int(it*100/split) != 0:
            #    self.stdout.write(self.style.SUCCESS(f"Processing {run:>2d} ... {it*100/split:>4.1f} %             ", end="\r"))
            column_dict = {c:attr_dict[c] for c in column_list}
            jattr_dict = self.process_jattr(attr_dict["jattr"], jattr_list)
            meta_dict = {**column_dict, **jattr_dict}
            meta_dict = {k: self.process_value(v) for k, v in meta_dict.items()}
            meta_dict['biosample_link'] = f"https://www.ncbi.nlm.nih.gov/biosample/{meta_dict.get('biosample', '')}"
            meta_dict['sra_link'] = f"https://www.ncbi.nlm.nih.gov/sra/{meta_dict.get('acc', '')}"
            meta_dict['_id'] = meta_dict['acc']
            new_attr.append(meta_dict)
        res_list.append(new_attr)

    def process_value(self, v):
        if   isinstance(v, list)       and not len(v): return 'NP'
        if   isinstance(v, list)                     : return v
        elif isinstance(v, np.ndarray) and not len(v): return 'NP'
        elif isinstance(v, np.ndarray):                return v.tolist()
        elif isinstance(v, float) and v.is_integer():  return int(v)
        elif isinstance(v, date):                      return str(v)
        elif pd.isna(v):                               return 'NP'
        else:                                          return v

    def process_jattr(self, jattr_str, jattr_list):
        jattr_dict = json.loads(jattr_str)
        cleaned_dict = {re.sub(r"_sam_s_dpl34|_sam", "", k): v for k,v in jattr_dict.items()}
        lalo = cleaned_dict.get("lat_lon", "NP")
        NS, EW = {"N":1, "S":-1}, {"W":-1, "E":1}
        match = re.search(r"(\d+(\.\d+)?) ([NS]) (\d+(\.\d+)?) ([EW])", lalo)
        if match:
            lat = float(match.group(1)) * NS.get(match.group(3), 1)
            lon = float(match.group(4)) * EW.get(match.group(6), 1)
            cleaned_dict["lat_lon"] = [lat, lon]
        else:
            cleaned_dict["lat_lon"] = "NP"
        extracted_values = {key: cleaned_dict.get(key, "NP") for key in jattr_list}
        return extracted_values

    def clean_log(self):
        logfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log_metadata.log")
        with open(logfile, "w") as logf:
            logf.write(f"")

    def write_log(self, message):
        logfile = os.path.join(os.path.dirname(os.path.abspath(__file__)), "log_metadata.log")
        now = datetime.now()
        dt = now.strftime("%d.%m.%Y %H:%M:%S")
        with open(logfile, "a") as logf:
            logf.write(f"{dt} - Status: {message}\n")

    def set_initial_flag(self):
        init_flag = os.path.join(settings.DATA_DIR, "SRA", "metadata", "initial_setup.txt")
        with open(init_flag, "w") as initf:
            initf.write(f"")

