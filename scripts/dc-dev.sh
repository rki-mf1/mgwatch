#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${EXTERNAL_DATA_DIR:=./work/data}"
: "${MONGODB_DATA_DIR:=./work/mongo}"
: "${MONGODB_LOG_DIR:=./work/mongo-logs}"
: "${SQLITE_DIR:=./work/db}"
: "${LOG_DIR:=./work/django-logs}"

mkdir -p \
    "${EXTERNAL_DATA_DIR%/}/backend-data" \
    "${EXTERNAL_DATA_DIR%/}/backend-crontabs" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$SQLITE_DIR" \
    "$LOG_DIR"
chmod -R ugo+rwX \
    "$EXTERNAL_DATA_DIR" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$SQLITE_DIR" \
    "$LOG_DIR" 2>/dev/null || true

docker compose -f compose.yml -f compose-dev.yml "$@"
