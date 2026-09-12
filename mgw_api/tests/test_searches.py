from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase
from django.test import TestCase
from django.test import override_settings

from mgw_api.database_config import get_database_configs
from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature
from mgw_api.services.exceptions import UnsupportedSearchConfiguration
from mgw_api.services.searches import get_indices
from mgw_api.services.searches import run_search


class SearchIndexDiscoveryTests(SimpleTestCase):
    def test_get_indices_ignores_disabled_database_even_when_files_exist(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_dir = root / "config"
            data_dir = root / "data"
            config_dir.mkdir()
            (config_dir / "database.yml").write_text(
                """
version: 1
databases:
  sra_metagenomes:
    enabled: true
    mongodb_collection: sra_metagenomes_metadata
    wort_manifest_url: https://example.test/manifest.parquet
    wort_signature_endpoint: https://example.test/signatures
    profiles:
      - kmer: 21
        scaled: 1000
        enabled: true
  disabled_metagenomes:
    enabled: false
    mongodb_collection: disabled_metagenomes_metadata
    wort_manifest_url: https://example.test/disabled-manifest.parquet
    wort_signature_endpoint: https://example.test/disabled-signatures
    profiles:
      - kmer: 21
        scaled: 1000
        enabled: true
""",
                encoding="utf-8",
            )
            disabled_index = (
                data_dir
                / "search-databases"
                / "disabled_metagenomes"
                / "profiles"
                / "k21-scaled1000"
                / "batch-38"
                / "index.rocksdb"
            )
            disabled_index.mkdir(parents=True)

            with override_settings(CONFIG_DIR=config_dir, DATA_DIR=data_dir):
                get_database_configs.cache_clear()
                try:
                    self.assertEqual(get_indices("21", "disabled_metagenomes"), [])
                finally:
                    get_database_configs.cache_clear()


class SearchPlanGuardTests(TestCase):
    def test_run_search_rejects_empty_plan_without_saving_result(self):
        user = User.objects.create_user(username="owner", password="testpass123")
        signature = Signature.objects.create(
            user=user,
            name="stale",
            file="user_1/stale.sig",
            submitted=True,
        )
        settings = Settings.objects.create(
            user=user,
            kmer=["31"],
            database=["sra_metagenomes"],
            containment=0.1,
        )

        with (
            patch(
                "mgw_api.services.searches.build_search_plan",
                return_value=(signature, settings, []),
            ),
            patch("mgw_api.services.searches.send_notification") as send_notification,
            patch(
                "mgw_api.services.searches.try_record_search_rate"
            ) as record_search_rate,
        ):
            with self.assertRaisesMessage(
                UnsupportedSearchConfiguration,
                "Search settings do not match any enabled indexed profile",
            ):
                run_search(user_id=user.pk, name="stale", watch="False")

        self.assertFalse(Result.objects.exists())
        signature.refresh_from_db()
        self.assertTrue(signature.submitted)
        send_notification.assert_not_called()
        record_search_rate.assert_not_called()
