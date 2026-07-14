# Repository Guidelines

## Project Structure & Module Organization
- Django project config lives in `mgw/` (settings, URLs, WSGI/ASGI). The main app is in `mgw_api/` with models, forms, views, templates, and static assets scoped to the app. Management commands sit in `mgw_api/management/commands/`.
- Container and orchestration assets are in `compose*.yml`, `Dockerfile`, and helper scripts under `scripts/`. Per-environment variables live in `.env` and `vars.env` (see `vars.env.example`); secrets stay out of version control.
- Development data and generated indices live under `mgw-data/` and `work/`; avoid checking these into git. Reference docs are under `docs/`; admin interface html files live in `templates/`.

## Build, Test, and Development Commands
- Build backend image: `./scripts/build-docker.sh`.
- Start/stop dev stack: `./scripts/dc-dev.sh up -d` and `./scripts/dc-dev.sh down`. `./mgw.sh -bm` rebuilds the backend, applies migrations, and restarts containers in one go.
- Run Django management tasks inside the backend container: `./scripts/dev-manage.sh <command>`, e.g., `./scripts/dev-manage.sh migrate` or `./scripts/dev-manage.sh collectstatic --no-input`.
- Load developer fixtures (users, example data): `./scripts/dev-load-fixtures.sh`. Initialize metadata and signatures for tests: `./scripts/dev-init-test-data.sh`.

## Coding Style & Naming Conventions
- Python code follows PEP 8 with 4-space indents; keep imports grouped stdlib/third-party/local (see `mgw_api/views.py`). Use descriptive, lowercase_with_underscores for functions and snake_case for fields/model attributes.
- Keep views slim; push data shaping into `mgw_api/functions.py` helpers or management commands. Favor Django templates in `mgw_api/templates/` and static assets in `mgw_api/static/`.
- HTML templates should remain lintable with `djlint` (config in `djlint.toml`); keep block/variable names consistent with existing templates.

## Testing Guidelines
- Run the suite via `./scripts/run-tests.sh` before pushing any branch. The script builds the backend image, starts the required Docker Compose services without the development port overrides, and executes `manage.py test mgw_api` in the container. To run a narrower target, pass Django test labels, e.g. `./scripts/run-tests.sh mgw_api.tests.test_jobs`.
- Install the local pre-push guard with `pre-commit install --hook-type pre-push`; it runs `./scripts/run-tests.sh` before `git push`. If Docker or the local environment prevents the test run, pause the push and report the blocker instead of bypassing the check silently.
- Prefer fixture-driven tests using existing data under `mgw_api/fixtures/`; keep large assets in `test-data/` and avoid committing generated indices.
- Until coverage targets are set, ensure new features include tests that cover success and failure paths and verify search/watch workflows manually in dev.

## Commit & Pull Request Guidelines
- Use concise, present-tense commit subjects (recent history uses short sentences like “Make wort signature downloads asynchronous”). Group related changes per commit; avoid noisy rebuild artifacts or local data.
- Pull requests should describe the change, why it’s needed, and how to verify (commands and expected outcomes). Link issues or tickets when relevant.
- Include screenshots or sample payloads for UI/API changes, note schema or migration impacts, and call out any operational steps (e.g., rerunning `create_metadata` or `create_search` commands).
- Do not use the `gh` CLI for GitHub operations in this sandbox. Its auth configuration is expected to fail; use the configured GitHub connector for issues, pull requests, comments, and repository metadata instead.
