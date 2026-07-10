import tempfile
from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from mgw_api.models import Fasta
from mgw_api.models import Job
from mgw_api.services.exceptions import JobConflictError
from mgw_api.services.jobs import create_signature_pipeline_job

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CELERY_TASK_ALWAYS_EAGER=True)
class JobStatusViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")
        self.client.login(username="owner", password="testpass123")
        self.fasta = Fasta.objects.create(
            user=self.user,
            name="example",
            size=1,
            processed=False,
            status="Searching indexes 1/3",
            result_pk=None,
            file="user_1/example.fa",
        )

    def test_check_status_includes_progress_fields(self):
        Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.RUNNING,
            status_message="Searching indexes 1/3",
            progress_current=1,
            progress_total=3,
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
        )

        response = self.client.get(
            reverse("mgw_api:check_status", kwargs={"fasta_id": self.fasta.pk})
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["state"], Job.State.RUNNING)
        self.assertEqual(payload["current"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["percent"], 33)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, CELERY_TASK_TIME_LIMIT=10)
class JobReconciliationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")
        self.fasta = Fasta.objects.create(
            user=self.user,
            name="example",
            size=1,
            processed=False,
            status="Queued",
            result_pk=None,
            file="user_1/example.fa",
        )

    def test_stale_running_job_is_failed_before_creating_replacement(self):
        active_job = Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.RUNNING,
            status_message="Searching indexes 1/3",
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
            celery_task_id="task-123",
        )
        stale_at = timezone.now() - timedelta(seconds=120)
        Job.objects.filter(pk=active_job.pk).update(
            created_at=stale_at,
            started_at=stale_at,
        )

        with patch("mgw_api.services.jobs.current_app.AsyncResult") as async_result:
            async_result.return_value = Mock(state="STARTED")
            replacement = create_signature_pipeline_job(
                fasta=self.fasta,
                queue="interactive",
            )

        active_job.refresh_from_db()
        self.assertEqual(active_job.state, Job.State.FAILED)
        self.assertIn("exceeded the liveness window", active_job.error_message)
        self.assertNotEqual(active_job.pk, replacement.pk)
        self.assertEqual(replacement.state, Job.State.QUEUED)

    def test_recent_running_job_still_conflicts(self):
        active_job = Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.RUNNING,
            status_message="Searching indexes 1/3",
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
            celery_task_id="task-123",
        )
        recent_at = timezone.now() - timedelta(seconds=5)
        Job.objects.filter(pk=active_job.pk).update(
            created_at=recent_at,
            started_at=recent_at,
        )

        with patch("mgw_api.services.jobs.current_app.AsyncResult") as async_result:
            async_result.return_value = Mock(state="STARTED")
            with self.assertRaises(JobConflictError):
                create_signature_pipeline_job(
                    fasta=self.fasta,
                    queue="interactive",
                )

        active_job.refresh_from_db()
        self.assertEqual(active_job.state, Job.State.RUNNING)
