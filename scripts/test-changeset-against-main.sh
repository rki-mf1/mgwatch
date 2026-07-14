#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/test-changeset-against-main.sh [--quick] [--full] [--baseline] [--skip-build]

Options:
  --quick       Run build/config/Django tests and in-process smoke checks.
  --full        Run --quick plus an end-to-end Docker/Celery smoke suite.
  --baseline    Run the quick suite on BASE_REF first, then on the current tree.
  --skip-build  Reuse the existing mgwatch:local image.
  -h, --help    Show this help text.

Environment:
  BASE_REF=main             Git ref to compare against.
  ALLOW_STACK_RECREATE=1    Required for --full because compose uses fixed names.
  KEEP_STACK=1              Leave the full smoke compose stack running.
USAGE
}

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BASE_REF=${BASE_REF:-main}
RUN_QUICK=0
RUN_FULL=0
RUN_BASELINE=0
SKIP_BUILD=0
KEEP_STACK=${KEEP_STACK:-0}
ALLOW_STACK_RECREATE=${ALLOW_STACK_RECREATE:-0}
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_ROOT="$REPO_ROOT/work/changeset-test/$TIMESTAMP"
SUMMARY="$RUN_ROOT/summary.log"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick)
      RUN_QUICK=1
      ;;
    --full)
      RUN_QUICK=1
      RUN_FULL=1
      ;;
    --baseline)
      RUN_BASELINE=1
      ;;
    --skip-build)
      SKIP_BUILD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "$RUN_QUICK" -eq 0 && "$RUN_FULL" -eq 0 ]]; then
  RUN_QUICK=1
fi

mkdir -p "$RUN_ROOT"

if [[ "$RUN_BASELINE" -eq 1 && "$SKIP_BUILD" -eq 1 ]]; then
  echo "--baseline cannot be combined with --skip-build because it must test two different code images." >&2
  exit 2
fi

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$SUMMARY"
}

die() {
  log "ERROR: $*"
  exit 1
}

bootstrap_env_file() {
  local source=$1
  local target=$2

  if [[ -f "$target" ]]; then
    return 0
  fi

  [[ -f "$source" ]] || die "Cannot create $(basename "$target"); missing $(basename "$source")"
  cp "$source" "$target"
  log "Created $(basename "$target") from $(basename "$source")"
}

bootstrap_env_files() {
  bootstrap_env_file "$REPO_ROOT/.env.template" "$REPO_ROOT/.env"
  bootstrap_env_file "$REPO_ROOT/vars.env.example" "$REPO_ROOT/vars.env"
}

