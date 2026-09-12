import importlib

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase

from mgw_api.models import Result
from mgw_api.models import Signature


class SuspendUnsupportedWatchesMigrationTests(TestCase):
    def test_suspends_watches_with_no_enabled_kmer(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        user = User.objects.create_user(username="owner", password="testpass123")
        signature = Signature.objects.create(
            user=user,
            name="query",
            file="user_1/query.sig",
        )
        unsupported = Result.objects.create(
            user=user,
            name="unsupported",
            signature=signature,
            kmer=["31"],
            database=["sra_metagenomes"],
            is_watched=True,
        )
        supported = Result.objects.create(
            user=user,
            name="supported",
            signature=signature,
            kmer=["21", "31"],
            database=["sra_metagenomes"],
            is_watched=True,
        )
        already_unwatched = Result.objects.create(
            user=user,
            name="already-unwatched",
            signature=signature,
            kmer=["51"],
            database=["sra_metagenomes"],
            is_watched=False,
        )

        migration.suspend_unsupported_watches(apps, None)

        unsupported.refresh_from_db()
        supported.refresh_from_db()
        already_unwatched.refresh_from_db()
        self.assertFalse(unsupported.is_watched)
        self.assertTrue(supported.is_watched)
        self.assertFalse(already_unwatched.is_watched)
