import importlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings

from mgw_api.models import Result
from mgw_api.models import Settings
from mgw_api.models import Signature


class SuspendUnsupportedWatchesMigrationTests(TestCase):
    def write_database_config(self, config_dir, *, enabled_kmers):
        profiles = "\n".join(
            f"""      - kmer: {kmer}
        scaled: 1000
        moltype: DNA
        enabled: true"""
            for kmer in enabled_kmers
        )
        (config_dir / "database.yml").write_text(
            f"""
version: 1
databases:
  sra_metagenomes:
    enabled: true
    label: SRA Metagenomes
    mongodb_collection: sra_metagenomes_metadata
    wort_manifest_url: https://example.test/sra-manifest.parquet
    wort_signature_endpoint: https://example.test/sra-signatures
    profiles:
{profiles}
""",
            encoding="utf-8",
        )

    def write_disjoint_database_config(self, config_dir):
        (config_dir / "database.yml").write_text(
            """
version: 1
databases:
  sra_metagenomes:
    enabled: true
    label: SRA Metagenomes
    mongodb_collection: sra_metagenomes_metadata
    wort_manifest_url: https://example.test/sra-manifest.parquet
    wort_signature_endpoint: https://example.test/sra-signatures
    profiles:
      - kmer: 21
        scaled: 1000
        moltype: DNA
        enabled: true
  other_metagenomes:
    enabled: true
    label: Other Metagenomes
    mongodb_collection: other_metagenomes_metadata
    wort_manifest_url: https://example.test/other-manifest.parquet
    wort_signature_endpoint: https://example.test/other-signatures
    profiles:
      - kmer: 31
        scaled: 1000
        moltype: DNA
        enabled: true
""",
            encoding="utf-8",
        )

    def test_suspends_watches_with_any_disabled_kmer(self):
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
        mixed = Result.objects.create(
            user=user,
            name="mixed",
            signature=signature,
            kmer=["21", "31"],
            database=["sra_metagenomes"],
            is_watched=True,
        )
        supported = Result.objects.create(
            user=user,
            name="supported",
            signature=signature,
            kmer=["21"],
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
        mixed.refresh_from_db()
        supported.refresh_from_db()
        already_unwatched.refresh_from_db()
        self.assertFalse(unsupported.is_watched)
        self.assertFalse(mixed.is_watched)
        self.assertTrue(supported.is_watched)
        self.assertFalse(already_unwatched.is_watched)

    def test_preserves_watches_with_configured_enabled_kmers(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        user = User.objects.create_user(username="configured", password="testpass123")
        signature = Signature.objects.create(
            user=user,
            name="query",
            file="user_1/query.sig",
        )
        configured = Result.objects.create(
            user=user,
            name="configured",
            signature=signature,
            kmer=["31"],
            database=["sra_metagenomes"],
            is_watched=True,
        )
        unsupported = Result.objects.create(
            user=user,
            name="unsupported",
            signature=signature,
            kmer=["21"],
            database=["sra_metagenomes"],
            is_watched=True,
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            self.write_database_config(config_dir, enabled_kmers=[31])
            with override_settings(CONFIG_DIR=config_dir):
                migration.suspend_unsupported_watches(apps, None)

        configured.refresh_from_db()
        unsupported.refresh_from_db()
        self.assertTrue(configured.is_watched)
        self.assertFalse(unsupported.is_watched)

    def test_suspends_watches_using_kmers_unsupported_by_saved_database(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        user = User.objects.create_user(
            username="saved-database", password="testpass123"
        )
        signature = Signature.objects.create(
            user=user,
            name="query",
            file="user_1/query.sig",
        )
        unsupported_for_saved_database = Result.objects.create(
            user=user,
            name="unsupported-for-saved-database",
            signature=signature,
            kmer=["31"],
            database=["sra_metagenomes"],
            is_watched=True,
        )
        supported_for_saved_database = Result.objects.create(
            user=user,
            name="supported-for-saved-database",
            signature=signature,
            kmer=["31"],
            database=["other_metagenomes"],
            is_watched=True,
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            self.write_disjoint_database_config(config_dir)
            with override_settings(CONFIG_DIR=config_dir):
                migration.suspend_unsupported_watches(apps, None)

        unsupported_for_saved_database.refresh_from_db()
        supported_for_saved_database.refresh_from_db()
        self.assertFalse(unsupported_for_saved_database.is_watched)
        self.assertTrue(supported_for_saved_database.is_watched)

    def test_normalizes_settings_with_disabled_kmers(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        unsupported_user = User.objects.create_user(
            username="unsupported-settings", password="testpass123"
        )
        mixed_user = User.objects.create_user(
            username="mixed-settings", password="testpass123"
        )
        supported_user = User.objects.create_user(
            username="supported-settings", password="testpass123"
        )
        string_mixed_user = User.objects.create_user(
            username="string-mixed-settings", password="testpass123"
        )
        unsupported = Settings.objects.create(
            user=unsupported_user,
            kmer=[31],
            database=["sra_metagenomes"],
        )
        mixed = Settings.objects.create(
            user=mixed_user,
            kmer=[21, 31],
            database=["sra_metagenomes"],
        )
        supported = Settings.objects.create(
            user=supported_user,
            kmer=[21],
            database=["sra_metagenomes"],
        )
        string_mixed = Settings.objects.create(
            user=string_mixed_user,
            kmer=["21", "51"],
            database=["sra_metagenomes"],
        )

        migration.normalize_unsupported_settings(apps, None)

        unsupported.refresh_from_db()
        mixed.refresh_from_db()
        supported.refresh_from_db()
        string_mixed.refresh_from_db()
        self.assertEqual(unsupported.kmer, [21])
        self.assertEqual(mixed.kmer, [21])
        self.assertEqual(supported.kmer, [21])
        self.assertEqual(string_mixed.kmer, ["21"])

    def test_normalizes_settings_to_configured_enabled_kmer(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        unsupported_user = User.objects.create_user(
            username="configured-unsupported-settings", password="testpass123"
        )
        supported_user = User.objects.create_user(
            username="configured-supported-settings", password="testpass123"
        )
        unsupported = Settings.objects.create(
            user=unsupported_user,
            kmer=[21],
            database=["sra_metagenomes"],
        )
        supported = Settings.objects.create(
            user=supported_user,
            kmer=[31],
            database=["sra_metagenomes"],
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            self.write_database_config(config_dir, enabled_kmers=[31])
            with override_settings(CONFIG_DIR=config_dir):
                migration.normalize_unsupported_settings(apps, None)

        unsupported.refresh_from_db()
        supported.refresh_from_db()
        self.assertEqual(unsupported.kmer, [31])
        self.assertEqual(supported.kmer, [31])

    def test_normalizes_settings_against_saved_database_profiles(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        sra_user = User.objects.create_user(
            username="sra-only-settings", password="testpass123"
        )
        other_user = User.objects.create_user(
            username="other-only-settings", password="testpass123"
        )
        sra_settings = Settings.objects.create(
            user=sra_user,
            kmer=[31],
            database=["sra_metagenomes"],
        )
        other_settings = Settings.objects.create(
            user=other_user,
            kmer=[31],
            database=["other_metagenomes"],
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            self.write_disjoint_database_config(config_dir)
            with override_settings(CONFIG_DIR=config_dir):
                migration.normalize_unsupported_settings(apps, None)

        sra_settings.refresh_from_db()
        other_settings.refresh_from_db()
        self.assertEqual(sra_settings.kmer, [21])
        self.assertEqual(other_settings.kmer, [31])

    def test_normalizes_settings_with_no_shared_profile_to_first_saved_database(self):
        migration = importlib.import_module(
            "mgw_api.migrations.0040_suspend_unsupported_watches"
        )
        user = User.objects.create_user(
            username="disjoint-settings", password="testpass123"
        )
        settings = Settings.objects.create(
            user=user,
            kmer=[31],
            database=["sra_metagenomes", "other_metagenomes"],
        )

        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            self.write_disjoint_database_config(config_dir)
            with override_settings(CONFIG_DIR=config_dir):
                migration.normalize_unsupported_settings(apps, None)

        settings.refresh_from_db()
        self.assertEqual(settings.database, ["sra_metagenomes"])
        self.assertEqual(settings.kmer, [21])
