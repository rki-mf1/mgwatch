# Production release checklist (image-based deployments)

Use this checklist when promoting a MetagenomeWatch change from merge to safe production rollout.

## 1) Prepare the application change

- [ ] If models changed, create Django migrations before merge so they are committed into the release image:

  ```bash
  ./scripts/dev-manage.sh makemigrations
  ```

- [ ] Review generated migration files and commit them with the application change.
- [ ] Pull request or tracked branch exists, CI passed, including pre-commit,
      Django migration check, full Django tests, coverage threshold, and quick
      release gate, and the release owner reviewed the final diff.
- [ ] Generate draft release notes:

  ```bash
  python scripts/generate-release-notes.py --from <previous-release-ref> --to <release-ref> --output release-notes.md
  ```

- [ ] Review generated release notes for what changed, security-relevant changes, risk areas, migration notes, and rollback notes.
- [ ] Any required schema/data migration steps identified.
- [ ] Confirm the merge commit already contains every required migration file before the image build starts.
- [ ] Confirm release governance evidence expectations in [release-governance.md](./release-governance.md).

## 2) Build and publish the backend image

- [ ] CI pipeline builds the backend image from `Dockerfile`.
- [ ] Image is published to GHCR.
- [ ] Record immutable image digest (`sha256:...`) for deployment.
- [ ] Optional: create a semantic release tag (e.g. `v1.6.0`) mapped to the same digest.
- [ ] Record CI run links and image digest artifact location in the operations log or change request.
- [ ] Verify the latest successful `vulnerability-scan` run covers the release commit on `main`; if not, run it manually with `workflow_dispatch` and record the result.

## 3) Promote to staging first

If no staging instance is operated for this release, run the manual
`release-smoke` GitHub Actions workflow or:

```bash
ALLOW_STACK_RECREATE=1 ./scripts/test-changeset-against-main.sh --full
```

Record the result in the release notes before production rollout.

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
  docker compose -f compose.prod.yml run --rm mgwatch "pixi run --frozen ./manage.py migrate"
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
- [ ] Record the last branch-protection verification date or evidence location.

## 5) Roll out to production

- [ ] Apply deployment with explicit compose file:

  ```bash
  docker compose -f compose.prod.yml pull
  docker compose -f compose.prod.yml up -d
  ```

- [ ] Run migrations (if required):

  ```bash
  docker compose -f compose.prod.yml run --rm mgwatch "pixi run --frozen ./manage.py migrate"
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
- [ ] Finalize `CHANGELOG.md` or attach finalized notes to the GitHub Release.
- [ ] Save the deployed digest, rollback digest, release notes, CI links, and smoke-test result in your operations log.
- [ ] Track any follow-up fixes discovered during rollout.

## Suggested policy guardrails

- Keep production deployment artifacts in a dedicated ops repo/directory.
- Pin production to image digests (not mutable tags like `latest`).
- In the current single-maintainer model, document release-owner final diff review instead of requiring independent PR approval.
- Require independent review/approval for production-impacting changes once a second qualified maintainer is available.
- Do not keep dev helper scripts on production hosts.
