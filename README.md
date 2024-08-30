# MetagenomeWatch
MetagenomeWatch

## Initial Setup
1. delete current mamba environment e.g. `mamba remove -n mgw --all`
2. create `mgw-api/vars.env` with environmental variables
3. start server with `bash mgw.sh m` (`m` for migrate)
    - first start will download the metadata and create the mongodb
    - currently set to a maximum of 1 core
    - will create `mgw-data/SRA/metadata/initial_setup.txt` if it was successful
    - takes a while
4. move rocksdb index directories to `mgw-data/SRA/metagenomes/index`
    - directory will be created outside of the code base
    - can also be created manually before starting the server

## Directories
- code: `mgw-api/`
- index: `mgw-data/SRA/metagenomes/`
- metadata: `mgw-data/SRA/metadata/`

## Current update settings

### mgw_api/management/commands/create_crons.py
- change line 39 to adjust update timing
- currently set to 1 am every day

### mgw_api/management/commands/create_daily.py
- line 15: runs metadata update
- line 16: runs index update
- line 17: runs watches (also run after successfull index update)
- currently all are deactivated

### mgw_api/management/commands/create_mail.py
- local mail server for testing
- create vars.env file in main directory with mail setting variables
- e.g. SECRET_KEY, EMAIL_HOST_PASSWORD, EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS, EMAIL_HOST_USER, DEFAULT_FROM_EMAIL

### mgw_api/management/commands/create_search.py
- modified to only work with SRA and k=21
- change line 35 to change this behavior

### mgw_api/management/commands/create_metadata.py
- modify line 107 to allow for more cores
