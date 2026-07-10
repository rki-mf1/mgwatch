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

mkdir -p \
    work/data/backend-data \
    work/data/backend-crontabs \
    work/mongo \
    work/mongo-logs \
    work/db \
    work/django-logs

cleanup() {
    docker compose -f compose.yml down --remove-orphans
}
trap cleanup EXIT

if [[ "$skip_build" -eq 0 ]]; then
    ./scripts/build-docker.sh
fi

docker compose -f compose.yml up -d mgwatch-mongodb
docker compose -f compose.yml run --rm --entrypoint conda mgwatch \
    run --no-capture-output -n mgw ./manage.py test "${django_args[@]}"
