import pickle
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.test.utils import override_settings

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import get_database_config
from mgw_api.database_config import index_path
from mgw_api.database_config import profile_manifest
from mgw_api.database_config import read_accession_parquet


class MigrateDatabaseStorageTests(SimpleTestCase):
    def test_migrates_disabled_legacy_kmer_indexes_into_profile_layout(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            legacy_root = data_dir / "SRA" / "metagenomes"
            legacy_manifest_dir = legacy_root / "manifests"
            legacy_index_dir = legacy_root / "index"
            legacy_manifest_dir.mkdir(parents=True)
            legacy_index_dir.mkdir()
            for name in ["updates", "signatures", "indexing-failed", "tmp"]:
                (legacy_root / name).mkdir()

            with (legacy_manifest_dir / "db38.pickle").open("wb") as handle:
                pickle.dump(["SRR1", "SRR2"], handle)
            for kmer in [21, 31, 51]:
                old_index = legacy_index_dir / f"{kmer}mers-db38.rocksdb"
                old_index.mkdir()
                (old_index / "CURRENT").write_text("rocksdb", encoding="utf-8")

            with override_settings(DATA_DIR=data_dir):
                call_command("migrate_database_storage")
                database = get_database_config(DEFAULT_DATABASE_ID)

                for profile in database.profiles:
                    migrated_index = index_path(database.id, profile, 38)
                    self.assertTrue(migrated_index.exists())
                    self.assertTrue((migrated_index / "CURRENT").exists())
                    self.assertEqual(
                        read_accession_parquet(profile_manifest(database.id, profile)),
                        ["SRR1", "SRR2"],
                    )

                self.assertFalse(
                    (legacy_index_dir / "31mers-db38.rocksdb").exists(),
                    "Disabled k=31 index should be preserved in the new layout.",
                )
                self.assertFalse(
                    (legacy_index_dir / "51mers-db38.rocksdb").exists(),
                    "Disabled k=51 index should be preserved in the new layout.",
                )

    def test_refuses_existing_target_directory_instead_of_nesting_legacy_directory(
        self,
    ):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            legacy_root = data_dir / "SRA" / "metagenomes"
            (legacy_root / "updates").mkdir(parents=True)
            target = (
                data_dir
                / "search-databases"
                / DEFAULT_DATABASE_ID
                / "signatures"
                / "pending"
            )
            target.mkdir(parents=True)

            with override_settings(DATA_DIR=data_dir):
                with self.assertRaisesMessage(
                    CommandError,
                    "Refusing to overwrite existing target",
                ):
                    call_command("migrate_database_storage")

            self.assertTrue((legacy_root / "updates").exists())
            self.assertFalse((target / "updates").exists())
