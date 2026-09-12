from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import get_database_config
from mgw_api.database_config import profile_root
from mgw_api.database_config import signature_dirs
from mgw_api.database_config import write_accession_parquet
from mgw_api.services.maintenance import can_reuse_last_index
from mgw_api.services.maintenance import get_last_index
from mgw_api.services.maintenance import process_index_batch
from mgw_api.services.maintenance import run_index


class CreateIndexServiceTests(SimpleTestCase):
    def test_process_index_batch_moves_files_to_failed_when_update_raises(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            for name in ["index", "signatures", "indexing-failed", "manifests"]:
                (base_dir / name).mkdir()
            update_sig = base_dir / "updates-SRR1.sig"
            update_sig.write_text("sig", encoding="ascii")

            with (
                patch(
                    "mgw_api.services.maintenance.update_index",
                    side_effect=RuntimeError("sourmash failed"),
                ),
                patch("mgw_api.services.maintenance.update_manifests") as manifest_mock,
            ):
                succeeded, manifest_ids = process_index_batch(
                    work_dir=base_dir,
                    dir_paths={
                        "signatures": base_dir / "signatures",
                        "indexing-failed": base_dir / "indexing-failed",
                    },
                    sig_list=base_dir / "sig-list.txt",
                    database=DEFAULT_DATABASE_ID,
                    profiles=get_database_config().enabled_profiles,
                    index_number=38,
                    new_files=[str(update_sig)],
                    mani_list=[],
                    max_signatures=100,
                    delete_indexed_sigs=False,
                )

            self.assertFalse(succeeded)
            self.assertEqual(manifest_ids, [])
            manifest_mock.assert_not_called()
            self.assertFalse(update_sig.exists())
            self.assertTrue((base_dir / "indexing-failed" / update_sig.name).exists())

    def test_get_last_index_filters_missing_signature_files(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            data_dir = base_dir / "data"
            database = get_database_config()
            profile = database.enabled_profiles[0]
            with override_settings(DATA_DIR=data_dir):
                signatures_dir = signature_dirs(database.id)["indexed"]
                signatures_dir.mkdir(parents=True)
                (signatures_dir / "present.sig").write_text("sig", encoding="ascii")
                batch_dir = profile_root(database.id, profile) / "batch-7"
                write_accession_parquet(
                    batch_dir / "manifest.parquet",
                    ["present", "deleted"],
                )

                last_sig_files, last_num, has_existing_index = get_last_index(
                    database.id,
                    profile,
                    {"signatures": signatures_dir},
                )

        self.assertEqual(last_num, 38)
        self.assertTrue(has_existing_index)
        self.assertEqual(last_sig_files, [str(signatures_dir / "present.sig")])

    def test_can_reuse_last_index_distinguishes_missing_files_from_missing_index(self):
        with TemporaryDirectory() as tmp_dir:
            sig_path = Path(tmp_dir) / "present.sig"
            sig_path.write_text("sig", encoding="ascii")

            self.assertTrue(can_reuse_last_index([str(sig_path)], True))
            self.assertFalse(
                can_reuse_last_index(
                    [str(sig_path), str(Path(tmp_dir) / "missing.sig")], True
                )
            )
            self.assertFalse(can_reuse_last_index([], True))
            self.assertTrue(can_reuse_last_index([], False))

    @override_settings(
        INDEX_MAX_SIGNATURES=100000,
        INDEX_MIN_ITERATOR=38,
        DELETE_INDEXED_SIGS=False,
    )
    def test_run_index_uses_override_for_max_index_size(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            pending_dir = (
                data_dir
                / "search-databases"
                / DEFAULT_DATABASE_ID
                / "signatures"
                / "pending"
            )
            pending_dir.mkdir(parents=True, exist_ok=True)
            for accession in ["SRR1", "SRR2", "SRR3"]:
                (pending_dir / f"{accession}.sig").write_text("sig", encoding="ascii")

            written_lists = []

            def capture_signature_list(sig_file_names, output_file):
                written_lists.append(list(sig_file_names))

            with (
                override_settings(DATA_DIR=data_dir),
                patch(
                    "mgw_api.services.maintenance.write_signature_list",
                    side_effect=capture_signature_list,
                ),
                patch("mgw_api.services.maintenance.update_index", return_value=0),
                patch("mgw_api.services.maintenance.move_files"),
                patch("mgw_api.services.maintenance.update_manifests"),
            ):
                result = run_index(index_max_signatures=2)

        self.assertEqual(result, {"indexes_updated": 1})
        self.assertEqual(len(written_lists), 2)
        self.assertEqual(
            [Path(path).name for path in written_lists[0]], ["SRR1.sig", "SRR2.sig"]
        )
        self.assertEqual([Path(path).name for path in written_lists[1]], ["SRR3.sig"])
