import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from mgw_api.models import Result
from mgw_api.models import Signature

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class DownloadViewsTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="testpass123")
        self.other_user = User.objects.create_user(
            username="other", password="testpass123"
        )
        self.signature = Signature.objects.create(
            user=self.owner,
            name="example-signature",
            submitted=False,
        )
        self.signature.file.save(
            "example.sig", ContentFile(b"signature-bytes"), save=True
        )
        self.result = Result.objects.create(
            user=self.owner,
            name="example-result",
            signature=self.signature,
            num_results=1,
        )
        self.result.file.save("result.csv", ContentFile(b"a,b\n1,2\n"), save=True)

    def test_owner_can_download_signature_file(self):
        self.client.login(username="owner", password="testpass123")

        response = self.client.get(
            reverse("mgw_api:download_signature_file", args=[self.signature.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="example.sig"',
        )
        self.assertEqual(b"".join(response.streaming_content), b"signature-bytes")

    def test_owner_can_download_result_file(self):
        self.client.login(username="owner", password="testpass123")

        response = self.client.get(
            reverse("mgw_api:download_result_file", args=[self.result.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="result.csv"',
        )
        self.assertEqual(b"".join(response.streaming_content), b"a,b\n1,2\n")

    def test_other_user_cannot_download_owned_file(self):
        self.client.login(username="other", password="testpass123")

        response = self.client.get(
            reverse("mgw_api:download_result_file", args=[self.result.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_missing_result_file_returns_404(self):
        self.client.login(username="owner", password="testpass123")
        self.result.file.delete(save=True)

        response = self.client.get(
            reverse("mgw_api:download_result_file", args=[self.result.pk])
        )

        self.assertEqual(response.status_code, 404)
