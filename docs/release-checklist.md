# Production release checklist (image-based deployments)

Use this checklist when promoting a MetagenomeWatch change from merge to safe production rollout.

## 1) Prepare the application change

- [ ] If models changed, create Django migrations before merge so they are committed into the release image:

  ```bash
  ./scripts/dev-manage.sh makemigrations
  ```

- [ ] Review generated migration files and commit them with the application change.
- [ ] Pull request approved and merged to `main`.
- [ ] Changelog/release notes drafted (what changed, risk areas, rollback notes).
- [ ] Any required schema/data migration steps identified.
- [ ] Confirm the merge commit already contains every required migration file before the image build starts.

## 2) Build and publish the backend image

- [ ] CI pipeline builds the backend image from `Dockerfile`.
- [ ] Image is published to GHCR.
- [ ] Record immutable image digest (`sha256:...`) for deployment.
- [ ] Optional: create a semantic release tag (e.g. `v1.6.0`) mapped to the same digest.

## 3) Promote to staging first

- [ ] Update staging deployment config to the new digest:

  ```env
  DOCKER_MGWATCH_IMAGE=ghcr.io/<org>/mgwatch:sha-<git digest>
  ```

- [ ] Deploy staging:

  ```bash
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d
  ```

- [ ] Run migrations (if needed):

  ```bash
  docker compose -f compose.prod.yml run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py migrate"
  ```

- [ ] Run smoke tests (login, search, watch workflow, admin paths).
- [ ] Check logs for startup/runtime errors:

  ```bash
  docker compose -f compose.prod.yml logs -f --tail=200
  ```

## 4) Production change control

- [ ] Open deployment PR (or change request) that updates **only** the production digest.
- [ ] Verify `DEBUG=False`, `ALLOWED_HOSTS`, and other production settings in `vars.env`.
- [ ] Confirm maintenance window and owner/on-call coverage.
- [ ] Capture rollback target digest before rollout.

## 5) Roll out to production

- [ ] Apply deployment with explicit compose file:

  ```bash
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d
  ```

- [ ] Run migrations (if required):

  ```bash
  docker compose -f compose.prod.yml run --rm mgwatch "conda run --no-capture-output -n mgw ./manage.py migrate"
  ```

- [ ] Verify service health endpoints / core user flows.
- [ ] Verify worker/cron behavior and scheduled task logs.

## 6) Rollback procedure (if needed)

- [ ] Revert production digest to prior known-good digest.
- [ ] Redeploy:

  ```bash
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d
  ```

- [ ] Confirm service recovery and record incident notes.

## 7) Post-release closeout

- [ ] Announce rollout completion.
- [ ] Save the deployed digest + release notes in your operations log.
- [ ] Track any follow-up fixes discovered during rollout.

## Suggested policy guardrails

- Keep production deployment artifacts in a dedicated ops repo/directory.
- Pin production to image digests (not mutable tags like `latest`).
- Require review/approval for digest updates in production configuration.
- Do not keep dev helper scripts on production hosts.
