import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

from django.conf import settings


class BackupRestoreScriptTests(TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.deploy_dir = self.tmpdir / "deploy"
        self.backup_parent = self.tmpdir / "backups"
        self.data_dir = self.deploy_dir / "data"
        self.postgres_dir = self.deploy_dir / "postgres"
        self.nginx_dir = self.deploy_dir / "nginx"
        self.log_dir = self.deploy_dir / "logs"
        self.compose_file = self.deploy_dir / "compose.yml"
        self.env_file = self.deploy_dir / ".env"
        self.vars_file = self.deploy_dir / "vars.env"
        self.fake_bin_dir = self.tmpdir / "bin"
        self.restored_postgres_dump = self.deploy_dir / "restored-postgres.dump"

        for directory in (
            self.data_dir / "backend-data" / "media",
            self.postgres_dir,
            self.nginx_dir / "static",
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self._write_fake_docker()
        self.compose_file.write_text("services: {}\n", encoding="utf-8")
        self.env_file.write_text(
            "\n".join(
                [
                    f"EXTERNAL_DATA_DIR={self.data_dir}",
                    f"POSTGRES_DATA_DIR={self.postgres_dir}",
                    f"NGINX_DATA_DIR={self.nginx_dir}",
                    f"LOG_DIR={self.log_dir}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.vars_file.write_text(
            "\n".join(
                [
                    "MONGO_URI=mongodb://root:example1@mgwatch-mongodb:27017/",
                    "POSTGRES_DB=mgwatch",
                    "POSTGRES_USER=mgwatch",
                    "POSTGRES_PASSWORD=example1",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        (self.data_dir / "backend-data" / "media" / "sequence.fa").write_text(
            ">seq\nACGT\n",
            encoding="utf-8",
        )
        (self.nginx_dir / "static" / "app.css").write_text(
            "body { color: black; }\n",
            encoding="utf-8",
        )
        (self.log_dir / "app.log").write_text("original log\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backup_and_restore_scripts_restore_files_and_postgres(self):
        env = {
            **os.environ,
            "COMPOSE_FILE": str(self.compose_file),
            "MGWATCH_ENV_FILE": str(self.env_file),
            "MGWATCH_VARS_FILE": str(self.vars_file),
            "PATH": f"{self.fake_bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_POSTGRES_DUMP_CONTENT": "postgres backup original\n",
            "FAKE_POSTGRES_RESTORE_OUTPUT": str(self.restored_postgres_dump),
            "MGWATCH_SKIP_MONGO_BACKUP": "True",
            "MGWATCH_SKIP_MONGO_RESTORE": "True",
        }

        backup_result = subprocess.run(
            [str(settings.BASE_DIR / "scripts" / "backup.sh"), str(self.backup_parent)],
            cwd=settings.BASE_DIR,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        backup_dir = self._backup_dir_from_output(backup_result.stdout)

        shutil.rmtree(self.data_dir / "backend-data")
        shutil.rmtree(self.nginx_dir)
        shutil.rmtree(self.log_dir)
        self.compose_file.write_text("services:\n  broken: {}\n", encoding="utf-8")

        subprocess.run(
            [
                str(settings.BASE_DIR / "scripts" / "restore.sh"),
                "--force",
                str(backup_dir),
            ],
            cwd=settings.BASE_DIR,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertEqual(
            (backup_dir / "postgres.dump").read_text(encoding="utf-8"),
            "postgres backup original\n",
        )
        self.assertEqual(
            self.restored_postgres_dump.read_text(encoding="utf-8"),
            "postgres backup original\n",
        )
        self.assertEqual(
            (self.data_dir / "backend-data" / "media" / "sequence.fa").read_text(
                encoding="utf-8"
            ),
            ">seq\nACGT\n",
        )
        self.assertEqual(
            (self.nginx_dir / "static" / "app.css").read_text(encoding="utf-8"),
            "body { color: black; }\n",
        )
        self.assertEqual(
            (self.log_dir / "app.log").read_text(encoding="utf-8"),
            "original log\n",
        )
        self.assertEqual(
            self.compose_file.read_text(encoding="utf-8"),
            "services: {}\n",
        )
        self.assertTrue((backup_dir / "MANIFEST.txt").is_file())

    def _write_fake_docker(self):
        self.fake_bin_dir.mkdir(parents=True, exist_ok=True)
        fake_docker = self.fake_bin_dir / "docker"
        fake_docker.write_text(
            """#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "compose" ]]; then
    printf 'unsupported docker command: %s\\n' "$*" >&2
    exit 1
fi
shift

while [[ "${1:-}" == "--env-file" || "${1:-}" == "-f" ]]; do
    shift 2
done

case "${1:-}" in
    ps)
        printf 'mgwatch-postgres\\n'
        ;;
    exec)
        shift
        if [[ "${1:-}" == "-T" ]]; then
            shift
        fi
        service=${1:-}
        shift
        if [[ "$service" == "mgwatch-postgres" && "${1:-}" == "pg_dump" ]]; then
            printf '%s' "${FAKE_POSTGRES_DUMP_CONTENT:?}"
        elif [[ "$service" == "mgwatch-postgres" && "${1:-}" == "pg_restore" ]]; then
            cat > "${FAKE_POSTGRES_RESTORE_OUTPUT:?}"
        else
            printf 'unsupported docker compose exec: %s %s\\n' "$service" "$*" >&2
            exit 1
        fi
        ;;
    *)
        printf 'unsupported docker compose command: %s\\n' "$*" >&2
        exit 1
        ;;
esac
""",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)

    def _backup_dir_from_output(self, stdout):
        prefix = "Backup written to "
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return Path(line.removeprefix(prefix))
        raise AssertionError(
            f"backup output did not include backup directory: {stdout}"
        )
