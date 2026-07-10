import tempfile
from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from mgw_api.models import Fasta
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Signature
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

    def test_job_status_fragment_renders_htmx_polling_markup(self):
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
            reverse("mgw_api:job_status", kwargs={"fasta_id": self.fasta.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-trigger="every 5s"')
        self.assertContains(
            response,
            reverse("mgw_api:job_status", kwargs={"fasta_id": self.fasta.pk}),
        )
        self.assertContains(response, "Searching indexes 1/3")
        self.assertContains(response, 'value="33"', html=False)

    def test_job_status_fragment_refreshes_when_job_is_terminal(self):
        Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.COMPLETED,
            status_message="Complete",
            progress_current=3,
            progress_total=3,
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
        )

        response = self.client.get(
            reverse("mgw_api:job_status", kwargs={"fasta_id": self.fasta.pk})
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Refresh"], "true")

    def test_upload_returns_bookmarkable_search_result_url(self):
        upload = SimpleUploadedFile(
            "query.fasta",
            b">query\nACGTACGT\n",
            content_type="text/plain",
        )

        with patch("mgw_api.views.submit_signature_pipeline_job"):
            response = self.client.post(
                reverse("mgw_api:upload_fasta"),
                {"name": "query", "file": upload},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        fasta = Fasta.objects.get(user=self.user, name="query")
        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["result_url"],
            reverse("mgw_api:search_result", kwargs={"fasta_id": fasta.pk}),
        )

    def test_search_result_page_shows_active_job_progress_at_stable_url(self):
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
            reverse("mgw_api:search_result", kwargs={"fasta_id": self.fasta.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Search: example")
        self.assertContains(response, "Searching indexes 1/3")
        self.assertContains(response, "(1/3)")
        self.assertContains(response, 'value="33"', html=False)
        self.assertContains(response, 'hx-trigger="every 5s"')

    def test_search_result_page_renders_result_without_redirect_after_completion(self):
        signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example.sig",
        )
        result = Result.objects.create(
            user=self.user,
            name="example",
            signature=signature,
            file="",
            num_results=0,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        self.fasta.result_pk = result.pk
        self.fasta.status = "Complete"
        self.fasta.save(update_fields=["result_pk", "status"])

        url = reverse("mgw_api:search_result", kwargs={"fasta_id": self.fasta.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], url)
        self.assertContains(response, "Name: example")
        self.assertContains(response, "This search found zero results")

    def test_search_result_htmx_poll_swaps_to_result_content_when_complete(self):
        signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example.sig",
        )
        result = Result.objects.create(
            user=self.user,
            name="example",
            signature=signature,
            file="",
            num_results=0,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        self.fasta.result_pk = result.pk
        self.fasta.status = "Complete"
        self.fasta.save(update_fields=["result_pk", "status"])

        response = self.client.get(
            reverse("mgw_api:search_result", kwargs={"fasta_id": self.fasta.pk}),
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Name: example")
        self.assertNotContains(response, "<html")

    def test_results_page_shows_active_search_job_progress(self):
        signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example.sig",
        )
        Result.objects.create(
            user=self.user,
            name="example",
            signature=signature,
            file="user_1/example.csv",
            num_results=7,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        Job.objects.create(
            job_type=Job.JobType.SEARCH,
            state=Job.State.RUNNING,
            status_message="Searching indexes 1/3",
            progress_current=1,
            progress_total=3,
            user=self.user,
            signature=signature,
            fasta=self.fasta,
            queue="interactive",
        )

        response = self.client.get(reverse("mgw_api:list_result"))

        self.assertContains(response, "Current search")
        self.assertContains(response, "Searching indexes 1/3")
        self.assertContains(response, "(1/3)")
        self.assertContains(response, 'hx-trigger="every 5s"')
        self.assertContains(response, 'value="33"', html=False)

    def test_results_page_shows_active_signature_pipeline_without_completed_results(
        self,
    ):
        Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.RUNNING,
            status_message="Creating signature",
            progress_current=0,
            progress_total=0,
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
        )

        response = self.client.get(reverse("mgw_api:list_result"))

        self.assertContains(response, "Sequence name: example")
        self.assertContains(response, "Current search")
        self.assertContains(response, "Creating signature")


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
