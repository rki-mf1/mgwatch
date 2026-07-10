import asyncio
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from mgw_api.services.maintenance import download_from_wort
from mgw_api.services.maintenance import get_update_accessions
from mgw_api.services.maintenance import run_index


class DownloadMaintenanceTests(SimpleTestCase):
    def test_get_update_accessions_reads_pending_signatures_from_updates_dir(self):
        with TemporaryDirectory() as tmp_dir:
            updates_dir = Path(tmp_dir)
            (updates_dir / "SRR1.sig").write_text("sig", encoding="ascii")
            (updates_dir / "SRR2.sig").write_text("sig", encoding="ascii")
            (updates_dir / "README.txt").write_text("ignore", encoding="ascii")

            self.assertEqual(get_update_accessions(updates_dir), {"SRR1", "SRR2"})

    def test_download_from_wort_skips_ids_already_present_in_updates_dir(self):
        with TemporaryDirectory() as tmp_dir:
            base_dir = Path(tmp_dir)
            updates_dir = base_dir / "updates"
            updates_dir.mkdir()
            (updates_dir / "SRR1.sig").write_text("sig", encoding="ascii")
            man_fail = base_dir / "download_failed.pickle"
            with open(man_fail, "wb") as handle:
                pickle.dump(set(), handle, protocol=4)

            async def fake_fetch_signature(
                session, url, target_dir, ids_fail, failed_pickle, lock
            ):
                return {"url": url}

            with patch(
                "mgw_api.services.maintenance.fetch_signature",
                side_effect=fake_fetch_signature,
            ) as fetch_mock:
                asyncio.run(
                    download_from_wort(
                        {"updates": updates_dir},
                        {"SRR1", "SRR2"},
                        man_fail,
                        timeout_seconds=1,
                    )
                )

        self.assertEqual(fetch_mock.call_count, 1)
        self.assertEqual(
            fetch_mock.call_args.args[1],
            "https://wort.sourmash.bio/v1/view/sra/SRR2",
        )

    @override_settings(
        DATA_DIR=Path("/tmp/mgwatch-test-data"),
        INDEX_MAX_SIGNATURES=100000,
        INDEX_MIN_ITERATOR=38,
        DELETE_INDEXED_SIGS=False,
    )
    def test_run_index_does_not_touch_download_successful_pickle(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            database_dir = data_dir / "SRA" / "metagenomes"
            for name in [
                "updates",
                "index",
                "signatures",
                "indexing-failed",
                "manifests",
            ]:
                (database_dir / name).mkdir(parents=True, exist_ok=True)
            (database_dir / "updates" / "SRR1.sig").write_text("sig", encoding="ascii")
            success_pickle = database_dir / "download_successful.pickle"
            success_pickle.write_bytes(b"sentinel")
            manifest = database_dir / "manifest.pickle"
            with open(manifest, "wb") as handle:
                pickle.dump([], handle, protocol=4)

            with (
                override_settings(DATA_DIR=data_dir),
                patch("mgw_api.services.maintenance.update_index", return_value=0),
            ):
                result = run_index()

            self.assertEqual(result, {"indexes_updated": 1})
            self.assertEqual(success_pickle.read_bytes(), b"sentinel")
