import os
import shutil
import sqlite3
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
        self.sqlite_dir = self.deploy_dir / "db"
        self.nginx_dir = self.deploy_dir / "nginx"
        self.log_dir = self.deploy_dir / "logs"
        self.compose_file = self.deploy_dir / "compose.yml"
        self.env_file = self.deploy_dir / ".env"
        self.vars_file = self.deploy_dir / "vars.env"

        for directory in (
            self.data_dir / "backend-data" / "media",
            self.sqlite_dir,
            self.nginx_dir / "static",
            self.log_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.compose_file.write_text("services: {}\n", encoding="utf-8")
        self.env_file.write_text(
            "\n".join(
                [
                    f"EXTERNAL_DATA_DIR={self.data_dir}",
                    f"SQLITE_DIR={self.sqlite_dir}",
                    f"NGINX_DATA_DIR={self.nginx_dir}",
                    f"LOG_DIR={self.log_dir}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.vars_file.write_text(
            "MONGO_URI=mongodb://root:example1@mgwatch-mongodb:27017/\n",
            encoding="utf-8",
        )

        self._write_sqlite_value("original")
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

    def test_backup_and_restore_scripts_restore_files_and_sqlite(self):
        env = {
            **os.environ,
            "COMPOSE_FILE": str(self.compose_file),
            "MGWATCH_ENV_FILE": str(self.env_file),
            "MGWATCH_VARS_FILE": str(self.vars_file),
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

        self._write_sqlite_value("mutated")
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

        self.assertEqual(self._read_sqlite_value(), "original")
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

    def _write_sqlite_value(self, value):
        with sqlite3.connect(self.sqlite_dir / "db.sqlite3") as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS backup_test (value TEXT)")
            connection.execute("DELETE FROM backup_test")
            connection.execute("INSERT INTO backup_test VALUES (?)", (value,))

    def _read_sqlite_value(self):
        with sqlite3.connect(self.sqlite_dir / "db.sqlite3") as connection:
            row = connection.execute("SELECT value FROM backup_test").fetchone()
        return row[0]

    def _backup_dir_from_output(self, stdout):
        prefix = "Backup written to "
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return Path(line.removeprefix(prefix))
        self.fail(f"backup output did not include backup directory: {stdout}")
