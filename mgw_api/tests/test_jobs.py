import tempfile

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from mgw_api.models import Fasta
from mgw_api.models import Job

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
