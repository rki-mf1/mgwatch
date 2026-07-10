import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings

TEST_MEDIA_ROOT = Path(tempfile.mkdtemp())


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class UserCleanupTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_user_delete_removes_media_directory(self):
        user = User.objects.create_user(username="owner", password="testpass123")
        user_directory = TEST_MEDIA_ROOT / f"user_{user.id}"
        nested_file = user_directory / "search" / "result.csv"
        nested_file.parent.mkdir(parents=True)
        nested_file.write_text("a,b\n1,2\n")

        user.delete()

        self.assertFalse(user_directory.exists())
