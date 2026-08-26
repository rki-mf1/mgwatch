#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/restore.sh --force BACKUP_DIR

Restores a backup created by scripts/backup.sh. The script reads host paths from
.env by default, falling back to the backed-up .env if the current file is
missing. Override these inputs with:

  COMPOSE_FILE=compose.prod.yml
  MGWATCH_ENV_FILE=.env
  MGWATCH_VARS_FILE=vars.env
  MGWATCH_SKIP_POSTGRES_RESTORE=True
  MGWATCH_SKIP_MONGO_RESTORE=True

Run it from the deployment directory that contains the compose and env files.
The --force flag is required because restore overwrites local application state.
EOF
}

force=0
backup_dir=

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help)
            usage
            exit 0
            ;;
        --force)
            force=1
            shift
            ;;
        *)
            if [[ -n "$backup_dir" ]]; then
                usage >&2
                exit 2
            fi
            backup_dir=$1
            shift
            ;;
    esac
done

if [[ "$force" -ne 1 || -z "$backup_dir" ]]; then
    usage >&2
    exit 2
fi

if [[ ! -d "$backup_dir" ]]; then
    printf 'ERROR: backup directory not found: %s\n' "$backup_dir" >&2
    exit 1
fi

compose_file=${COMPOSE_FILE:-compose.yml}
env_file=${MGWATCH_ENV_FILE:-.env}
vars_file=${MGWATCH_VARS_FILE:-vars.env}

backup_config_file() {
    local target=$1
    local basename_target
    basename_target=$(basename "$target")
    if [[ -f "$backup_dir/config/$basename_target" ]]; then
        printf '%s\n' "$backup_dir/config/$basename_target"
    fi
}

source_env_file=$env_file
if [[ ! -f "$source_env_file" ]]; then
    source_env_file=$(backup_config_file "$env_file" || true)
fi

if [[ -n "${source_env_file:-}" && -f "$source_env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$source_env_file"
    set +a
fi

: "${EXTERNAL_DATA_DIR:=./work/data}"
: "${NGINX_DATA_DIR:=./work/nginx}"
: "${LOG_DIR:=./work/django-logs}"

compose_args=()
if [[ -f "$env_file" ]]; then
    compose_args+=(--env-file "$env_file")
elif [[ -n "$(backup_config_file "$env_file" || true)" ]]; then
    compose_args+=(--env-file "$(backup_config_file "$env_file")")
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

restore_config_file() {
    local target=$1
    local source
    source=$(backup_config_file "$target" || true)
    if [[ -n "$source" ]]; then
        mkdir -p "$(dirname "$target")"
        cp -a "$source" "$target"
    fi
}

restore_archive() {
    local archive=$1
    local target=$2
    local extract_dir extracted_top

    if [[ ! -f "$archive" ]]; then
        return 0
    fi

    extract_dir=$(mktemp -d "${TMPDIR:-/tmp}/mgwatch-restore.XXXXXX")
    tar -C "$extract_dir" -xzf "$archive"
    extracted_top=$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d -print -quit)
    if [[ -z "$extracted_top" ]]; then
        rm -rf "$extract_dir"
        printf 'ERROR: archive did not contain a top-level directory: %s\n' "$archive" >&2
        exit 1
    fi

    mkdir -p "$(dirname "$target")"
    rm -rf "$target"
    mv "$extracted_top" "$target"
    rm -rf "$extract_dir"
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

restore_postgres() {
    local source_dump="$backup_dir/postgres.dump"
    local postgres_db postgres_user
    if [[ ! -f "$source_dump" ]]; then
        printf 'WARN: PostgreSQL backup not found at %s; skipped PostgreSQL restore\n' "$source_dump" >&2
        return 0
    fi
    if is_truthy "${MGWATCH_SKIP_POSTGRES_RESTORE:-}"; then
        printf 'WARN: MGWATCH_SKIP_POSTGRES_RESTORE is set; skipped PostgreSQL restore\n' >&2
        return 0
    fi
    if ! docker_compose ps --status running --services | grep -qx mgwatch-postgres; then
        printf 'WARN: mgwatch-postgres is not running; skipped PostgreSQL restore\n' >&2
        return 0
    fi

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

    docker_compose exec -T mgwatch-postgres pg_restore \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --username "$postgres_user" \
        --dbname "$postgres_db" \
        < "$source_dump"
}

restore_postgres
restore_archive "$backup_dir/archives/backend-data.tar.gz" "${EXTERNAL_DATA_DIR%/}/backend-data"
restore_archive "$backup_dir/archives/logs.tar.gz" "$LOG_DIR"
restore_archive "$backup_dir/archives/nginx-data.tar.gz" "$NGINX_DATA_DIR"
restore_config_file "$env_file"
restore_config_file "$vars_file"
restore_config_file "$compose_file"

if [[ -d "$backup_dir/config/nginx-templates" ]]; then
    nginx_template_dir=${NGINX_TEMPLATE_DIR:-nginx-templates}
    rm -rf "$nginx_template_dir"
    cp -a "$backup_dir/config/nginx-templates" "$nginx_template_dir"
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

if [[ ! -f "$backup_dir/mongodb.archive.gz" ]]; then
    printf 'WARN: MongoDB backup archive not found; skipped MongoDB restore\n' >&2
elif is_truthy "${MGWATCH_SKIP_MONGO_RESTORE:-}"; then
    printf 'WARN: MGWATCH_SKIP_MONGO_RESTORE is set; skipped MongoDB restore\n' >&2
elif docker_compose ps --status running --services | grep -qx mgwatch-mongodb; then
    docker_compose exec -T mgwatch-mongodb mongorestore \
        --drop \
        --archive \
        --gzip \
        --username root \
        --password "$mongo_password" \
        --authenticationDatabase admin \
        < "$backup_dir/mongodb.archive.gz"
else
    printf 'WARN: mgwatch-mongodb is not running; skipped MongoDB restore\n' >&2
fi

printf 'Restore completed from %s\n' "$backup_dir"
