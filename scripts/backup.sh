#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/backup.sh [BACKUP_PARENT_DIR]

Creates a timestamped MetagenomeWatch backup directory. The script reads host
paths from .env by default. Override these inputs with:

  COMPOSE_FILE=compose.prod.yml
  MGWATCH_ENV_FILE=.env
  MGWATCH_VARS_FILE=vars.env
  MGWATCH_SKIP_POSTGRES_BACKUP=True
  MGWATCH_SKIP_MONGO_BACKUP=True

Run it from the deployment directory that contains the compose and env files.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

backup_parent=${1:-./backups}
compose_file=${COMPOSE_FILE:-compose.yml}
env_file=${MGWATCH_ENV_FILE:-.env}
vars_file=${MGWATCH_VARS_FILE:-vars.env}
timestamp=$(date -u +"%Y%m%dT%H%M%SZ")
backup_dir="${backup_parent%/}/mgwatch-${timestamp}"

mkdir -p "$backup_dir"/{config,archives}

if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
fi

: "${EXTERNAL_DATA_DIR:=./work/data}"
: "${NGINX_DATA_DIR:=./work/nginx}"
: "${LOG_DIR:=./work/django-logs}"

compose_args=()
if [[ -f "$env_file" ]]; then
    compose_args+=(--env-file "$env_file")
fi
compose_args+=(-f "$compose_file")

docker_compose() {
    docker compose "${compose_args[@]}" "$@"
}

is_truthy() {
    case "${1:-}" in
        1 | true | TRUE | True | yes | YES | Yes)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

copy_if_exists() {
    local source=$1
    local destination=$2
    if [[ -e "$source" ]]; then
        cp -a "$source" "$destination"
    fi
}

archive_dir_if_exists() {
    local source=$1
    local archive=$2
    if [[ -d "$source" ]]; then
        tar -C "$(dirname "$source")" -czf "$archive" "$(basename "$source")"
    fi
}

python_bin=$(command -v python3 || command -v python)

read_env_value() {
    local file=$1
    local key=$2
    [[ -f "$file" ]] || return 0
    "$python_bin" - "$file" "$key" <<'PY'
import shlex
import sys

file_path, requested_key = sys.argv[1:3]
for line in open(file_path, encoding="utf-8"):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    if key.strip() != requested_key:
        continue
    parts = shlex.split(value, comments=False)
    if parts:
        print(parts[0])
    break
PY
}

copy_if_exists "$env_file" "$backup_dir/config/"
copy_if_exists "$vars_file" "$backup_dir/config/"
copy_if_exists "$compose_file" "$backup_dir/config/"
copy_if_exists nginx-templates "$backup_dir/config/"
copy_if_exists example-config/nginx-templates "$backup_dir/config/"

archive_dir_if_exists "${EXTERNAL_DATA_DIR%/}/backend-data" "$backup_dir/archives/backend-data.tar.gz"
archive_dir_if_exists "$LOG_DIR" "$backup_dir/archives/logs.tar.gz"
archive_dir_if_exists "$NGINX_DATA_DIR" "$backup_dir/archives/nginx-data.tar.gz"

postgres_db=${POSTGRES_DB:-}
postgres_user=${POSTGRES_USER:-}
if [[ -z "$postgres_db" ]]; then
    postgres_db=$(read_env_value "$vars_file" POSTGRES_DB)
fi
if [[ -z "$postgres_user" ]]; then
    postgres_user=$(read_env_value "$vars_file" POSTGRES_USER)
fi
postgres_db=${postgres_db:-mgwatch}
postgres_user=${postgres_user:-mgwatch}

if is_truthy "${MGWATCH_SKIP_POSTGRES_BACKUP:-}"; then
    printf 'WARN: MGWATCH_SKIP_POSTGRES_BACKUP is set; skipped PostgreSQL dump\n' >&2
elif docker_compose ps --status running --services | grep -qx mgwatch-postgres; then
    docker_compose exec -T mgwatch-postgres pg_dump \
        --format custom \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --username "$postgres_user" \
        --dbname "$postgres_db" \
        > "$backup_dir/postgres.dump"
else
    printf 'WARN: mgwatch-postgres is not running; skipped PostgreSQL dump\n' >&2
fi

mongo_password=${MGWATCH_MONGO_ROOT_PASSWORD:-}
if [[ -z "$mongo_password" && -f "$vars_file" ]]; then
    mongo_password=$("$python_bin" - "$vars_file" <<'PY'
import shlex
import sys
from urllib.parse import unquote, urlsplit

for line in open(sys.argv[1], encoding="utf-8"):
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        continue
    key, value = stripped.split("=", 1)
    if key.strip() == "MONGO_URI":
        parts = shlex.split(value, comments=False)
        if parts:
            print(unquote(urlsplit(parts[0]).password or ""))
        break
PY
)
fi
mongo_password=${mongo_password:-example1}

if is_truthy "${MGWATCH_SKIP_MONGO_BACKUP:-}"; then
    printf 'WARN: MGWATCH_SKIP_MONGO_BACKUP is set; skipped MongoDB dump\n' >&2
elif docker_compose ps --status running --services | grep -qx mgwatch-mongodb; then
    docker_compose exec -T mgwatch-mongodb mongodump \
        --archive \
        --gzip \
        --username root \
        --password "$mongo_password" \
        --authenticationDatabase admin \
        > "$backup_dir/mongodb.archive.gz"
else
    printf 'WARN: mgwatch-mongodb is not running; skipped MongoDB dump\n' >&2
fi

{
    printf 'created_at_utc=%s\n' "$timestamp"
    printf 'compose_file=%s\n' "$compose_file"
    printf 'env_file=%s\n' "$env_file"
    printf 'vars_file=%s\n' "$vars_file"
    printf 'postgres_service=mgwatch-postgres\n'
    printf 'postgres_database=%s\n' "$postgres_db"
    printf 'backend_data_source=%s\n' "${EXTERNAL_DATA_DIR%/}/backend-data"
    printf 'log_source=%s\n' "$LOG_DIR"
    printf 'nginx_data_source=%s\n' "$NGINX_DATA_DIR"
    printf '\nfiles:\n'
    find "$backup_dir" -type f -printf '%P\t%s bytes\n' | sort
} > "$backup_dir/MANIFEST.txt"

printf 'Backup written to %s\n' "$backup_dir"
