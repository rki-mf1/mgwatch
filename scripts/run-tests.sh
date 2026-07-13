#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

skip_build=0
django_args=()

for arg in "$@"; do
    case "$arg" in
        --skip-build)
            skip_build=1
            ;;
        *)
            django_args+=("$arg")
            ;;
    esac
done

if [[ "${#django_args[@]}" -eq 0 ]]; then
    django_args=(mgw_api)
fi

if [[ ! -f .env ]]; then
    cp .env.template .env
fi

if [[ ! -f vars.env ]]; then
    cp vars.env.example vars.env
fi

test_root=$(mktemp -d "${TMPDIR:-/tmp}/mgwatch-tests.XXXXXX")
test_project_suffix=$(basename "$test_root" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')
export COMPOSE_PROJECT_NAME="mgwatch-tests-${test_project_suffix}"
export EXTERNAL_DATA_DIR="$test_root/data"
export MONGODB_DATA_DIR="$test_root/mongo"
export MONGODB_LOG_DIR="$test_root/mongo-logs"
export SQLITE_DIR="$test_root/db"
export NGINX_DATA_DIR="$test_root/nginx"
export LOG_DIR="$test_root/django-logs"

mkdir -p \
    "$EXTERNAL_DATA_DIR/backend-data" \
    "$EXTERNAL_DATA_DIR/backend-crontabs" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$SQLITE_DIR" \
    "$NGINX_DATA_DIR" \
    "$LOG_DIR"
chmod -R ugo+rwX "$test_root"

cleanup() {
    docker compose -f compose.yml down --remove-orphans
    rm -rf "$test_root" 2>/dev/null || true
}
trap cleanup EXIT

if [[ "$skip_build" -eq 0 ]]; then
    ./scripts/build-docker.sh
fi

test_volumes=(
    --volume "$repo_root/scripts:/code/scripts:ro"
)

if [[ -d example-config ]]; then
    test_volumes+=(--volume "$repo_root/example-config:/code/example-config:ro")
fi

docker compose -f compose.yml up -d mgwatch-mongodb
docker compose -f compose.yml run --rm --entrypoint conda \
    -e DEBUG=True \
    -e LOG_LEVEL=DEBUG \
    -e AXES_ENABLED=False \
    "${test_volumes[@]}" mgwatch \
    run --no-capture-output -n mgw ./manage.py test "${django_args[@]}"
