from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.database_config import get_database_configs


class DatabaseConfigValidationTests(SimpleTestCase):
    def load_config(self, profile_fragment, database_fragment=""):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            (config_dir / "database.yml").write_text(
                f"""
version: 1
databases:
  sra_metagenomes:
    enabled: true
    mongodb_collection: sra_metagenomes_metadata
    wort_manifest_url: https://example.test/manifest.parquet
    wort_signature_endpoint: https://example.test/signatures
{database_fragment}
    profiles:
{profile_fragment}
""",
                encoding="utf-8",
            )
            with override_settings(CONFIG_DIR=config_dir):
                get_database_configs.cache_clear()
                try:
                    return get_database_configs()
                finally:
                    get_database_configs.cache_clear()

    def test_accepts_supported_profile_values(self):
        configs = self.load_config(
            """
      - kmer: 21
        scaled: 1000
        moltype: dna
        enabled: true
"""
        )

        profile = configs["sra_metagenomes"].enabled_profiles[0]
        self.assertEqual(profile.kmer, 21)
        self.assertEqual(profile.scaled, 1000)
        self.assertEqual(profile.moltype, "DNA")

    def test_rejects_unsupported_profile_kmer(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "Unsupported profile kmer"):
            self.load_config(
                """
      - kmer: 17
        scaled: 1000
        moltype: DNA
        enabled: true
"""
            )

    def test_rejects_unsupported_profile_scaled(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Unsupported profile scaled",
        ):
            self.load_config(
                """
      - kmer: 21
        scaled: 2000
        moltype: DNA
        enabled: true
"""
            )

    def test_rejects_unsupported_profile_moltype(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Unsupported profile moltype",
        ):
            self.load_config(
                """
      - kmer: 21
        scaled: 1000
        moltype: protein
        enabled: true
"""
            )

    def test_rejects_librarysource_excluded_by_metadata_importer_allowlist(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured,
            "Unsupported metadata filter librarysource",
        ):
            self.load_config(
                """
      - kmer: 21
        scaled: 1000
        moltype: DNA
        enabled: true
""",
                database_fragment="""
    metadata_filter:
      include:
        librarysource: OTHER
""",
            )

    def test_accepts_librarysource_supported_by_metadata_importer_allowlist(self):
        configs = self.load_config(
            """
      - kmer: 21
        scaled: 1000
        moltype: DNA
        enabled: true
""",
            database_fragment="""
    metadata_filter:
      include:
        librarysource: metagenomic
""",
        )

        self.assertEqual(
            configs["sra_metagenomes"].metadata_filter["include"]["librarysource"],
            "METAGENOMIC",
        )
