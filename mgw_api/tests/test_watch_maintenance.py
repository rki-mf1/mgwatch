import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings

from mgw.settings import LOGGER
from mgw_api.models import Fasta
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.services.maintenance import run_watch

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class RunWatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")
        self.fasta = Fasta.objects.create(
            user=self.user,
            name="example",
            size=1,
            processed=True,
            status="Complete",
            result_pk=None,
            file="user_1/example.fa",
        )

        self.bad_signature = Signature.objects.create(
            user=self.user,
            name="bad-watch",
            fasta=self.fasta,
            size=1,
        )
        self.bad_signature.file.save(
            "bad.sig",
            ContentFile(b"bad-signature"),
            save=True,
        )
        self.good_signature = Signature.objects.create(
            user=self.user,
            name="good-watch",
            fasta=self.fasta,
            size=1,
        )
        self.good_signature.file.save(
            "good.sig",
            ContentFile(b"good-signature"),
            save=True,
        )

        self.bad_result = Result.objects.create(
            user=self.user,
            name="bad-watch",
            signature=self.bad_signature,
            num_results=1,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
            is_watched=True,
        )
        self.bad_result.file.save(
            "bad.csv",
            ContentFile(b"col\nold\n"),
            save=True,
        )
        self.good_result = Result.objects.create(
            user=self.user,
            name="good-watch",
            signature=self.good_signature,
            num_results=1,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
            is_watched=True,
        )
        self.good_result.file.save(
            "good.csv",
            ContentFile(b"col\nold\n"),
            save=True,
        )

    def test_run_watch_continues_after_per_watch_failure(self):
        call_order = []

        def fake_search_watch(name, user_id, watch_pk):
            call_order.append(watch_pk)
            if watch_pk == self.bad_result.pk:
                raise FileNotFoundError("missing signature")
            return self.good_result

        with self.assertLogs(LOGGER.name, level="ERROR") as captured_logs:
            with (
                patch(
                    "mgw_api.services.maintenance.search_watch",
                    side_effect=fake_search_watch,
                ),
                patch(
                    "mgw_api.services.maintenance.compare_results", return_value=True
                ),
            ):
                result = run_watch()

        self.assertEqual(call_order, [self.bad_result.pk, self.good_result.pk])
        self.assertEqual(
            result,
            {
                "processed_watches": 1,
                "failed_watches": 1,
            },
        )
        self.bad_signature.refresh_from_db()
        self.good_signature.refresh_from_db()
        self.assertTrue(self.bad_signature.submitted)
        self.assertTrue(self.good_signature.submitted)
        self.assertIn(
            "Watch run failed for result_pk=",
            "\n".join(captured_logs.output),
        )
