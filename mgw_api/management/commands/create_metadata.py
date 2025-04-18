import pickle
import subprocess

import polars as pl
import pymongo as pm
from django.conf import settings
from django.core.management.base import BaseCommand

from mgw.settings import LOGGER


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
        parser.add_argument(
            "--drop-first",
            action="store_true",
            help="Drop the old metadata collection before creating the new one (usually not recommended, but necessary in low space situations)",
        )
        parser.add_argument(
            "--indexed-only",
            action="store_true",
            help="Only save metadata for sequences that are already in the search index",
        )

    def handle(self, *args, **kwargs):
        try:
            LOGGER.info("Starting metadata update")
            download = not kwargs["no_download"]
            process = not kwargs["no_process"]
            drop_first = kwargs["drop_first"]
            indexed_only = kwargs["indexed_only"]

            database = "SRA"
            metadata_dir = settings.DATA_DIR / database / "metadata" / "parquet"
            metadata_dir.mkdir(parents=True, exist_ok=True)

            if drop_first:
                LOGGER.info("Dropping existing mongodb collections")
                self.drop_mongo_collection("sradb_list")
                self.drop_mongo_collection("sradb_temp")

            if download:
                self.download_sra(metadata_dir)
            else:
                LOGGER.info("Skip downloading of new SRA metadata")

            if process:
                self.import_parquet(metadata_dir, indexed_only)
            else:
                LOGGER.info("Skip importing SRA metadata files into mongodb")

            self.set_initial_flag()
            LOGGER.info(
                f"Downloaded new data into {metadata_dir} and imported into mongodb."
            )
        except Exception as e:
            LOGGER.error(f"Error processing metadata update': {e}")

    def get_filter_data(self):
        column_list = [
            "acc",
            "assay_type",
            "bioproject",
            "biosample",
            "collection_date_sam",
            "geo_loc_name_country_calc",
            "organism",
            "releasedate",
            "librarysource",
        ]

        # These fields are packed into the jattr column of the SRA parquet
        # files and need to be handled specially
        jattr_dtypes = pl.Struct(
            [
                pl.Field("lat_lon", dtype=pl.String),
            ]
        )

        allowed_librarysources = ["METAGENOMIC", "GENOMIC", "METATRANSCRIPTOMIC"]

        return column_list, jattr_dtypes, allowed_librarysources

    def download_sra(self, parquet_dir):
        LOGGER.info("Downloading SRA metadata files from S3")
        command = [
            "aws",
            "s3",
            "sync",
            "s3://sra-pub-metadata-us-east-1/sra/metadata/",
            parquet_dir,
            "--no-sign-request",
            "--delete",
        ]
        result = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        stdout, stderr = result.communicate()
        if result.returncode == 0:
            LOGGER.info("Download metadata succeeded")
        else:
            LOGGER.error(f"Download metadata failed with error {stderr}")

    def import_parquet(self, parquet_dir, indexed_only=None):
        self.drop_mongo_collection("sradb_temp")
        column_list, jattr_dtypes, allowed_librarysources = self.get_filter_data()

        indexed_ids = None
        if indexed_only:
            database = "SRA"
            indexed_ids_file = (
                settings.DATA_DIR / database / "metagenomes" / "manifest.pcl"
            )
            if indexed_ids_file.exists():
                try:
                    with open(indexed_ids_file, "rb") as f:
                        indexed_ids = pickle.load(f)
                except Exception as e:
                    LOGGER.warning(
                        f"Could not load indexed SRA ids file ({indexed_ids_file}). Skipping filtering using those ids. {e}"
                    )
            else:
                LOGGER.warning(f"File not found: {indexed_ids_file}")

        # scan_parquet() can handle the whole directory of files at once, but
        # memory usage goes crazy. For now we just import one file at a time.
        for file_num, parquet_file in enumerate(parquet_dir.glob("*")):
            LOGGER.info(f"Processing SRA parquet file {file_num}: {parquet_file.name}")
            df = pl.scan_parquet(parquet_file)
            sra_lf = df.filter(
                pl.col("librarysource").is_in(allowed_librarysources)
            ).select(column_list + ["jattr"])

            # Only filter by accessions if we actually have a set of ids to filter by
            if indexed_ids:
                sra_lf = sra_lf.filter(pl.col("acc").is_in(indexed_ids))

            sra_df = (
                sra_lf.collect()
                .with_columns(
                    pl.col(pl.Date).cast(pl.Datetime)
                )  # Cast all date columns to datetime to keep mongodb happy
                .with_columns(
                    pl.col("jattr").str.json_decode(jattr_dtypes).alias("jattr_decoded")
                )  # Decode json cell into a polars struct with just the fields we care about
                .drop("jattr")
                .unnest("jattr_decoded")  # Unnest to split struct into separate columns
                .with_columns(
                    [
                        pl.when(pl.col("acc").is_not_null())
                        .then(
                            pl.format(
                                "https://www.ncbi.nlm.nih.gov/sra/{}", pl.col("acc")
                            )
                        )
                        .otherwise(None)
                        .alias("sra_link"),
                        pl.when(pl.col("biosample").is_not_null())
                        .then(
                            pl.format(
                                "https://www.ncbi.nlm.nih.gov/biosample/{}",
                                pl.col("biosample"),
                            )
                        )
                        .otherwise(None)
                        .alias("biosample_link"),
                    ]
                )
                .with_columns(
                    [pl.col("acc").alias("_id")]
                )  # assign acc to the special mongodb _id field
            )

            # Only insert data if there is some to insert
            if sra_df.height > 0:
                mongo = pm.MongoClient(settings.MONGO_URI)
                db = mongo["sradb"]
                db["sradb_temp"].insert_many(sra_df.to_dicts())
                mongo.close()

        self.drop_mongo_collection("sradb_list")
        self.finish_mongo()

    def drop_mongo_collection(self, collection):
        mongo = pm.MongoClient(settings.MONGO_URI)
        db = mongo["sradb"]
        if collection in db.list_collection_names():
            db[collection].drop()
            LOGGER.debug(f"Dropped mongodb collection {collection}.")
        mongo.close()

    def finish_mongo(self):
        mongo = pm.MongoClient(settings.MONGO_URI)
        db = mongo["sradb"]
        db["sradb_temp"].rename("sradb_list")
        collection_stats = db.command("collstats", "sradb_list")
        acc_count, total_size, avg_doc_size = (
            collection_stats["count"],
            collection_stats["size"],
            collection_stats["avgObjSize"],
        )
        LOGGER.info(f"{acc_count} acc documents imported to mongoDB collection")
        LOGGER.debug(
            f"MongoDB size is {total_size} bytes ({total_size/1024.0**3:.2f} GB), average document size is {avg_doc_size} bytes"
        )
        mongo.close()

    # TODO: check if we really need to do this. Currently I'm not, and I also
    # get a lot of None columns in my jattr columns. Not sure if that is the
    # cause.
    # def cleanup_jattr_field_names(self, names):
    #     cleaned_dict = {
    #         re.sub(r"_sam_s_dpl34|_sam", "", k): v for k, v in jattr_dict.items()
    #     }

    # TODO: see if we want to reuse some if this. The lat_lon field needs to be
    # processed or else we will have problems when showing the results table.
    # def parse_lat_lon(self, lat_lon):
    #     lalo = cleaned_dict.get("lat_lon", "NP")
    #     NS, EW = {"N": 1, "S": -1}, {"W": -1, "E": 1}
    #     match = re.search(r"(\d+(\.\d+)?) ([NS]) (\d+(\.\d+)?) ([EW])", lalo)
    #     if match:
    #         lat = float(match.group(1)) * NS.get(match.group(3), 1)
    #         lon = float(match.group(4)) * EW.get(match.group(6), 1)
    #         cleaned_dict["lat_lon"] = [lat, lon]
    #     else:
    #         cleaned_dict["lat_lon"] = "NP"

    def set_initial_flag(self):
        init_flag = settings.DATA_DIR / "SRA" / "metadata" / "initial_setup.txt"
        init_flag.touch()
