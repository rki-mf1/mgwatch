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
from mgw_api.models import FilterSetting
from mgw_api.models import Job
from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature
from mgw_api.services.exceptions import JobConflictError
from mgw_api.services.jobs import create_signature_pipeline_job
from mgw_api.tasks import run_signature_pipeline

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

    def test_upload_saves_submitted_settings(self):
        upload = SimpleUploadedFile(
            "query.fasta",
            b">query\nACGTACGT\n",
            content_type="text/plain",
        )

        with patch("mgw_api.views.submit_signature_pipeline_job"):
            response = self.client.post(
                reverse("mgw_api:upload_fasta"),
                {
                    "name": "query",
                    "file": upload,
                    "kmer": ["31"],
                    "database": ["SRA"],
                    "containment": "0.25",
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        settings = Settings.objects.get(user=self.user)
        self.assertEqual(settings.kmer, ["31"])
        self.assertEqual(settings.database, ["SRA"])
        self.assertEqual(settings.containment, 0.25)

    def test_upload_page_includes_compact_advanced_filters(self):
        response = self.client.get(reverse("mgw_api:upload_fasta"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Advanced filters")
        self.assertContains(response, "Choose metadata field")
        self.assertContains(response, 'data-operator="date"')
        self.assertLess(
            response.content.index(b"Upload Genome"),
            response.content.index(b"Settings"),
        )
        self.assertLess(
            response.content.index(b"Settings"),
            response.content.index(b"Advanced filters"),
        )

    def test_upload_saves_initial_advanced_filter_spec(self):
        upload = SimpleUploadedFile(
            "query.fasta",
            b">query\nACGTACGT\n",
            content_type="text/plain",
        )

        with patch("mgw_api.views.submit_signature_pipeline_job"):
            response = self.client.post(
                reverse("mgw_api:upload_fasta"),
                {
                    "name": "query",
                    "file": upload,
                    "in__geo_loc_name_country_calc": "Canada",
                    "min__releasedate": "2024-01-01",
                    "max__releasedate": "2024-12-31",
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        fasta = Fasta.objects.get(user=self.user, name="query")
        self.assertEqual(
            fasta.initial_filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada"],
                    },
                    {
                        "field": "releasedate",
                        "operator": "range",
                        "include_missing": False,
                        "min": "2024-01-01",
                        "max": "2024-12-31",
                    },
                ],
            },
        )

    def test_signature_pipeline_copies_initial_filters_to_result(self):
        self.fasta.initial_filter_spec = {
            "version": 1,
            "rules": [
                {
                    "field": "geo_loc_name_country_calc",
                    "operator": "contains",
                    "include_missing": False,
                    "value": "Canada",
                }
            ],
        }
        self.fasta.save(update_fields=["initial_filter_spec"])
        signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example.sig",
        )
        job = Job.objects.create(
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state=Job.State.QUEUED,
            status_message="Queued",
            user=self.user,
            fasta=self.fasta,
            queue="interactive",
        )

        def fake_run_search(**_kwargs):
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
            return {"result_pk": result.pk}

        with (
            patch("mgw_api.tasks.create_signature"),
            patch("mgw_api.tasks.run_search", side_effect=fake_run_search),
        ):
            run_signature_pipeline.apply(
                kwargs={
                    "job_id": job.pk,
                    "user_id": self.user.pk,
                    "name": "example",
                }
            ).get()

        result = Result.objects.get(signature=signature)
        filter_setting = FilterSetting.objects.get(user=self.user, result=result)
        self.assertEqual(filter_setting.filter_spec, self.fasta.initial_filter_spec)

    def test_upload_failure_does_not_expose_exception_details(self):
        upload = SimpleUploadedFile(
            "query.fasta",
            b">query\nACGTACGT\n",
            content_type="text/plain",
        )

        with (
            patch(
                "mgw_api.views.submit_signature_pipeline_job",
                side_effect=RuntimeError("internal /srv/app/path failed"),
            ),
            self.assertLogs("mgw_api.views", level="ERROR") as logs,
        ):
            response = self.client.post(
                reverse("mgw_api:upload_fasta"),
                {"name": "query", "file": upload},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(
            payload["error"],
            "Error: file submission failed. Please try again later.",
        )
        self.assertNotIn("/srv/app/path", payload["error"])
        self.assertIn("/srv/app/path", "\n".join(logs.output))

    def test_signature_submission_failure_does_not_expose_exception_details(self):
        signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example.sig",
        )

        with (
            patch(
                "mgw_api.views.submit_search_job",
                side_effect=RuntimeError("SQL select from private_table failed"),
            ),
            self.assertLogs("mgw_api.views", level="ERROR") as logs,
        ):
            response = self.client.post(
                reverse("mgw_api:list_result"),
                {"signature_id": signature.pk},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(
            payload["error"],
            "Error: file submission failed. Please try again later.",
        )
        self.assertNotIn("private_table", payload["error"])
        self.assertIn("private_table", "\n".join(logs.output))

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

    def test_results_page_preserves_results_for_duplicate_signature_names(self):
        first_signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example-1.sig",
        )
        second_signature = Signature.objects.create(
            user=self.user,
            name="example",
            fasta=self.fasta,
            file="user_1/example-2.sig",
        )
        Result.objects.create(
            user=self.user,
            name="example",
            signature=first_signature,
            file="user_1/example-1.csv",
            num_results=7,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        Result.objects.create(
            user=self.user,
            name="example",
            signature=second_signature,
            file="user_1/example-2.csv",
            num_results=9,
            kmer=[31],
            database=["SRA"],
            containment=0.1,
        )

        response = self.client.get(reverse("mgw_api:list_result"))

        self.assertContains(response, "Sequence name: example", count=1)
        self.assertContains(response, "<td>7</td>", html=True)
        self.assertContains(response, "<td>9</td>", html=True)

    def test_results_page_shows_saved_filter_labels(self):
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
            file="user_1/example.csv",
            num_results=7,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        FilterSetting.objects.create(
            user=self.user,
            result=result,
            filter_spec={
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    }
                ]
            },
        )

        response = self.client.get(reverse("mgw_api:list_result"))

        self.assertContains(response, "<th>Filters</th>", html=True)
        self.assertContains(response, "Country: Canada")

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
