from pathlib import Path
from tempfile import TemporaryDirectory

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.database_config import get_database_configs
from mgw_api.forms import SettingsForm


class SettingsFormDatabaseKmerCompatibilityTests(SimpleTestCase):
    def test_rejects_database_kmer_pairs_without_enabled_profile(self):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
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
        enabled: true
""",
                encoding="utf-8",
            )
            with override_settings(CONFIG_DIR=config_dir):
                get_database_configs.cache_clear()
                try:
                    form = SettingsForm(
                        data={
                            "kmer": ["21", "31"],
                            "database": ["sra_metagenomes", "other_metagenomes"],
                            "containment": "0.1",
                        }
                    )

                    self.assertFalse(form.is_valid())
                    self.assertIn(
                        "Unsupported database and k-mer combination",
                        str(form.errors),
                    )
                finally:
                    get_database_configs.cache_clear()

    def test_settings_template_shows_validation_errors_and_waits_for_submit(self):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
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
        enabled: true
""",
                encoding="utf-8",
            )
            with override_settings(CONFIG_DIR=config_dir):
                get_database_configs.cache_clear()
                try:
                    form = SettingsForm(
                        data={
                            "kmer": ["21", "31"],
                            "database": ["sra_metagenomes", "other_metagenomes"],
                            "containment": "0.1",
                        }
                    )
                    self.assertFalse(form.is_valid())

                    rendered = render_to_string(
                        "mgw_api/settings.html",
                        {
                            "settings_form": form,
                            "settings_form_owns_form": True,
                            "messages": [],
                        },
                    )
                finally:
                    get_database_configs.cache_clear()

        self.assertIn("Unsupported database and k-mer combination", rendered)
        self.assertIn("Save settings", rendered)
        self.assertNotIn("settingsForm.submit()", rendered)
        self.assertNotIn("addEventListener('change'", rendered)
