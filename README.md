# MetagenomeWatch

MetagenomeWatch is a system that uses [sourmash branchwater](https://github.com/sourmash-bio/sourmash_plugin_branchwater) to index and peform fast content searches of genomic sequencing data. Compared to the exising [branchwater website](https://branchwater.jgi.doe.gov/advanced), MetagenomeWatch has a few unique features:

- the ability to set up "watches", which will automatically search any new sequences that are added to the database and notify you via email if high quality matches are found
- user accounts, so you can save and review search results from previous searches

## Initial Setup

We use docker both when doing development as well as when running in production. Specifically, we use [rootless docker](https://docs.docker.com/engine/security/rootless/).

### Setting up rootless docker

Instructions will vary based on your operating system and are outlined [here](https://docs.docker.com/engine/security/rootless/), but for Debian or Ubuntu the process should roughly be:

Install and check some dependencies:

```
$ sudo apt install -y dbus-user-session uidmap docker-ce-rootless-extras
$ slirp4netns --version  # Must be > v0.4.0
slirp4netns version 1.2.0
commit: 656041d45cfca7a4176f6b7eed9e4fe6c11e8383
libslirp: 4.7.0
SLIRP_CONFIG_VERSION_MAX: 4
libseccomp: 2.5.4
```

Make sure your user has a set of subordinate UIDs and GIDs. If not, edit the `/etc/subuid` and `/etc/subgid` files as needed:

```
$ id -u
1001
$ whoami
testuser
$ grep ^$(whoami): /etc/subuid
testuser:231072:65536
$ grep ^$(whoami): /etc/subgid
testuser:231072:65536
```

Disable system-wide docker daemon

```
sudo systemctl disable --now docker.service docker.socket
sudo rm /var/run/docker.sock
```

To launch the daemon on system startup, enable the systemd service and lingering:

```console
$ systemctl --user enable docker
$ sudo loginctl enable-linger $(whoami)
```

As your normal user, run the command:

```
$ dockerd-rootless-setuptool.sh install
```

### Configuring MetagenomeWatch

There are currently two places where you MetagenomeWatch configuration is stored:

`vars.env`: this file doesn't exist by default. An example is provided in the project root directory, called `vars.env.example`. You should copy this file to `.env` and customize its contents as needed.

```
$ cp vars.env.example vars.env
```

`.env`: these are variables that are needed to properly set up the docker containers. As with vars.env, the file is missing by default. You should copy the `.env.template` and customize its contents as needed.

```
$ cp .env.template .env
```

### Managing MetagenomeWatch docker containers

The `./scripts` folder contains helper scripts you can use to perform most docker-related tasks for MetagenomeWatch.

1. Rebuild the Django docker container: `./scripts/build-docker.sh`
1. Start all containers: `./scripts/dc-dev.sh up -d`
1. Stop all containers: `./scripts/dc-dev.sh down`
1. Apply Django migrations: `./scripts/dev-migrate.sh`
1. Run Django mangement tasks: `./scripts/dev-manage.sh create_metadata` (downloads and builds metadata database)

Additionally, the `./mgw.sh` convenience script can also be used to run several commands in a more convenient way:

```
$ ./mgw.sh -h
./mgw.sh [-b] [-c] [-m]
 -b     build backend docker container
 -c     create (=make) migrations
 -m     migrate
# Bring down all containers, rebuild Django container, bring up containers and apply migrations:
$ ./mgw.sh -bm
```

### Automatic behaviour in developer mode

Staring MetagenomeWatch in developer mode will do a few things automatically, which aren't done in production:

- first start will download the metadata and create the mongodb
- currently set to use a maximum of 80% of available processors
- will create `mgw-data/SRA/metadata/initial_setup.txt` if it was successful
- takes a while

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
