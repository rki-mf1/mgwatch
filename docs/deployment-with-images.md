# Deploying MetagenomeWatch from published Docker images

This document describes how to run MetagenomeWatch on a host without cloning the
application repository.

## Required deployment artifacts

A release bundle should include:

- `compose.prod.yml`
- `.env` (compose/runtime host settings)
- `vars.env` (Django app settings/secrets)

The backend image must be available in GHCR under a tag or digest, for example:

- `ghcr.io/rki-mf1/mgwatch:sha-<git digest>`

Prefer digest pinning for reproducibility.

## Runtime host steps

1. Place deployment artifacts in a directory on the runtime host.
2. Set `DOCKER_MGWATCH_IMAGE` in `.env`.
3. Start services:

   ```bash
   docker compose -f compose.prod.yml up -d
   ```

4. Run migrations if needed:

   ```bash
   docker compose -f compose.prod.yml run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py migrate"
   ```

5. Verify service logs:

   ```bash
   docker compose -f compose.prod.yml logs -f --tail=200
   ```

## Operational notes

- Keep persistent paths (`EXTERNAL_DATA_DIR`, `SQLITE_DIR`, `MONGODB_DATA_DIR`, `LOG_DIR`) on durable storage.
- Use `vars.env` to manage Django secrets and environment-specific behavior.
- Keep cron and backend services on the same image tag/digest.

## Related documentation

- [Production release checklist](./release-checklist.md)
