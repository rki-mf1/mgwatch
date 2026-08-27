#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

skip_build=0
django_args=()
coverage_enabled=${MGWATCH_COVERAGE:-1}
coverage_fail_under=${COVERAGE_FAIL_UNDER:-}
coverage_output_dir=${COVERAGE_OUTPUT_DIR:-"$repo_root/work/coverage"}
run_full_suite=0

for arg in "$@"; do
    case "$arg" in
        --skip-build)
            skip_build=1
            ;;
        --no-coverage)
            coverage_enabled=0
            ;;
        *)
            django_args+=("$arg")
            ;;
    esac
done

if [[ "${#django_args[@]}" -eq 0 ]]; then
    django_args=(mgw_api)
    run_full_suite=1
fi

if [[ -z "$coverage_fail_under" && "$run_full_suite" -eq 1 ]]; then
    coverage_fail_under=50
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
export POSTGRES_DATA_DIR="$test_root/postgres"
export MONGODB_DATA_DIR="$test_root/mongo"
export MONGODB_LOG_DIR="$test_root/mongo-logs"
export NGINX_DATA_DIR="$test_root/nginx"
export LOG_DIR="$test_root/django-logs"

mkdir -p \
    "$EXTERNAL_DATA_DIR/backend-data" \
    "$EXTERNAL_DATA_DIR/backend-crontabs" \
    "$POSTGRES_DATA_DIR" \
    "$MONGODB_DATA_DIR" \
    "$MONGODB_LOG_DIR" \
    "$NGINX_DATA_DIR" \
    "$LOG_DIR"
chmod -R ugo+rwX "$test_root"

mkdir -p "$coverage_output_dir"
chmod ugo+rwX "$coverage_output_dir"

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
    --volume "$coverage_output_dir:/coverage-output"
)

if [[ -d example-config ]]; then
    test_volumes+=(--volume "$repo_root/example-config:/code/example-config:ro")
fi

docker compose -f compose.yml up -d mgwatch-postgres mgwatch-mongodb

if [[ "$coverage_enabled" == "1" ]]; then
    docker compose -f compose.yml run --rm --entrypoint /bin/sh \
        -e DEBUG=True \
        -e LOG_LEVEL=DEBUG \
        -e AXES_ENABLED=False \
        -e COVERAGE_FAIL_UNDER="$coverage_fail_under" \
        "${test_volumes[@]}" mgwatch \
        -c '
            set -e
            pixi run --frozen coverage erase
            pixi run --frozen coverage run --parallel-mode ./manage.py test "$@"
            pixi run --frozen coverage combine
            pixi run --frozen coverage report
            pixi run --frozen coverage xml -o /coverage-output/coverage.xml
            if [ -n "${COVERAGE_FAIL_UNDER}" ]; then
                pixi run --frozen coverage report \
                    --fail-under="${COVERAGE_FAIL_UNDER}" >/dev/null
            fi
        ' sh "${django_args[@]}"
else
    docker compose -f compose.yml run --rm --entrypoint pixi \
        -e DEBUG=True \
        -e LOG_LEVEL=DEBUG \
        -e AXES_ENABLED=False \
        "${test_volumes[@]}" mgwatch \
        run --frozen ./manage.py test "${django_args[@]}"
fi