resolve_base_ref() {
  if git -C "$REPO_ROOT" rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$BASE_REF" == origin/* ]]; then
    local remote_branch=${BASE_REF#origin/}
    if git -C "$REPO_ROOT" fetch --no-tags --prune origin \
      "refs/heads/$remote_branch:refs/remotes/origin/$remote_branch" >/dev/null 2>&1 &&
      git -C "$REPO_ROOT" rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1; then
      return 0
    fi
  fi

  if [[ "$BASE_REF" != origin/* ]] &&
    git -C "$REPO_ROOT" fetch --no-tags --prune origin \
      "refs/heads/$BASE_REF:refs/remotes/origin/$BASE_REF" >/dev/null 2>&1; then
    if git -C "$REPO_ROOT" rev-parse --verify "origin/$BASE_REF^{commit}" >/dev/null 2>&1; then
      BASE_REF="origin/$BASE_REF"
      log "Resolved base ref to $BASE_REF"
      return 0
    fi
  fi

  die "BASE_REF '$BASE_REF' does not resolve"
}

sanitize_label() {
  printf '%s' "$1" | tr -c '[:alnum:]_.-' '-'
}

run_logged() {
  local label=$1
  local step=$2
  shift 2
  local suite_dir="$RUN_ROOT/$label"
  local log_dir="$suite_dir/logs"
  local safe_step
  safe_step=$(sanitize_label "$step")
  mkdir -p "$log_dir"
  log "[$label] $step"
  if "$@" > >(tee "$log_dir/$safe_step.log") 2>&1; then
    log "[$label] PASS: $step"
  else
    log "[$label] FAIL: $step"
    return 1
  fi
}

compose_cmd() {
  local repo_dir=$1
  shift
  docker compose \
    --project-directory "$repo_dir" \
    -f "$repo_dir/compose.yml" \
    -f "$repo_dir/compose-dev.yml" \
    "$@"
}

compose_env_args() {
  local suite_dir=$1
  local project=$2
  printf '%s\0' \
    "COMPOSE_PROJECT_NAME=$project" \
    "EXTERNAL_DATA_DIR=$suite_dir/data" \
    "MONGODB_DATA_DIR=$suite_dir/mongo" \
    "MONGODB_LOG_DIR=$suite_dir/mongo-logs" \
    "SQLITE_DIR=$suite_dir/db" \
    "NGINX_DATA_DIR=$suite_dir/nginx" \
    "LOG_DIR=$suite_dir/django-logs"
}

compose_run_no_deps() {
  local repo_dir=$1
  local label=$2
  local command=$3
  local suite_dir="$RUN_ROOT/$label"
  local project="mgwatch-${label//[^a-zA-Z0-9]/-}"
  mkdir -p "$suite_dir"/{data/backend-data,db,django-logs,smoke}
  chmod -R ugo+rwX "$suite_dir"/{data,db,django-logs}

  mapfile -d '' env_args < <(compose_env_args "$suite_dir" "$project")
  (
    export "${env_args[@]}"
    compose_cmd "$repo_dir" run --rm --no-deps \
      -e DATA_DIR=/data \
      -e DB_DIR=/data-db \
      -e LOG_DIR=/logs \
      -e DEBUG=True \
      -e LOG_LEVEL=DEBUG \
      -e AXES_ENABLED=False \
      -e CELERY_TASK_ALWAYS_EAGER=True \
      -e CELERY_TASK_EAGER_PROPAGATES=True \
      -e REDIS_URL=redis://mgwatch-redis:6379/0 \
      -e MONGO_URI=mongodb://root:example1@mgwatch-mongodb:27017/ \
      -v "$repo_dir/scripts:/code/scripts:ro" \
      -v "$repo_dir/example-config:/code/example-config:ro" \
      -v "$suite_dir/smoke:/smoke:ro" \
      mgwatch "$command"
  )
}

compose_down_quick() {
  local repo_dir=$1
  local label=$2
  local suite_dir="$RUN_ROOT/$label"
  local project="mgwatch-${label//[^a-zA-Z0-9]/-}"

  mapfile -d '' env_args < <(compose_env_args "$suite_dir" "$project")
  (
    export "${env_args[@]}"
    compose_cmd "$repo_dir" down --remove-orphans
  )
}

write_quick_smoke() {
  local smoke_file=$1
  cat > "$smoke_file" <<'PY'
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from mgw_api.models import Fasta
from mgw_api.models import FilterSetting
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature
from mgw_api.services.maintenance import run_watch
from mgw_api.services.jobs import create_search_job
from mgw_api.tasks import run_search_task
from mgw_api.tasks import run_signature_pipeline


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def fake_signature_command(command, **kwargs):
    output = Path(command[command.index("--output") + 1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("fake sourmash signature\n", encoding="ascii")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def fake_search_index(*, result_file, sketch_file, index_path, k, containment):
    Path(result_file).write_text(
        "query_name,match_name,containment\n"
        "smoke-sequence,SRR_SMOKE,0.99\n",
        encoding="ascii",
    )


username = "changeset_smoke"
password = "testpass123"
User.objects.filter(username=username).delete()
User.objects.filter(username="changeset_smoke_other").delete()
user = User.objects.create_user(username=username, password=password, email="smoke@example.invalid")
other = User.objects.create_user(username="changeset_smoke_other", password=password)
Settings.objects.create(user=user, kmer=[21], database=["SRA"], containment=0.05)

client = Client()
response = client.get(reverse("mgw_api:upload_fasta"))
assert_true(response.status_code == 302, "anonymous upload page should redirect")
assert_true(client.login(username=username, password=password), "smoke user login failed")

for route in ["mgw_api:upload_fasta", "mgw_api:list_result", "mgw_api:list_signature", "mgw_api:settings"]:
    response = client.get(reverse(route))
    assert_true(response.status_code == 200, f"{route} returned {response.status_code}")

def fake_submit_pipeline(fasta):
    return Job.objects.create(
        job_type=Job.JobType.SIGNATURE_PIPELINE,
        state=Job.State.RUNNING,
        status_message="Creating signature",
        user=user,
        fasta=fasta,
        queue="interactive",
    )

upload = SimpleUploadedFile(
    "smoke.fa",
    b">smoke\nACGTACGTACGTACGTACGTACGT\n",
    content_type="text/plain",
)
with patch("mgw_api.views.submit_signature_pipeline_job", side_effect=fake_submit_pipeline):
    response = client.post(reverse("mgw_api:upload_fasta"), {"name": "queued-ui-smoke", "file": upload})
assert_true(response.status_code == 200, f"upload returned {response.status_code}")
payload = response.json()
assert_true(payload.get("success") is True, f"upload failed: {payload}")
fasta_id = payload["fasta_id"]
status_payload = client.get(reverse("mgw_api:check_status", kwargs={"fasta_id": fasta_id})).json()
assert_true(status_payload["state"] == Job.State.RUNNING, "status endpoint did not return running job")

response = client.post(
    reverse("mgw_api:upload_fasta"),
    {
        "name": "queued-ui-smoke",
        "file": SimpleUploadedFile("smoke2.fa", b">smoke\nACGT\n"),
    },
)
assert_true(response.json().get("success") is False, "duplicate upload should fail")

pipeline_fasta = Fasta.objects.create(
    user=user,
    name="pipeline-smoke",
    size=28,
    processed=False,
    status="Queued",
)
pipeline_fasta.file.save("pipeline-smoke.fa", ContentFile(b">smoke\nACGTACGTACGTACGTACGTACGT\n"), save=True)
index_dir = Path(settings.DATA_DIR) / "SRA" / "metagenomes" / "index"
shutil.rmtree(index_dir, ignore_errors=True)
index_dir.mkdir(parents=True, exist_ok=True)
(index_dir / "21mers-db38.rocksdb").mkdir(exist_ok=True)
pipeline_job = Job.objects.create(
    job_type=Job.JobType.SIGNATURE_PIPELINE,
    state=Job.State.QUEUED,
    status_message="Queued",
    user=user,
    fasta=pipeline_fasta,
    queue="interactive",
)
with (
    patch("mgw_api.services.signatures.run_command", side_effect=fake_signature_command),
    patch("mgw_api.services.searches.search_index", side_effect=fake_search_index),
    patch("mgw_api.services.searches.send_notification"),
):
    task_result = run_signature_pipeline.apply(
        kwargs={"job_id": pipeline_job.pk, "user_id": user.pk, "name": "pipeline-smoke"}
    ).get()

pipeline_job.refresh_from_db()
pipeline_fasta.refresh_from_db()
assert_true(pipeline_job.state == Job.State.COMPLETED, f"pipeline job state was {pipeline_job.state}")
assert_true(pipeline_fasta.status == "Complete", f"fasta status was {pipeline_fasta.status}")
assert_true(task_result["total_indexes"] == 1, f"unexpected search plan size: {task_result}")
result = Result.objects.get(pk=task_result["result_pk"])
assert_true(result.num_results == 1, f"unexpected result count: {result.num_results}")

signature = Signature.objects.get(user=user, name="pipeline-smoke")
signature.submitted = True
signature.save(update_fields=["submitted"])
search_job = create_search_job(signature=signature, queue="interactive")
with (
    patch("mgw_api.services.searches.search_index", side_effect=fake_search_index),
    patch("mgw_api.services.searches.send_notification"),
):
    second_result = run_search_task.apply(
        kwargs={
            "job_id": search_job.pk,
            "user_id": user.pk,
            "name": "pipeline-smoke",
            "watch": "False",
        }
    ).get()
search_job.refresh_from_db()
assert_true(search_job.state == Job.State.COMPLETED, f"search job state was {search_job.state}")
assert_true(Result.objects.filter(pk=second_result["result_pk"]).exists(), "search task did not create result")

result.is_watched = True
result.save(update_fields=["is_watched"])
signature.submitted = True
signature.save(update_fields=["submitted"])
with (
    patch("mgw_api.services.searches.search_index", side_effect=fake_search_index),
    patch("mgw_api.services.searches.send_notification"),
    patch("mgw_api.services.maintenance.send_watch_notification"),
):
    watch_result = run_watch()
assert_true(watch_result == {"processed_watches": 1, "failed_watches": 0}, f"watch failed: {watch_result}")

response = client.get(reverse("mgw_api:list_result"))
assert_true(response.status_code == 200, "result list failed")
assert_true(b"pipeline-smoke" in response.content, "result list missing smoke sequence")

response = client.post(
    reverse("mgw_api:toggle_watch", kwargs={"pk": result.pk}),
    {"is_watched": ""},
)
assert_true(response.status_code == 200, "toggle watch failed")

client.post(
    reverse("mgw_api:update_filters", kwargs={"pk": result.pk}),
    data=json.dumps({"column": "2", "value": "SRR"}),
    content_type="application/json",
)
client.post(
    reverse("mgw_api:update_sort", kwargs={"pk": result.pk}),
    data=json.dumps({"column": "2"}),
    content_type="application/json",
)
filters = FilterSetting.objects.get(user=user, result=result)
assert_true(filters.filters == {"2": "SRR"}, f"filters not saved: {filters.filters}")
assert_true(filters.sort_column == 2, "sort column not saved")

download = client.get(reverse("mgw_api:download_result_file", kwargs={"pk": result.pk}))
assert_true(download.status_code == 200, f"download result failed: {download.status_code}")
client.logout()
assert_true(client.login(username="changeset_smoke_other", password=password), "other user login failed")
forbidden = client.get(reverse("mgw_api:download_result_file", kwargs={"pk": result.pk}))
assert_true(forbidden.status_code == 404, f"other user download should 404, got {forbidden.status_code}")

shutil.rmtree(settings.MEDIA_ROOT / f"user_{user.pk}", ignore_errors=True)
print("quick smoke completed")
PY
}

run_quick_suite() {
  local repo_dir=$1
  local label=$2
  local include_smoke=${3:-1}
  local suite_dir="$RUN_ROOT/$label"
  mkdir -p "$suite_dir/smoke"

  run_logged "$label" "git diff stat against $BASE_REF" \
    bash -lc "cd '$repo_dir' && git diff --stat '$BASE_REF'...HEAD || true"
  run_logged "$label" "git diff names against $BASE_REF" \
    bash -lc "cd '$repo_dir' && git diff --name-status '$BASE_REF'...HEAD || true"
  run_logged "$label" "docker compose config" \
    bash -lc "cd '$repo_dir' && ./scripts/dc-dev.sh config --quiet"

  if [[ "$SKIP_BUILD" -eq 0 ]]; then
    run_logged "$label" "docker build" \
      bash -lc "cd '$repo_dir' && ./scripts/build-docker.sh"
  else
    log "[$label] SKIP: docker build"
  fi

  run_logged "$label" "Django system check" \
    compose_run_no_deps "$repo_dir" "$label" \
      "conda run --no-capture-output -n mgw ./manage.py check"
  run_logged "$label" "Django migration check" \
    compose_run_no_deps "$repo_dir" "$label" \
      "conda run --no-capture-output -n mgw ./manage.py makemigrations --check --dry-run"
  run_logged "$label" "Django unit tests" \
    compose_run_no_deps "$repo_dir" "$label" \
      "conda run --no-capture-output -n mgw ./manage.py test mgw_api --verbosity 2"

  if [[ "$include_smoke" != "1" ]]; then
    log "[$label] SKIP: in-process task and UI smoke"
    run_logged "$label" "cleanup quick compose resources" \
      compose_down_quick "$repo_dir" "$label"
    return 0
  fi

  run_logged "$label" "migrate quick smoke database" \
    compose_run_no_deps "$repo_dir" "$label" \
      "conda run --no-capture-output -n mgw ./manage.py migrate --noinput"
  write_quick_smoke "$suite_dir/smoke/quick_smoke.py"
  run_logged "$label" "in-process task and UI smoke" \
    compose_run_no_deps "$repo_dir" "$label" \
      "conda run --no-capture-output -n mgw ./manage.py shell < /smoke/quick_smoke.py"
  run_logged "$label" "cleanup quick compose resources" \
    compose_down_quick "$repo_dir" "$label"
}

stack_env() {
  local suite_dir=$1
  mapfile -d '' env_args < <(compose_env_args "$suite_dir" "mgwatch-full-smoke")
}

stack_compose() {
  local repo_dir=$1
  local suite_dir=$2
  shift 2
  stack_env "$suite_dir"
  (
    export "${env_args[@]}"
    compose_cmd "$repo_dir" "$@"
  )
}

stack_manage() {
  local repo_dir=$1
  local suite_dir=$2
  shift 2
  stack_compose "$repo_dir" "$suite_dir" exec -T mgwatch \
    conda run --no-capture-output -n mgw ./manage.py "$@"
}

stack_shell_script() {
  local repo_dir=$1
  local suite_dir=$2
  local script_path=$3
  stack_compose "$repo_dir" "$suite_dir" exec -T mgwatch \
    sh -lc "cat > /tmp/mgwatch-smoke.py && conda run --no-capture-output -n mgw ./manage.py shell < /tmp/mgwatch-smoke.py" \
    < "$script_path"
}

wait_for_http() {
  local url=$1
  for _ in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

write_full_setup() {
  local smoke_file=$1
  local username=$2
  local sequence_name=$3
  cat > "$smoke_file" <<PY
from django.contrib.auth.models import User
from django.core.files.base import ContentFile

from mgw_api.models import Fasta
from mgw_api.models import Settings

username = "$username"
sequence_name = "$sequence_name"
User.objects.filter(username=username).delete()
user = User.objects.create_user(username=username, password="testpass123", email="smoke@example.invalid")
Settings.objects.create(user=user, kmer=[21], database=["SRA"], containment=0.01)
fasta = Fasta.objects.create(
    user=user,
    name=sequence_name,
    size=64,
    processed=False,
    status="Queued",
)
fasta.file.save(
    f"{sequence_name}.fa",
    ContentFile(b">smoke\\n" + b"ACGT" * 128 + b"\\n"),
    save=True,
)
print(user.pk)
PY
}

write_full_prepare_index() {
  local smoke_file=$1
  local username=$2
  local sequence_name=$3
  cat > "$smoke_file" <<PY
import shutil
from pathlib import Path

from django.conf import settings

from mgw_api.models import Signature

signature = Signature.objects.get(user__username="$username", name="$sequence_name")
updates = Path(settings.DATA_DIR) / "SRA" / "metagenomes" / "updates"
updates.mkdir(parents=True, exist_ok=True)
shutil.copy2(signature.file.path, updates / f"{sequence_name}.sig")
print(updates / f"{sequence_name}.sig")
PY
}

write_full_verify() {
  local smoke_file=$1
  local username=$2
  local sequence_name=$3
  cat > "$smoke_file" <<PY
from django.contrib.auth.models import User

from mgw_api.models import Fasta
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Signature

user = User.objects.get(username="$username")
fasta = Fasta.objects.get(user=user, name="$sequence_name")
signature = Signature.objects.get(user=user, name="$sequence_name")
results = Result.objects.filter(user=user, signature=signature).order_by("-time")
if not results.exists():
    raise AssertionError("create_search did not create a result")
result = results.first()
if not result.file:
    raise AssertionError("search result has no file")
if result.num_results < 1:
    raise AssertionError(f"expected at least one search hit, got {result.num_results}")
if not Job.objects.filter(user=user, state=Job.State.COMPLETED).exists():
    raise AssertionError("no completed jobs found for smoke user")
if fasta.status != "Complete":
    raise AssertionError(f"fasta status is {fasta.status!r}")
result.is_watched = True
result.save(update_fields=["is_watched"])
print(result.pk)
PY
}

write_full_verify_watch() {
  local smoke_file=$1
  local username=$2
  cat > "$smoke_file" <<PY
from django.contrib.auth.models import User

from mgw_api.models import Result

user = User.objects.get(username="$username")
if not Result.objects.filter(user=user, is_watched=True).exists():
    raise AssertionError("watch result was not retained")
print("full smoke verification completed")
PY
}

run_full_suite() {
  local repo_dir=$1
  local label=full
  local suite_dir="$RUN_ROOT/$label"
  local smoke_dir="$suite_dir/smoke"
  local username="full_smoke_${TIMESTAMP//[^0-9]/}"
  local sequence_name="full-smoke-${TIMESTAMP//[^0-9]/}"
  mkdir -p "$suite_dir"/{data/backend-data,db,django-logs,mongo,mongo-logs,nginx} "$smoke_dir"

  if docker ps -a --format '{{.Names}}' | grep -Eq '^(mgwatch|mgwatch-mongodb|mgwatch-redis|mgwatch-celery-interactive|mgwatch-celery-maintenance|mgwatch-celery-beat)$'; then
    if [[ "$ALLOW_STACK_RECREATE" != "1" ]]; then
      die "--full needs to recreate fixed-name mgwatch containers. Stop the dev stack or rerun with ALLOW_STACK_RECREATE=1."
    fi
  fi

  if [[ "$SKIP_BUILD" -eq 0 ]]; then
    run_logged "$label" "docker build" \
      bash -lc "cd '$repo_dir' && ./scripts/build-docker.sh"
  fi

  cleanup_stack() {
    if [[ "$KEEP_STACK" != "1" ]]; then
      stack_compose "$repo_dir" "$suite_dir" down --remove-orphans >/dev/null 2>&1 || true
    fi
  }
  trap cleanup_stack EXIT

  run_logged "$label" "stop prior smoke stack" \
    stack_compose "$repo_dir" "$suite_dir" down --remove-orphans
  run_logged "$label" "start database services" \
    stack_compose "$repo_dir" "$suite_dir" up -d mgwatch-mongodb mgwatch-redis
  run_logged "$label" "run migrations" \
    stack_compose "$repo_dir" "$suite_dir" run --rm --no-deps mgwatch \
      "conda run --no-capture-output -n mgw ./manage.py migrate --noinput"
  run_logged "$label" "start full stack" \
    stack_compose "$repo_dir" "$suite_dir" up -d --force-recreate --remove-orphans
  run_logged "$label" "wait for web" \
    wait_for_http "http://localhost:8100/login/"
  run_logged "$label" "celery worker ping" \
    stack_compose "$repo_dir" "$suite_dir" exec -T mgwatch \
      conda run --no-capture-output -n mgw celery -A mgw inspect ping --timeout=20
  run_logged "$label" "celery active queues" \
    stack_compose "$repo_dir" "$suite_dir" exec -T mgwatch \
      conda run --no-capture-output -n mgw celery -A mgw inspect active_queues --timeout=20

  write_full_setup "$smoke_dir/full_setup.py" "$username" "$sequence_name"
  run_logged "$label" "create smoke fasta" \
    stack_shell_script "$repo_dir" "$suite_dir" "$smoke_dir/full_setup.py"
  local user_id
  user_id=$(stack_manage "$repo_dir" "$suite_dir" shell -c "from django.contrib.auth.models import User; print(User.objects.get(username='$username').pk)" | tail -n 1)

  run_logged "$label" "create signature through Celery command" \
    stack_manage "$repo_dir" "$suite_dir" create_signature "$user_id" "$sequence_name"

  write_full_prepare_index "$smoke_dir/full_prepare_index.py" "$username" "$sequence_name"
  run_logged "$label" "copy signature into update index input" \
    stack_shell_script "$repo_dir" "$suite_dir" "$smoke_dir/full_prepare_index.py"
  run_logged "$label" "create sourmash index through Celery command" \
    stack_manage "$repo_dir" "$suite_dir" create_index --index-max-signatures 1
  run_logged "$label" "create search through Celery command" \
    stack_manage "$repo_dir" "$suite_dir" create_search "$user_id" "$sequence_name" False

  write_full_verify "$smoke_dir/full_verify.py" "$username" "$sequence_name"
  run_logged "$label" "verify signature search result" \
    stack_shell_script "$repo_dir" "$suite_dir" "$smoke_dir/full_verify.py"
  run_logged "$label" "run watch command through Celery" \
    stack_manage "$repo_dir" "$suite_dir" create_watch
  write_full_verify_watch "$smoke_dir/full_verify_watch.py" "$username"
  run_logged "$label" "verify watch state" \
    stack_shell_script "$repo_dir" "$suite_dir" "$smoke_dir/full_verify_watch.py"

  cleanup_stack
  trap - EXIT
}

log "Writing logs under $RUN_ROOT"
bootstrap_env_files
resolve_base_ref

if [[ "$RUN_BASELINE" -eq 1 ]]; then
  BASE_LABEL=$(sanitize_label "$BASE_REF")
  BASE_WORKTREE="$RUN_ROOT/worktree-$BASE_LABEL"
  run_logged baseline-worktree "create $BASE_REF worktree" \
    git -C "$REPO_ROOT" worktree add --detach "$BASE_WORKTREE" "$BASE_REF"
  run_quick_suite "$BASE_WORKTREE" "baseline-$BASE_LABEL" 0
fi

if [[ "$RUN_QUICK" -eq 1 ]]; then
  run_quick_suite "$REPO_ROOT" current
fi

if [[ "$RUN_FULL" -eq 1 ]]; then
  run_full_suite "$REPO_ROOT"
fi

log "All requested changeset tests passed. Summary: $SUMMARY"
