from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.database_config import get_database_configs
from mgw_api.tasks import run_daily_pipeline_task


@dataclass
class AppliedTaskResult:
    payload: dict

    def get(self):
        return self.payload


def write_database_config(config_dir):
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


class DailyPipelineTests(SimpleTestCase):
    def test_daily_pipeline_refreshes_each_enabled_database_before_watches(self):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            write_database_config(config_dir)
            applied_calls = []

            def record_apply(task_name):
                def apply(*, kwargs):
                    applied_calls.append((task_name, kwargs))
                    return AppliedTaskResult({"task": task_name, "kwargs": kwargs})

                return apply

            with (
                override_settings(CONFIG_DIR=config_dir),
                patch(
                    "mgw_api.tasks.run_metadata_task.apply",
                    side_effect=record_apply("metadata"),
                ),
                patch(
                    "mgw_api.tasks.run_downloads_task.apply",
                    side_effect=record_apply("downloads"),
                ),
                patch(
                    "mgw_api.tasks.run_index_task.apply",
                    side_effect=record_apply("index"),
                ),
                patch(
                    "mgw_api.tasks.run_watch_task.apply",
                    side_effect=record_apply("watches"),
                ),
            ):
                get_database_configs.cache_clear()
                try:
                    result = run_daily_pipeline_task()
                finally:
                    get_database_configs.cache_clear()

        self.assertEqual(
            applied_calls,
            [
                ("metadata", {"database": "sra_metagenomes"}),
                ("downloads", {"database": "sra_metagenomes"}),
                ("index", {"database": "sra_metagenomes"}),
                ("metadata", {"database": "other_metagenomes"}),
                ("downloads", {"database": "other_metagenomes"}),
                ("index", {"database": "other_metagenomes"}),
                ("watches", {}),
            ],
        )
        self.assertEqual(
            result["databases"]["sra_metagenomes"]["metadata"]["kwargs"],
            {"database": "sra_metagenomes"},
        )
        self.assertEqual(
            result["databases"]["other_metagenomes"]["index"]["kwargs"],
            {"database": "other_metagenomes"},
        )
        self.assertEqual(result["watches"], {"task": "watches", "kwargs": {}})
