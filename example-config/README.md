# Example image deployment config

This directory is a template for image-based deployments. Copy `.env.example` to
`.env` and `vars.env.example` to `vars.env` in the deployment directory, then
replace every `CHANGE_ME` value before starting services.

The included `config/database.yml` is mounted into the application containers at
`/config/database.yml`. Edit this file, or set `CONFIG_DIR` in `.env` to point at
another host directory containing `database.yml`, before starting services if you
need a non-default database configuration.

When upgrading an existing deployment that still has legacy `SRA/metagenomes`
data, run the one-time storage migration before starting the application:

```bash
docker compose -f compose.prod.yml run --rm --no-deps mgwatch "pixi run --frozen ./manage.py migrate_database_storage --dry-run"
docker compose -f compose.prod.yml run --rm --no-deps mgwatch "pixi run --frozen ./manage.py migrate_database_storage"
```

Start the stack with:

```bash
docker compose -f compose.prod.yml up -d
```

Only `mgwatch-proxy` publishes a host port. PostgreSQL, MongoDB, and Redis are
internal Compose services and should not be exposed in production.
