import pickle
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from mgw_api.services.maintenance import can_reuse_last_index
from mgw_api.services.maintenance import get_last_index


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
