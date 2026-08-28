#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if [[ ! -f .env ]]; then
    cp .env.template .env
fi

if [[ ! -f vars.env ]]; then
    cp vars.env.example vars.env
fi

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${EXTERNAL_DATA_DIR:=./work/data}"
: "${POSTGRES_DATA_DIR:=./work/postgres}"
: "${MONGODB_DATA_DIR:=./work/mongo}"
: "${MONGODB_LOG_DIR:=./work/mongo-logs}"
: "${LOG_DIR:=./work/django-logs}"
: "${TZ:=Europe/Berlin}"
: "${DOCKER_POSTGRES_IMAGE:=postgres:18-alpine}"
: "${DOCKER_MONGODB_IMAGE:=mongo:8.2.3-noble}"

export EXTERNAL_DATA_DIR
export POSTGRES_DATA_DIR
export MONGODB_DATA_DIR
export MONGODB_LOG_DIR
export LOG_DIR
export TZ
export DOCKER_POSTGRES_IMAGE
export DOCKER_MONGODB_IMAGE

mkdir -p \
    "${EXTERNAL_DATA_DIR%/}/backend-data" \
    "$POSTGRES_DATA_DIR" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$LOG_DIR"
chmod -R ugo+rwX \
    "$EXTERNAL_DATA_DIR" \
    "$POSTGRES_DATA_DIR" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$LOG_DIR" 2>/dev/null || true

docker compose -f compose.yml -f compose-dev.yml "$@"
