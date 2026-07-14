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

`vars.env`: this file doesn't exist by default. An example is provided in the project root directory, called `vars.env.example`. You should copy this file to `vars.env` and customize its contents as needed.

```
$ cp vars.env.example vars.env
```

`.env`: these are variables that are needed to properly set up the docker containers. As with vars.env, the file is missing by default. You should copy the `.env.template` and customize its contents as needed.

```
$ cp .env.template .env
```

The application image runs as the non-root `mgwatch` user. For bind-mounted
deployment directories, set `MGWATCH_UID` and `MGWATCH_GID` in `.env` and make
sure the mounted data, SQLite, log, and static directories are writable by that
UID/GID before starting the stack.

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

- code: `mgw_api/`
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

### mgw_api/management/commands/create_search.py
- modified to only work with SRA and k=21
- change line 35 to change this behavior

### mgw_api/management/commands/create_metadata.py
- modify line 107 to allow for more cores


## Production deployment without cloning the repository

To deploy from prebuilt images, use a production compose file that references `DOCKER_MGWATCH_IMAGE` from GHCR and keep deployment files in a separate ops directory/repository.

Recommended operator workflow:

1. Download or sync a deployment bundle (`compose.prod.yml`, `.env`, `vars.env`).
2. Set `DOCKER_MGWATCH_IMAGE` to a pinned digest such as `ghcr.io/rki-mf1/mgwatch:sha-<git digest>`.
3. Start services with `docker compose -f compose.prod.yml up -d`.
4. Run maintenance commands with `docker compose -f compose.prod.yml run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py <command>"`.

## Backups

Backups must cover both databases and the filesystem state used by
MetagenomeWatch: SQLite, MongoDB, media uploads, signatures, indexes, manifests,
logs, `.env`, `vars.env`, Compose files, and NGINX/deployment configuration.

Run the backup script from the deployment directory that contains `.env`,
`vars.env`, and the Compose file:

```console
$ COMPOSE_FILE=compose.prod.yml ./scripts/backup.sh /srv/mgwatch/backups
```

For repository-local development, the defaults target `compose.yml` and write to
`./backups`:

```console
$ ./scripts/backup.sh
```

Each run creates `mgwatch-<timestamp>/` with:

- `sqlite/db.sqlite3`: online SQLite backup created through the SQLite backup API.
- `mongodb.archive.gz`: `mongodump --archive --gzip` output when the MongoDB container is running.
- `archives/backend-data.tar.gz`: uploaded media, signatures, indexes, manifests, and other `/data` state.
- `archives/logs.tar.gz` and `archives/nginx-data.tar.gz`: operational logs and proxy/static deployment data.
- `config/`: copied environment, Compose, and NGINX template files.
- `MANIFEST.txt`: source paths and file sizes for the backup set.

Store backup output outside the application data directories and protect it like
production data because it can contain uploaded sequences, metadata, credentials,
and operational logs. Before migrations, image upgrades, or data/index rebuilds,
create a fresh backup and record its path in the release notes. Periodically test
restores in a staging environment.

To restore a backup, stop application traffic, make sure the target `.env` points
to the intended restore paths, and run:

```console
$ COMPOSE_FILE=compose.prod.yml ./scripts/restore.sh --force /srv/mgwatch/backups/mgwatch-<timestamp>
```

The restore script overwrites the configured SQLite database, backend data,
logs, NGINX/static data, and copied deployment config. If
`mongodb.archive.gz` exists and `mgwatch-mongodb` is running, it imports the
dump with `mongorestore --drop --archive --gzip`. After restore, start the stack,
run migrations if required by the restored application version, and run the smoke
tests from the release checklist.

## Retention cleanup

MetagenomeWatch has a scheduled retention cleanup task for user-facing search
data, stale job rows, temporary files, failed index artifacts, and old Django log
files. The task runs daily at 02:30 on the maintenance queue when
`RETENTION_CLEANUP_ENABLED=True`.

Default retention periods:

- Unwatched results: 180 days.
- Watched results: 365 days.
- Orphaned signatures with no remaining result rows: 180 days.
- Stale unprocessed FASTA uploads: 7 days.
- Completed job rows: 180 days.
- Failed job rows: 90 days.
- Temporary files: 7 days.
- Failed index artifacts: 30 days.
- Django `.log` files: 180 days.

The cleanup does not age-delete canonical metadata, manifests, SQLite, MongoDB,
production indexes, or current WORT search state. Those data classes are managed
through explicit backup, restore, release, and index rebuild procedures.

Run a dry-run before changing retention settings or applying cleanup manually:

```console
$ ./scripts/dev-manage.sh cleanup_retention
```

Apply cleanup explicitly with:

```console
$ ./scripts/dev-manage.sh cleanup_retention --apply
```

Set a retention period to a negative value to disable cleanup for that data
class. Cleanup logs report aggregate counts only and must not include uploaded
sequence content, metadata rows, user filenames, or detailed paths. Take a fresh
backup before lowering retention periods because applied cleanup is destructive.

## LDAP deprovisioning

When LDAP is configured, run `reconcile_ldap_users` periodically from the
application container to detect users that no longer exist in LDAP:

```console
$ docker compose -f compose.prod.yml run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py reconcile_ldap_users"
```

The command aborts on LDAP connection/search errors, so LDAP outages do not mark
users as missing. Missing LDAP users are tracked in the database, disabled
according to `LDAP_DEPROVISION_DISABLE_IMMEDIATELY`, and assigned a configurable
deletion due date from `LDAP_DEPROVISION_GRACE_DAYS`. Set
`LDAP_DEPROVISION_NOTIFY_EMAIL` to notify operators, and set
`LDAP_DEPROVISION_DELETE_AFTER_GRACE=True` only when the deployment is ready for
automatic user deletion and the corresponding media cleanup after the grace
period.

`LDAP_ALLOW_LOCAL_AUTH_FALLBACK=False` makes LDAP authoritative by removing the
Django local password backend when LDAP is configured. Keep a documented
break-glass administrative path before disabling local fallback.
