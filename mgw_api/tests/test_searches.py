from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.database_config import get_database_configs
from mgw_api.services.searches import get_indices


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
