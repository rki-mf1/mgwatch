# MetagenomeWatch

MetagenomeWatch is a web service for searching genome sequences against large
metagenomic sequencing indexes and keeping important searches under watch as new
data becomes available.

It combines [sourmash branchwater](https://github.com/sourmash-bio/sourmash_plugin_branchwater)
search with a persistent, multi-user application: users can upload FASTA files,
review saved results, and turn a result into a watch that is rerun automatically
when the local search index is updated.

## What MetagenomeWatch Does

MetagenomeWatch helps researchers and analysts answer questions such as: where
has this genome, organism, or marker-like sequence appeared in public
metagenomic sequencing data?

The typical workflow is:

1. Upload a FASTA file through the web interface.
2. MetagenomeWatch creates a sourmash signature in the background.
3. The signature is searched against the configured metagenomic index.
4. Results are saved to the user's account for later review.
5. Any result can be marked as a watch and rerun automatically after future
   index updates.

## Why MetagenomeWatch

MetagenomeWatch is designed for teams that need more than a one-off search form.
Compared with using branchwater directly or a public search page, it adds:

- Persistent user accounts with saved searches and result history.
- Watch workflows that notify users by email when updated indexes produce new
  high-quality matches.
- Background processing with visible job status and progress reporting.
- Metadata-enriched result tables for filtering, sorting, and reviewing matches.
- A self-hosted deployment model suitable for institutional services.
- Operational support for scheduled metadata/index updates, backups, retention
  cleanup, and optional LDAP user deprovisioning.

## Screenshot

<!-- TODO: Add a screenshot of the search/results workflow here.
Suggested path: docs/images/metagenomewatch-results.png -->

_Screenshot coming soon._

## Who It Is For

**Researchers and analysts** can use MetagenomeWatch to search uploaded sequences,
come back to previous results, and keep biologically or operationally important
queries under continuous watch.

**Service operators** can run MetagenomeWatch for a group, institute, or project
using Docker Compose, persistent storage, background workers, and documented
maintenance workflows.

## Quick Start With Docker Compose

The recommended deployment path is to run published container images with the
example Docker Compose deployment files in [`example-config/`](example-config/).

```bash
mkdir mgwatch-deploy
cp example-config/compose.prod.yml mgwatch-deploy/
cp example-config/.env.example mgwatch-deploy/.env
cp example-config/vars.env.example mgwatch-deploy/vars.env
cp -r example-config/nginx-templates mgwatch-deploy/

cd mgwatch-deploy
# Edit .env and vars.env, replacing every CHANGE_ME value.

docker compose -f compose.prod.yml up -d
docker compose -f compose.prod.yml run --rm mgwatch "pixi run --frozen ./manage.py migrate"
```

For production, pin `DOCKER_MGWATCH_IMAGE`, `DOCKER_NGINX_IMAGE`, PostgreSQL,
MongoDB, and Redis images by immutable digest. Keep the persistent data,
PostgreSQL, MongoDB,
logs, and static-file paths on durable storage and make sure they are writable by
the configured `MGWATCH_UID:MGWATCH_GID`.

Only the reverse proxy service should publish a host port. PostgreSQL, MongoDB,
and Redis are internal Compose services and should not be exposed directly.

See [Deploying MetagenomeWatch from published Docker images](docs/deployment-with-images.md)
for the full image-based deployment workflow.

## Operations

Operators should plan for the following before running a shared instance:

- Configure email if users should receive watch notifications.
- Back up PostgreSQL, MongoDB, uploaded media, signatures, indexes, manifests, logs,
  and deployment configuration.
- Review retention settings before enabling automatic cleanup.
- Use the release checklist before image upgrades, migrations, or index rebuilds.
- Configure LDAP only when a tested break-glass administrative path exists.
- After directly modifying on-disk indexes or manifests, refresh the cached
  Stats index count with `./scripts/dev-manage.sh update_stats --index-only`.

Useful references:

- [Production release checklist](docs/release-checklist.md)
- [Release governance](docs/release-governance.md)
- [Architecture and index maintenance notes](docs/architecture.md)
- [Example deployment config](example-config/README.md)

## Development

Development commands and conventions are documented in [AGENTS.md](AGENTS.md) and
[CONTRIBUTING.md](CONTRIBUTING.md). The main test entry point is:

The dev fixture loader creates local-only users for manual development:

- `root` / `root` for admin access.
- `user` / `user` for normal user access.

```bash
./scripts/run-tests.sh
```

To run a narrower Django test target, pass the test label:

```bash
./scripts/run-tests.sh mgw_api.tests.test_jobs
```

## Acknowledgements

We thank the sourmash team for their helpful communications during this project
and for developing excellent software. MetagenomeWatch depends on sourmash and
sourmash branchwater; without that work, this project would not be possible.

## Similar Tools

- [Branchwater Search](https://branchwater.sourmash.bio/) provides public
  sourmash branchwater searches; MetagenomeWatch builds on similar search
  technology but adds user accounts, saved results, watches, notifications, and
  self-hosted service operations.
- [Logan Search](https://logan-search.org/) searches over pre-assembled SRA
  genomes, while MetagenomeWatch is designed around searching metagenomic
  sequencing indexes derived from raw reads.

## License

See [LICENSE.txt](LICENSE.txt).
