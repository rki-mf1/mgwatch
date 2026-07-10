# Changeset Test Plan

This plan is aimed at validating the current branch against `main`, with extra
coverage around the Celery/job refactor, maintenance services, indexing, search,
watch processing, and the result/status UI paths.

## Test Layers

1. Compare the branch to `main`.
   - Record `git diff --stat main...HEAD` and `git diff --name-status main...HEAD`.
   - Run the quick suite on `main` and on the current branch when a true baseline
     comparison is needed.

2. Build and configuration checks.
   - Build `mgwatch:local` from the branch.
   - Validate Docker Compose config.
   - Run Django `check`.
   - Run `makemigrations --check --dry-run`.

3. Automated Django tests.
   - Run the full Django test suite in the container.
   - Keep Celery eager for this layer so the unit tests are deterministic and do
     not depend on worker timing.

4. In-process smoke coverage.
   - Create a temporary user, settings row, FASTA, signature job, search job, and
     watched result.
   - Patch only external command boundaries, then exercise the real task/service
     code for signature creation, search result saving, job progress, status
     reconciliation, filter/sort updates, downloads, and watch execution.

5. Full Docker/Celery smoke coverage.
   - Recreate an isolated dev stack with Redis, MongoDB, Django, Celery workers,
     and Celery beat.
   - Run migrations.
   - Confirm the web service and Celery workers are reachable.
   - Create a real tiny FASTA record.
   - Run `create_signature` through the interactive worker.
   - Build a real sourmash index from the generated signature through
     `create_index`.
   - Run `create_search` through the interactive worker and verify a result file
     and completed job.
   - Toggle the result as watched and run `create_watch`.

6. Optional network maintenance smoke.
   - For release candidates, run a small WORT-backed download/index command with
     known test accessions and low limits.
   - Keep this separate from the normal gate because it depends on external
     service availability and can be slower or flaky.

## Script

Use:

```bash
./scripts/test-changeset-against-main.sh --quick
./scripts/test-changeset-against-main.sh --baseline --quick
ALLOW_STACK_RECREATE=1 ./scripts/test-changeset-against-main.sh --full
```

The quick suite is safe for normal development. The full suite uses isolated
host-side data directories under `work/changeset-test/`, but the Compose files
use fixed container names and ports, so it must be allowed to recreate the local
`mgwatch` containers.

## Release Gate

Before merging the changeset, the minimum recommended gate is:

```bash
./scripts/test-changeset-against-main.sh --baseline --quick
ALLOW_STACK_RECREATE=1 ./scripts/test-changeset-against-main.sh --full
```

The run passes only if the quick suite passes on `main`, the quick suite passes
on the current branch, and the current branch passes the full Docker/Celery
smoke suite.
