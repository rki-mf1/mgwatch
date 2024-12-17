# mgw_api/management/commands/create_downloads.py

from django.core.management.base import BaseCommand, CommandError
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings

from mgw.settings import LOGGER

import os
import shutil
import subprocess
import json
import hashlib
import re
import multiprocessing as mp
from functools import partial
import datetime


import pickle
import resource

import sys
import os 
import re
import time
import pickle
import random

import glob
import pymongo as pm
from datetime import datetime

################################################################################
## django command class
################################################################################

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        try:
            kmers = [21, 31, 51]
            database = "SRA"
            start_date, end_date = "2023-09-27", "2023-09-27"
            lib_source_list = ["METAGENOMIC"]
            download_attempts = 1
            #["\n\t\t\t\tGENOMIC\n\t\t\t", "GENOMIC", "GENOMIC SINGLE CELL", "METAGENOMIC", "METATRANSCRIPTOMIC", "OTHER", "SYNTHETIC", "TRANSCRIPTOMIC", "TRANSCRIPTOMIC SINGLE CELL", "VIRAL RNA"]
            manifest = os.path.join(settings.DATA_DIR, database, "metagenomes", f"manifest.pcl")
            man_succ = os.path.join(settings.DATA_DIR, database, "metagenomes", f"update_successful.pcl")
            man_fail = os.path.join(settings.DATA_DIR, database, "metagenomes", f"update_failed.pcl")
            dir_paths = self.handle_dirs(database, ["updates", "index", "signatures", "failed", "manifests"])
            mani_list = self.get_manifest(manifest)
            if not mani_list and not settings.INDEX_FROM_SCRATCH:
                LOGGER.error(f"There is no index available and creating one from scratch is disabled.")
                raise Exception(f"There is no index available and creating one from scratch is disabled.")
            sig_list, last_num = self.get_last_index(dir_paths)
            print(f"index IDs: {len(mani_list)}")
            print(f"index-{last_num} IDs: {sig_list}")
            mongo_IDs = self.get_mongoIDs(start_date, end_date, lib_source_list)
            print(f"mongo IDs: {len(mongo_IDs)}")
            mani_set, mongo_set = set(mani_list), set(mongo_IDs)
            missing_IDs = mongo_set - mani_set
            print(f"missing IDs: {len(missing_IDs)}")
            LOGGER.info("Running SRA downloads ...")
            successful_downloads, failed_downloads = self.download_from_wort(dir_paths, missing_IDs, download_attempts)
            self.save_pickle(man_succ, successful_downloads)
            self.save_pickle(man_fail, failed_downloads)
            LOGGER.info(f"Creating downloads finished.")
        except Exception as e:
            LOGGER.error(f"Error downloading signatures '{settings.DATA_DIR}': {e}")

    def handle_dirs(self, database, dir_names):
        dir_paths = {n:os.path.join(settings.DATA_DIR, database, "metagenomes", n) for n in dir_names}
        for dir_path in dir_paths.values():
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
                os.chmod(dir_path, 0o700)
        return dir_paths

    def get_manifest(self, manifest):
        LOGGER.info(f"Reading manifest file for signature update.")
        with open(manifest, "rb") as pcl_in:
            mani_list = pickle.load(pcl_in)
        return mani_list
    
    def get_last_index(self, dir_paths):
        LOGGER.info(f"Getting last index number and content.")
        last_num = max([int(os.path.basename(f).split("db")[1].split(".pcl")[0]) for f in glob.glob(os.path.join(dir_paths["manifests"], "wort-sra-kmer-db*.pcl"))])
        last_sigs = os.path.join(dir_paths["manifests"], f"wort-sra-kmer-db{last_num}.pcl")
        with open(last_sigs, "rb") as pcl_in:
            sig_list = pickle.load(pcl_in)
        return sig_list, last_num
    
    def get_mongoIDs(self, start_date, end_date, lib_source_list):
        #LOGGER.info(f"Getting current SRA IDs from MongoDB.")
        mongo = pm.MongoClient(settings.MONGO_URI)
        #mongo = pm.MongoClient("mongodb://localhost:27017/")
        db = mongo["sradb"]
        collection = db["sradb_list"]
        # oldest date: 2007-06-05 newest date: 2024-11-13
        # start_date = "2023-09-26" mongo IDs: 104099 shared IDs: 1795
        # start_date = "2023-09-27" mongo IDs: 95092  shared IDs: 54
        # start_date = "2023-09-28" mongo IDs: 67608  shared IDs: 0
        #ids = collection.find({"librarysource": mID}, {"_id": 1})
        #ids = collection.find({}, {"_id": 1})
        #start_date = "2007-06-05"
        #end_date = "2023-09-26"
        query = {"releasedate": {"$gte": start_date, "$lte": end_date}, "librarysource": {"$in": lib_source_list}}
        ids = collection.find(query, {"_id": 1})
        mongo_IDs = [doc["_id"] for doc in ids]
        mongo.close()
        return mongo_IDs
    
    def download_from_wort(self, dir_paths, SRA_IDs, download_attempts):
        successful_downloads = []
        failed_downloads = []
        slen = len(SRA_IDs)
        for i,SRA_ID in enumerate(SRA_IDs):
            LOGGER.info(f"... {i} of {slen} ID {SRA_ID} ...")
            attempts, success = 0, False
            while attempts < download_attempts and not success:
                success = self.call_curl_download(dir_paths, SRA_ID)
                if not success:
                    attempts += 1
                    time.sleep(1)
            if success:
                successful_downloads.append(SRA_ID)
            else:
                failed_downloads.append(SRA_ID)
        print("Successful downloads:", successful_downloads)
        print("Failed downloads:", failed_downloads)
        return successful_downloads, failed_downloads

    def call_curl_download(self, dir_paths, SRA_ID):
        url = f"https://wort.sourmash.bio/v1/view/sra/{SRA_ID}"
        output_file = os.path.join(dir_paths["updates"], f"{SRA_ID}.sig")
        cmd = ["curl", "-JLf", url, "-o", output_file]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
            else:
                print(f"Failed to download {SRA_ID}: Exit code {result.returncode}")
                return False
        except Exception as e:
            print(f"Error occurred while downloading {SRA_ID}: {e}")
            return False

    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)




    def search_index(self, result_file, sketch_file, index_path, k, containment):
        cpus = min(8, int(mp.cpu_count()*0.8))
        cmd = ["sourmash", "scripts", "manysearch", "--ksize", f"{k}", "--moltype", "DNA", "--scaled", "1000", "--cores", f"{cpus}", "--threshold", f"{containment}", "--output", result_file, sketch_file, index_path]
        LOGGER.debug(f"Running commands: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result # returncode: 0 = success, 2 = fail




















    def create_initial_manifests(self, manifest, dir_paths, sig_list):
        manifest_IDs, index_paths, index_lists = list(), os.listdir(dir_paths["index"]), os.listdir(dir_paths["lists"])
        if os.path.exists(manifest):
            LOGGER.info("Manifest found, reading ...")
            with open(manifest, "rb") as pcl_in:
                manifest_IDs = pickle.load(pcl_in)
        if not manifest_IDs and not index_paths:
            LOGGER.info("No index and no manifest, creating empty manifest ...")
            self.save_pickle([], manifest)
        if not manifest_IDs and index_paths:
            LOGGER.info("Index found, but no manifest, creating manifest ...")
            if len(index_paths) != len(index_lists):
                raise Exception(f"The number of indices and index lists are not the same.")
            index_lists = sorted(index_lists, key=lambda x: self.extract_number(x))
            manifest_dict = dict()
            for index_list in index_lists:
                with open(os.path.join(dir_paths["lists"], index_list), "r") as list_in:
                    i = self.extract_number(index_list)
                    ID_list = [os.path.splitext(os.path.split(line.strip())[1])[0] for line in list_in]
                    manifest_dict[i] = ID_list
            LOGGER.info(f"Extracted SRA IDs from index list files, found {len(manifest_dict)} list files beloning to indices.")
            SRA_IDs = [v for val in manifest_dict.values() for v in val]
            LOGGER.info(f"Saving manifest with {len(SRA_IDs)} SRA IDs.")
            self.save_pickle(SRA_IDs, manifest)
            for i,IDs in manifest_dict.items():
                print(IDs[:10])
                self.save_pickle(IDs, os.path.join(dir_paths["manifests"], f"wort-sra-21-db{i}.pcl"))
            LOGGER.info(f"Finished, creating new starting manifest {len(manifest_dict)} for further updates.")
            self.save_pickle([], os.path.join(dir_paths["manifests"], f"wort-sra-21-db{len(manifest_dict)}.pcl"))
    
    def save_pickle(self, data, file):
        with open(file, "wb") as outpcl:
            pickle.dump(data, outpcl, protocol=4)

    def extract_number(self, s):
        return int(re.search(r'\d+', s).group())




















def main():
    ############################################################################
    ## get metadata dir
    # mamba install bioconda::sra-tools=3.1.1
    # prefetch SRR12345678 --output-directory
    # fastq-dump --split-files /path/to/SRR12345678.sra --gzip --outdir <dir>
    # --clip Removes adapter sequences and low-quality tails based on quality scores.
    # LOGGER.info
    ############################################################################
    print("Status: Create initial manifests.")
    kmers = [21, 31, 51]
    database = "SRA"
    sig_list = os.path.join(DATA_DIR, database, "metagenomes", f"sig-list.txt")
    manifest = os.path.join(DATA_DIR, database, "metagenomes", f"manifest.pcl")
    dir_paths = handle_dirs(database, ["updates", "index", "signatures", "failed"])
    sig_files = get_manifest(manifest, dir_paths)
    

    bw_sra_sigs, manifest, mani_path, wort_path = get_paths()
    print(f"bw_sra_sigs = {bw_sra_sigs}")
    print(f"manifest = {manifest}")
    print(f"mani_path = {mani_path}")
    print(f"wort_path = {wort_path}")
    search_mongodb()
    create_initial_manifest(bw_sra_sigs, manifest, mani_path)
    #if not os.path.exists(manifest):
    #
    #for i in range(38):
    #    sig_file = os.path.join(sig_path, f"sigs-sra-{i}.txt")
    #    man_file = os.path.join(man_path, f"wort-sra-21-db{i}.pcl")
    #    with open(sig_file, "r") as sigf:
    #        SRA_IDs = [os.path.splitext(os.path.basename(line.strip()))[0] for line in sigf]
    #    with open(man_file, "wb") as manf:
    #        pickle.dump(SRA_IDs, manf , protocol=4)

    exit()


    # wort-sra-21-db0.rocksdb
    # sigs-sra-0.txt
    # sigs-sra-db0.pcl
    # curl -JLf https://wort.sourmash.bio/v1/view/sra/{params.sraid} -o {output}
    #curl -JLf https://wort.sourmash.bio/v1/view/sra/SRA10728684 -o SRA10728684
    #curl -JLf https://wort.sourmash.bio/v1/view/sra/ERR2683278 -o ERR2683278
    # mamba install bioconda::sra-tools=3.1.1
    # sigs-sra.txt


    # 1.
    # sigs-sra.txt -> manifest.pcl
    #with open("sigs-sra.txt", "r") as sigin:
        
    # 2. get current mogno db list
    
    #def search_mongodb2(headers, rows):
    #    #mongo = pm.MongoClient(settings.MONGO_URI)
    #    mongo = pm.MongoClient("mongodb://localhost:27017/")
    #    db = mongo["sradb"]
    #    collection = db["sradb_list"]
    #    ids = collection.find({}, {"_id": 1})
    #    id_list = [doc["_id"] for doc in ids]
#
    #    qidx = headers.index("match_name")
    #    query = {"_id": {"$in": [row[qidx] for row in rows]}}
    #    mongo_df = pd.DataFrame(list(collection.find(query)))
    #    mongo.close()
    #    return mongo_df.map(convert_to_string)
    # 3.
    # compare manifest with current mongodb list
    # 4.
    # test if ID is available in wort
    # 5. download if ID is available in wort
    # 6. save downloaded IDs to new_ids.pcl
    # 7. add IDs to current 100k list
    # 8. recreate current 100k list with new IDs till at 100k
    # 9. create new 100k list id
        # 10. repeat and save current 100k ids.
        # 11. save everyting to manifest.pcl (master comparison list)
        # 12. run index creation with all 100k id lists (batch index)



    #
    sig_files = get_manifest(manifest)
    print(sig_files)


    sig_files = [file for file in new_files if os.path.basename(file) in sig_files]
    #sig_files = glob.glob(os.path.join(sig_path, "*.txt"))
    #dir_path, SRA_file = get_paths("sigs-sra.txt")
    #sig_dict = read_sigs(SRA_file)
    #sig_dict_list = split_dict(sig_dict, 100000)
    #write_sigs(sig_dict_list, dir_path)





################################################################################
## functions
################################################################################

def get_paths():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    bw_sra_sigs = os.path.join(dir_path, f"sigs-sra.txt")
    manifest = os.path.join(dir_path, f"manifest.pcl")
    mani_path = os.path.join(dir_path, f"mans-sra")
    wort_path = os.path.join(dir_path, f"wort-sra")
    return bw_sra_sigs, manifest, mani_path, wort_path

def create_initial_manifest(bw_sra_sigs, manifest, mani_path):
    i = 0
    with open(bw_sra_sigs, "r") as bwsigs:
        SRA_IDs = [os.path.splitext(os.path.basename(line.strip()))[0] for line in bwsigs]
        print(SRA_IDs[:20])
        print(len(SRA_IDs))
    with open(manifest, "wb") as manf:
        pickle.dump(SRA_IDs, manf , protocol=4)
    for i,IDs in enumerate([SRA_IDs[i:i + 100000] for i in range(0, len(SRA_IDs), 100000)]):
        man_file = os.path.join(mani_path, f"wort-sra-21-db{i}.pcl")
        with open(manifest, "wb") as manf:
            pickle.dump(IDs, man_file , protocol=4)

def get_manifest(manifest):
    with open(manifest, "rb") as pcl_in:
        mani_list = pickle.load(pcl_in)
    return mani_list

def get_last_index(mani_path):
    last_num = max([int(os.path.basename(f).split("db")[1].split(".pcl")[0]) for f in glob.glob(os.path.join(mani_path, "wort-sra-21-db*.pcl"))])
    print(last_sigs)
    last_sigs = os.path.join(mani_path, f"wort-sra-21-db{last_num}.pcl")
    with open(last_sigs, "rb") as pcl_in:
        sig_list = pickle.load(pcl_in)
    return sig_list, last_num

def search_mongodb():
    #mongo = pm.MongoClient(settings.MONGO_URI)
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    collection = db["sradb_list"]
    ids = collection.find_one({"_id": "SRR6953603"})
    print(ids)
    exit()
    ids = collection.find({}, {"_id": 1})
    mongo_list = [doc["_id"] for doc in ids[:20]] # TODO: remove limit
    print(mongo_list)
    mongo.close()
    return mongo_list

def get_missing_sigs(mani_list, mongo_list, sig_list, last_num):
    
    pass




















#{'_id': ObjectId('66c7097f87350905c263b2cd'), 'sample_name': 'HG02132', 'sample_name_sam': 'NP', 'acc': 'SRR29483254', 'assay_type': 'WGS', 'avgspotlen': 19635, 'bioproject': 'PRJNA701308', 'biosample': 'SAMN26267382', 'biosamplemodel_sam': ['Human'], 'center_name': 'UCSC GI', 'collection_date_sam': 'NP', 'consent': 'public', 'datastore_filetype': ['bam', 'sra'], 'datastore_provider': ['gs', 's3', 'ncbi'], 'datastore_region': ['gs.us-east1', 's3.us-east-1', 'ncbi.public'], 'ena_first_public_run': 'NP', 'ena_last_update_run': 'NP', 'experiment': 'SRX24993949', 'geo_loc_name_country_calc': 'NP', 'geo_loc_name_country_continent_calc': 'NP', 'geo_loc_name_sam': 'NP', 'insertsize': 'NP', 'instrument': 'Revio', 'library_name': 'HG02132.HFSSc_m84046_230603_204152_s4', 'librarylayout': 'SINGLE', 'libraryselection': 'size fractionation', 'librarysource': 'GENOMIC', 'loaddate': 'NaT', 'mbases': 67412, 'mbytes': 26276, 'organism': 'Homo sapiens', 'platform': 'PACBIO_SMRT', 'releasedate': '2024-06-21', 'sample_acc': 'SRS12122870', 'sra_study': 'SRP305758', 'bases': 67412093607, 'bytes': 27552540979, 'run_file_create_date': '2024-06-21T06:09:00.000Z', 'run_file_version': 'NP', 'primary_search': '26267382', 'age': ['No Data'], 'altitude': 'NP', 'body_habitat': 'NP', 'body_product': 'NP', 'collection_date': 'NP', 'depth': 'NP', 'env_biome': 'NP', 'env_broad_scale': 'NP', 'env_feature': 'NP', 'env_local_scale': 'NP', 'env_material': 'NP', 'env_medium': 'NP', 'env_package': 'NP', 'host': 'NP', 'host_age': 'NP', 'host_body_habitat': 'NP', 'host_body_product': 'NP', 'host_common_name': 'NP', 'host_sex': 'NP', 'host_subject_id': 'NP', 'host_taxid': 'NP', 'investigation_type': 'NP', 'isolate': 'NP', 'lat_lon': 'NP', 'project_name': 'NP', 'race': 'NP', 'sample_type': 'NP', 'source_material_id': 'NP', 'biosample_link': 'https://www.ncbi.nlm.nih.gov/biosample/SAMN26267382', 'sra_link': 'https://www.ncbi.nlm.nih.gov/sra/SRR29483254'}

def update_manifest(self, new_files, sig_files, manifest):
    new_files = [os.path.basename(file) for file in new_files]
    sig_files = sig_files + new_files
    with open(manifest, "wb") as pcl_out:
        pickle.dump(sig_files, pcl_out , protocol=4)

def get_manifest(manifest):
    #if not os.path.exists(manifest):
    #    sig_files = [os.path.basename(f) for f in glob.glob(os.path.join(dir_paths["signatures"], "*.sig.gz"))]
    #    with open(manifest, "wb") as pcl_out:
    #        pickle.dump(sig_files, pcl_out , protocol=4)
    #else:
    with open(manifest, "rb") as pcl_in:
        sig_files = pickle.load(pcl_in)
    return sig_files


def write_sigs(sig_dict_list, dir_path):
    for j,sig_dict in enumerate(sig_dict_list):
        with open(os.path.join(dir_path, f"sigs-sra-{j}.txt"), "w") as sra_out:
            for i,(sig, path) in enumerate(sig_dict.items()):
                sra_out.write(f"{path}/{sig}.sig\n")


def read_sigs(SRA_file):
    sig_dict = dict()
    with open(SRA_file, "r") as sra_in:
        for i,line in enumerate(sra_in):
            print(f"Status: line {i}", end="\r")
            path, sra = os.path.split(line.strip())
            sig, ext = os.path.splitext(sra)
            sig_dict[sig] = path
            #if i >= 1000: break
        sorted_dict = dict(sorted(sig_dict.items(), key=lambda x: extract_number(x[0])))
    return sorted_dict


def extract_number(s):
    return int(re.search(r'\d+', s).group())

def split_dict(sig_dict, chunk_size):
    sig_dict_list, current_dict = list(), dict()
    for i, (k, v) in enumerate(sig_dict.items()):
        current_dict[k] = v
        if (i + 1) % chunk_size == 0:
            sig_dict_list.append(current_dict)
            current_dict = dict()
    if current_dict:
        sig_dict_list.append(current_dict)
    return sig_dict_list





























def get_meta_dir(dir_name):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    filter_file = os.path.join(dir_path, 'attrcounts_4.5percent.csv')
    parquet_dir_path = os.path.join(dir_path, dir_name)
    return parquet_dir_path, filter_file


def download_parquet_files(parquet_dir_path):
    if os.path.exists(parquet_dir_path):
        shutil.rmtree(parquet_dir_path)
    os.makedirs(parquet_dir_path)
    command = ["aws", "s3", "cp", "--recursive", "s3://sra-pub-metadata-us-east-1/sra/metadata/", parquet_dir_path, "--no-sign-request"]
    result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in result.stdout:
        print(f"{line.strip()}\033[K", end="\r")
    captured_errors = list()
    for line in result.stderr:
        captured_errors.append(line)
    result.wait()
    if result.returncode == 0:
        print("Status: Download metadata succeeded!\033[K")
    else:
        print(f"Status: Download metadata failed with error: {result.stderr}\033[K")


def process_parquet_files(parquet_dir_path, filter_file):
    filt_df = pd.read_csv(filter_file)
    column_list = list(filt_df.loc[filt_df['in_jattr'] != 1, 'HarmonizedName'])
    jattr_list = list(filt_df.loc[filt_df['in_jattr'] == 1, 'HarmonizedName'])
    clean_mongo("sradb_temp")
    for i, file in enumerate(os.listdir(parquet_dir_path)):
        if not i: print(f"Status: aws file date {file.split('_')[0]}")
        add_to_mongo(parquet_dir_path, file, column_list, jattr_list)
    clean_mongo("sradb_list")
    finish_mongo()


def finish_mongo():
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    db["sradb_temp"].rename("sradb_list")
    collection_stats = db.command("collstats", "sradb_list")
    acc_count, total_size, avg_doc_size = collection_stats["count"], collection_stats["size"], collection_stats["avgObjSize"]
    print(f"Status: {acc_count} acc documents imported to mongoDB collection")
    print(f"Status: MongoDB size is {total_size} bytes, average document size is {avg_doc_size} bytes")
    mongo.close()


def clean_mongo(collection):
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    if collection in db.list_collection_names(): db[collection].drop()
    mongo.close()


def add_to_mongo(parquet_dir_path, file, column_list, jattr_list):
    print(f"Statis: Processing parquet file {file}")
    df = pd.read_parquet(os.path.join(parquet_dir_path, file))
    res_list = multi_parsing(df.to_dict(orient='records'), process_row, mp.cpu_count(), *[column_list, jattr_list], shuffle=False)
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    for meta_list in res_list:
        db["sradb_temp"].insert_many(meta_list)
    mongo.close()


def multi_parsing(data_list, parseFunction, threads, *argv, shuffle=True):
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


def process_row(attr_list, run, split, res_list, column_list, jattr_list):
    new_attr = list()
    for it,attr_dict in enumerate(attr_list):
        if int(it*10000/split) % 10 == 0 and int(it*100/split) != 0:
            print(f"Status: Processing {run:>2d} ... {it*100/split:>4.1f} %             ", end="\r")
        column_dict = {c:attr_dict[c] for c in column_list}
        jattr_dict = process_jattr(attr_dict["jattr"], jattr_list)
        meta_dict = {**column_dict, **jattr_dict}
        meta_dict = {k: process_value(v) for k, v in meta_dict.items()}
        meta_dict['biosample_link'] = f"https://www.ncbi.nlm.nih.gov/biosample/{meta_dict.get('biosample', '')}"
        meta_dict['sra_link'] = f"https://www.ncbi.nlm.nih.gov/sra/{meta_dict.get('acc', '')}"
        meta_dict['_id'] = meta_dict['acc']
        new_attr.append(meta_dict)
    res_list.append(new_attr)


def process_value(v):
    if   isinstance(v, list)       and not len(v): return 'NP'
    if   isinstance(v, list)                     : return v
    elif isinstance(v, np.ndarray) and not len(v): return 'NP'
    elif isinstance(v, np.ndarray):                return v.tolist()
    elif isinstance(v, float) and v.is_integer():  return int(v)
    elif isinstance(v, datetime.date):             return str(v)
    elif pd.isna(v):                               return 'NP'
    else:                                          return v


def process_jattr(jattr_str, jattr_list):
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


def get_mongoIDs_notes(self):
    #LOGGER.info(f"Getting current SRA IDs from MongoDB.")
    #mongo = pm.MongoClient(settings.MONGO_URI)
    mongo = pm.MongoClient("mongodb://localhost:27017/")
    db = mongo["sradb"]
    collection = db["sradb_list"]
    ####
    #distinct_values = collection.distinct('releasedate')
    #date_objects = [datetime.strptime(date, "%Y-%m-%d") for date in distinct_values if date != "NP"]
    #oldest_date = min(date_objects)
    #oldest_date_str = oldest_date.strftime("%Y-%m-%d")
    #print("Oldest Date:", oldest_date_str)
    ####
    #distinct_values = collection.distinct('librarysource')
    #['\n\t\t\t\tGENOMIC\n\t\t\t', 'GENOMIC', 'GENOMIC SINGLE CELL', 'METAGENOMIC', 'METATRANSCRIPTOMIC', 'OTHER', 'SYNTHETIC', 'TRANSCRIPTOMIC', 'TRANSCRIPTOMIC SINGLE CELL', 'VIRAL RNA']
    #print(distinct_values)
    #3760757
    # Number of entries in index: 3,760,757
    # Number of entries not found in MongoDB: 26,999
    # Number of entries with 'releasedate' as 'NP': 198
    # Number of entries sorted by librarysource:
    # total:          1 | intersection:         0 | librarysource: \n\t\t\t\tGENOMIC\n\t\t\t
    # total: 10,620,843 | intersection: 2,692,115 | librarysource: GENOMIC
    # total:     63,637 | intersection:         0 | librarysource: GENOMIC SINGLE CELL
    # total:  4,908,180 | intersection:   953,702 | librarysource: METAGENOMIC
    # total:    132,738 | intersection:    83,224 | librarysource: METATRANSCRIPTOMIC
    # total:    237,001 | intersection:       736 | librarysource: OTHER
    # total:    104,140 | intersection:       105 | librarysource: SYNTHETIC
    # total:  5,285,187 | intersection:     3,038 | librarysource: TRANSCRIPTOMIC
    # total:    319,483 | intersection:         0 | librarysource: TRANSCRIPTOMIC SINGLE CELL
    # total:  6,528,643 | intersection:       838 | librarysource: VIRAL RNA
    ####
    # oldest date: 2007-06-05 newest date: 2024-11-13
    # start_date = "2023-09-26" mongo IDs: 104099 shared IDs: 1795
    # start_date = "2023-09-27" mongo IDs: 95092  shared IDs: 54
    # start_date = "2023-09-28" mongo IDs: 67608  shared IDs: 0
    #ids = collection.find({"librarysource": mID}, {"_id": 1})
    #ids = collection.find({}, {"_id": 1})
    start_date = "2007-06-05"
    end_date = "2015-12-31"
    query = {"releasedate": {"$gte": start_date, "$lte": end_date}}#,
    #         "librarysource": "METAGENOMIC"}
    ids = collection.find(query, {"_id": 1})
    mongo_IDs = [doc["_id"] for doc in ids]
    mongo.close()
    return mongo_IDs