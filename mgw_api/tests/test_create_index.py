import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from mgw_api.services.maintenance import can_reuse_last_index
from mgw_api.services.maintenance import get_last_index
from mgw_api.services.maintenance import run_index


class CreateIndexServiceTests(SimpleTestCase):
    def test_get_last_index_filters_missing_signature_files(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            manifests_dir = base_dir / "manifests"
            signatures_dir = base_dir / "signatures"
            manifests_dir.mkdir()
            signatures_dir.mkdir()

            (signatures_dir / "present.sig").write_text("sig", encoding="ascii")
            with open(manifests_dir / "db7.pickle", "wb") as handle:
                pickle.dump(["present", "deleted"], handle, protocol=4)

            last_sig_files, last_num, has_existing_index = get_last_index(
                {"manifests": manifests_dir, "signatures": signatures_dir}
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
            metagenomes_dir = data_dir / "SRA" / "metagenomes"
            for name in [
                "updates",
                "index",
                "signatures",
                "indexing-failed",
                "manifests",
            ]:
                (metagenomes_dir / name).mkdir(parents=True, exist_ok=True)
            for accession in ["SRR1", "SRR2", "SRR3"]:
                (metagenomes_dir / "updates" / f"{accession}.sig").write_text(
                    "sig", encoding="ascii"
                )
            with open(metagenomes_dir / "manifest.pickle", "wb") as handle:
                pickle.dump([], handle, protocol=4)

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
