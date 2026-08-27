#!/usr/bin/env bash

set -e

FIXTURES_DIR=mgw_api/fixtures/dev
mkdir -p "$FIXTURES_DIR"
scripts/dev-manage.sh dumpdata auth.user --indent 4 > "$FIXTURES_DIR/users.json"
scripts/dev-manage.sh dumpdata mgw_api --indent 4 | gzip > "$FIXTURES_DIR/data.json.gz"
