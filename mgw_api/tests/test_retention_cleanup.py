import os
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone

from mgw.settings import LOGGER
from mgw_api.models import Fasta
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.services.retention import run_retention_cleanup
from mgw_api.tasks import run_retention_cleanup_task


class RetentionCleanupTests(TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.media_root = self.temp_dir / "media"
        self.data_dir = self.temp_dir / "data"
        self.log_dir = self.temp_dir / "logs"
        self.media_root.mkdir()
        self.data_dir.mkdir()
        self.log_dir.mkdir()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_root,
            DATA_DIR=self.data_dir,
            LOG_DIR=self.log_dir,
            RETENTION_UNWATCHED_RESULTS_DAYS=180,
            RETENTION_WATCHED_RESULTS_DAYS=365,
            RETENTION_SIGNATURES_DAYS=180,
            RETENTION_UNPROCESSED_FASTA_DAYS=7,
            RETENTION_COMPLETED_JOBS_DAYS=180,
            RETENTION_FAILED_JOBS_DAYS=90,
            RETENTION_TEMP_FILES_DAYS=7,
            RETENTION_FAILED_INDEX_FILES_DAYS=30,
            RETENTION_LOG_FILES_DAYS=180,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.user = User.objects.create_user(username="owner", password="testpass123")

    def _media_file(self, relative_path, content=b"content"):
        path = self.media_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return relative_path

    def _data_file(self, relative_path, *, age_days):
        path = self.data_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")
        self._set_mtime(path, age_days=age_days)
        return path

    def _log_file(self, filename, *, age_days):
        path = self.log_dir / filename
        path.write_text("log content")
        self._set_mtime(path, age_days=age_days)
        return path

    def _set_mtime(self, path, *, age_days):
        timestamp = (timezone.now() - timedelta(days=age_days)).timestamp()
        os.utime(path, (timestamp, timestamp))

    def _set_model_time(self, model, field, *, age_days):
        value = timezone.now() - timedelta(days=age_days)
        model.__class__.objects.filter(pk=model.pk).update(**{field: value})
        setattr(model, field, value)

    def _signature(self, name, *, age_days, file_path=None):
        signature = Signature.objects.create(
            user=self.user,
            name=name,
            file=file_path or self._media_file(f"user_{self.user.pk}/{name}.sig"),
        )
        self._set_model_time(signature, "date", age_days=age_days)
        return signature

    def _result(self, name, signature, *, age_days, watched=False, file_path=None):
        result = Result.objects.create(
            user=self.user,
            name=name,
            signature=signature,
            file=file_path or self._media_file(f"user_{self.user.pk}/{name}.csv"),
            num_results=1,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
            is_watched=watched,
        )
        self._set_model_time(result, "time", age_days=age_days)
        return result

    def test_dry_run_reports_expired_data_without_deleting_or_logging_paths(self):
        signature = self._signature("sensitive-signature", age_days=200)
        result = self._result(
            "sensitive-result",
            signature,
            age_days=200,
            watched=False,
        )

        with self.assertLogs(LOGGER.name, level="INFO") as captured_logs:
            summary = run_retention_cleanup(dry_run=True)

        self.assertEqual(summary["unwatched_results"], 1)
        self.assertTrue(Result.objects.filter(pk=result.pk).exists())
        self.assertTrue((self.media_root / result.file.name).exists())
        log_output = "\n".join(captured_logs.output)
        self.assertIn("unwatched_results", log_output)
        self.assertNotIn(result.file.name, log_output)
        self.assertNotIn(signature.file.name, log_output)

    def test_apply_deletes_expired_objects_and_preserves_protected_data(self):
        expired_signature = self._signature("expired", age_days=220)
        expired_result_date = "20240101-010101-000001"
        expired_result = self._result(
            "expired-result",
            expired_signature,
            age_days=220,
            watched=False,
            file_path=self._media_file(
                f"user_{self.user.pk}/result_expired-result.{expired_result_date}.csv"
            ),
        )
        expired_result_shard = self.media_root / self._media_file(
            "user_"
            f"{self.user.pk}/result_expired-result.SRA-21-38-{expired_result_date}.csv"
        )
        fresh_result_shard = self.media_root / self._media_file(
            "user_"
            f"{self.user.pk}/result_expired-result.SRA-21-38-20260701-010101-000001.csv"
        )
        fresh_signature = self._signature("fresh", age_days=220)
        fresh_result = self._result(
            "fresh-result",
            fresh_signature,
            age_days=10,
            watched=False,
        )
        watched_signature = self._signature("watched", age_days=220)
        watched_result = self._result(
            "watched-result",
            watched_signature,
            age_days=220,
            watched=True,
        )
        orphaned_signature = self._signature("orphaned", age_days=220)
        stale_fasta = Fasta.objects.create(
            user=self.user,
            name="stale-fasta",
            file=self._media_file(f"user_{self.user.pk}/stale.fa"),
            size=10,
            processed=False,
        )
        self._set_model_time(stale_fasta, "upload_date", age_days=10)
        active_fasta = Fasta.objects.create(
            user=self.user,
            name="active-fasta",
            file=self._media_file(f"user_{self.user.pk}/active.fa"),
            size=10,
            processed=False,
        )
        self._set_model_time(active_fasta, "upload_date", age_days=10)
        active_job = Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.RUNNING,
            user=self.user,
            fasta=active_fasta,
        )
        old_completed_job = Job.objects.create(
            job_type=Job.JobType.SEARCH,
            state=Job.State.COMPLETED,
            user=self.user,
        )
        self._set_model_time(old_completed_job, "finished_at", age_days=200)
        fresh_failed_job = Job.objects.create(
            job_type=Job.JobType.SEARCH,
            state=Job.State.FAILED,
            user=self.user,
        )
        self._set_model_time(fresh_failed_job, "finished_at", age_days=10)
        stale_temp = self._data_file("tmp/stale.tmp", age_days=10)
        fresh_temp = self._data_file("tmp/fresh.tmp", age_days=1)
        stale_failed_index = self._data_file(
            "SRA/metagenomes/indexing-failed/stale.sig",
            age_days=45,
        )
        stale_log = self._log_file("2026_01_01.log", age_days=200)
        non_log = self._log_file("keep.txt", age_days=200)

        summary = run_retention_cleanup(dry_run=False)

        self.assertEqual(summary["unwatched_results"], 1)
        self.assertEqual(summary["result_shard_files"], 1)
        self.assertEqual(summary["orphaned_signatures"], 2)
        self.assertEqual(summary["unprocessed_fastas"], 1)
        self.assertEqual(summary["completed_jobs"], 1)
        self.assertEqual(summary["failed_jobs"], 0)
        self.assertFalse(Result.objects.filter(pk=expired_result.pk).exists())
        self.assertFalse(Signature.objects.filter(pk=expired_signature.pk).exists())
        self.assertFalse(Signature.objects.filter(pk=orphaned_signature.pk).exists())
        self.assertFalse(Fasta.objects.filter(pk=stale_fasta.pk).exists())
        self.assertFalse(Job.objects.filter(pk=old_completed_job.pk).exists())
        self.assertFalse((self.media_root / expired_result.file.name).exists())
        self.assertFalse(expired_result_shard.exists())
        self.assertTrue(fresh_result_shard.exists())
        self.assertFalse((self.media_root / expired_signature.file.name).exists())
        self.assertFalse((self.media_root / orphaned_signature.file.name).exists())
        self.assertFalse((self.media_root / stale_fasta.file.name).exists())
        self.assertTrue(Result.objects.filter(pk=fresh_result.pk).exists())
        self.assertTrue(Signature.objects.filter(pk=fresh_signature.pk).exists())
        self.assertTrue(Result.objects.filter(pk=watched_result.pk).exists())
        self.assertTrue(Signature.objects.filter(pk=watched_signature.pk).exists())
        self.assertTrue(Fasta.objects.filter(pk=active_fasta.pk).exists())
        self.assertTrue(Job.objects.filter(pk=active_job.pk).exists())
        self.assertTrue(Job.objects.filter(pk=fresh_failed_job.pk).exists())
        self.assertFalse(stale_temp.exists())
        self.assertTrue(fresh_temp.exists())
        self.assertFalse(stale_failed_index.exists())
        self.assertFalse(stale_log.exists())
        self.assertTrue(non_log.exists())

    def test_management_command_defaults_to_dry_run(self):
        signature = self._signature("command", age_days=220)
        result = self._result("command-result", signature, age_days=220)

        call_command("cleanup_retention")

        self.assertTrue(Result.objects.filter(pk=result.pk).exists())

        call_command("cleanup_retention", "--apply")

        self.assertFalse(Result.objects.filter(pk=result.pk).exists())

    @override_settings(RETENTION_CLEANUP_ENABLED=False)
    def test_retention_task_skips_when_disabled(self):
        result = run_retention_cleanup_task()

        self.assertEqual(result, {"skipped": True})

    def test_retention_task_uses_cleanup_service_when_enabled(self):
        with (
            override_settings(RETENTION_CLEANUP_ENABLED=True),
            patch("mgw_api.tasks.acquire_lock"),
            patch("mgw_api.services.retention.run_retention_cleanup") as cleanup,
        ):
            cleanup.return_value = {"unwatched_results": 0}

            result = run_retention_cleanup_task()

        self.assertEqual(result, {"unwatched_results": 0})
        cleanup.assert_called_once_with(dry_run=False)

    def test_retention_task_is_scheduled_after_daily_pipeline(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["daily-retention-cleanup"]

        self.assertEqual(schedule["task"], "mgw_api.tasks.run_retention_cleanup_task")
        self.assertEqual(schedule["options"], {"queue": "maintenance"})

    def test_daily_pipeline_is_scheduled_by_celery_beat(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["daily-maintenance-pipeline"]

        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)
        self.assertEqual(schedule["task"], "mgw_api.tasks.run_daily_pipeline_task")
        self.assertEqual(schedule["options"], {"queue": "maintenance"})
        self.assertEqual(schedule["schedule"]._orig_minute, 0)
        self.assertEqual(schedule["schedule"]._orig_hour, 1)
