# Code map and edit boundaries

This document clarifies where new code should live so contributors can keep
changes cohesive and easy to review.

## High-level boundaries

- `mgw/`: Django project settings/URL wiring only.
- `mgw_api/views.py`: HTTP request/response handling and minimal orchestration.
- `mgw_api/forms.py`, `mgw_api/models.py`: Django model/form definitions.
- `mgw_api/management/commands/*`: thin CLI wrappers for scheduled/operational
  entry points.
- `mgw_api/services/*`: domain workflows and reusable business logic.
- `mgw_api/tests/*`: tests grouped by feature path.

## Where to put new code

### Views

Keep views small and focused on:

- parsing request data
- permission/auth checks
- choosing template/JSON responses
- delegating workflow steps to service modules

Avoid putting long-running IO, subprocess execution, or heavy DataFrame logic
inside view functions.

### Management commands

Commands should mostly do:

- argument parsing
- high-level logging
- call one service entrypoint
- map exceptions to command exit behavior

Move operational logic into service modules so it can be reused by other
commands, tasks, and tests.

### Service modules

Service modules should contain:

- workflow orchestration
- external IO (when not specific to HTTP/CLI)
- domain-level error handling

Recommended naming pattern:

- `mgw_api/services/watch_service.py`
- `mgw_api/services/search_service.py`
- `mgw_api/services/metadata_service.py`
- `mgw_api/services/index_service.py`

### Tests

Mirror module/feature paths to keep navigation obvious. For example:

- `mgw_api/services/watch_service.py`
- `mgw_api/tests/services/test_watch_service.py`

## Refactor strategy for existing command-heavy code

1. Extract pure/helper methods from command classes into a service module.
2. Keep command CLI arguments unchanged.
3. Replace in-command logic with a single call to service functions.
4. Add/update tests at service layer first, then command-level smoke tests.
