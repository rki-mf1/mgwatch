# Updates

## Summary of important files and directories

All subfolders of `backend-data/SRA/metagenomes`:

- `failed/`: ?
- `index/`: Branchwater indexes
- `lists/`: lists of SRA IDs explaining what is contained in the indexes generated from data received from Titus et al. Not used in the future.
- `manifest.pcl`: a list of all SRA indexes that are stored in all indexes (the union of manifests/*.pcl file contents)
- `manifests/`: list of SRA indexes that are stored in each matching index file (in index/)
- `signatures/`: signatures downloaded from wort that have been indexed
- `updates/`: signatures downloaded from wort but not yet indexed

## Initial setup

Before any update on the index, the following command has to be run once from inside the code directory. Before running the command, all `sig-sra-<0-9>.txt` files have to be moved inside the `data/SRA/metagenomes/lists/` directory. These are then used inside the `create_manifest.py` command to generate the main manifest and all individual index manifests.

```bash
./scripts/dev-manage.sh create_manifests
```

This will create the initial `manifest.pcl` and all individual index manifest files available in `data/SRA/metagenomes/manifests/`.

## Daily update schedule

An update can be done manually with:

```bash
./scripts/dev-manage.sh create_daily
```

If enabled the automated cron job will run this script every day at 1AM.

## Update commands

The daily update will run (in order):

1. `create_metadata.py`
2. `create_downloads.py`
3. `create_index.py`
4. `create_watch.py`

### 1. Creating metadata

This will first download the newest NCBI metadata collection on aws and then integrate the new metadata into the MongoDB. Downloaded parquet files can be found in `data/SRA/metadata/parquet/`. The `initial_setup.txt` file is currently required to tell the `runserver.py` command to only download the metadata on the very first application run to create an initial metadata database.

### 2. Creating downloads

Depending on the user settings, this will either download the *wort* signatures of a specific date range (`START_DATE` to `END_DATE`) or the current date minus two days (`START_DATE=0`). This is to account for the metadata being 1 day behind and to adjust for the current 1 AM update time.

The script will get all SRA IDs of the specified date range from the updated MongoDB and from the `manifest.pcl` which is either empty if `INDEX_FROM_SCRATCH` setting was enabled or contains all current index SRA IDs which were initially added through the one time `create_manifest.py` command.

New *wort* signatures will be stored in `data/SRA/metagenomes/updates/`. Successful download IDs will be stored inside `update_successful.pcl` and failed download IDs will be stored inside `update_failed.pcl`. The IDs from both files will be ignored if the command fails and resumes downloads. Failed downloads can be re-enabled by setting the `WORT_SKIP_FAILED` to `False`. The `update_successful.pcl` file will be emptied at the end of the `create_index.py` command when the new SRA IDs have been stored inside the manifest files.

There are several further settings that can be changed for the download.
- `LIB_SOURCE` only download signatures with a specific libsource value
- `WORT_ATTEMPTS` number of download attempts if a download fails
- `MAX_DOWNLOADS` maximum number of downloads that run with one call of the command

### 3. Creating index

The script will check the current manifest ID inside the `data/SRA/metagenomes/manifests/` directory. This will be currently set to `38` for `wort-sra-kmer-db38.pcl`. There is also a settings parameter (`INDEX_MIN_ITERATOR`) that sets the current minimum index number to `38` as a precaution.

The script will read the SRA IDs from the current manifest number and the SRA files that are inside the `data/SRA/metagenomes/updates/` directory and combines them to create the `sig-list.txt` file which then contains the signature paths for the new index generation. If the number of the current and the new signatures exceed 100.000, the script will automatically increase the iterator to the next number.

As soon as all indices (21, 31, 51-mer) have been created, the script will add all added SRA IDs to the main manifest file (`manifest.pcl`) and update the individual index manifest file, as well as empty the `download_successful.pcl` file.

If the index creation fails, all signatures will be moved from `data/SRA/metagenomes/updates/` to `data/SRA/metagenomes/failed/` and have to be moved manually to the updates folder manually. If the index creation is successful, they will be moved to `data/SRA/metagenomes/signatures/`.

### 4. Create watch

This will run a sourmash SRA search for all current active watches. All new result `.csv` files will be compared with the already existing files. If they are the same, the new one will be discarded. If they are different, the new search result will be kept and an email will be sent to the user.
