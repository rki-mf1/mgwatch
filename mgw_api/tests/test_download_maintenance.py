import asyncio
import pickle
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from mgw_api.services.maintenance import download_from_wort
from mgw_api.services.maintenance import fetch_signature
from mgw_api.services.maintenance import get_update_accessions
from mgw_api.services.maintenance import prepare_download_targets
from mgw_api.services.maintenance import run_download_index
from mgw_api.services.maintenance import run_downloads
from mgw_api.services.maintenance import run_index


class FakeDownloadContent:
    async def iter_chunked(self, _chunk_size):
        yield b"signature"


class FakeDownloadResponse:
    status = 200
    content = FakeDownloadContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeDownloadSession:
    def get(self, url, ssl=None):
        return FakeDownloadResponse()


class DownloadMaintenanceTests(SimpleTestCase):
    @override_settings(
        DATA_DIR=Path("/tmp/mgwatch-test-data"),
        INDEX_FROM_SCRATCH=False,
    )
    def test_prepare_download_targets_requires_manifest_without_explicit_ids(self):
        with TemporaryDirectory() as tmp_dir:
            with override_settings(DATA_DIR=Path(tmp_dir)):
                with self.assertRaisesMessage(
                    RuntimeError,
                    "manifest.pickle is missing and INDEX_FROM_SCRATCH is disabled",
                ):
                    prepare_download_targets()

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

    def test_fetch_signature_publishes_only_final_signature_path(self):
        with TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir)
            failed_pickle = target_dir / "download_failed.pickle"

            result = asyncio.run(
                fetch_signature(
                    FakeDownloadSession(),
                    "https://wort.sourmash.bio/v1/view/sra/SRR1",
                    target_dir,
                    set(),
                    failed_pickle,
                    asyncio.Lock(),
                )
            )

            self.assertEqual(result["path"], str(target_dir / "SRR1.sig"))
            self.assertEqual((target_dir / "SRR1.sig").read_bytes(), b"signature")
            self.assertEqual(list(target_dir.glob("*.tmp")), [])

    @override_settings(MAX_DOWNLOADS=1)
    def test_run_downloads_preserves_explicit_download_limit(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            captured = {}

            async def fake_download_from_wort(
                dir_paths,
                sra_ids,
                man_fail,
                timeout_seconds,
                retry_failed=False,
                max_downloads=None,
                max_simultaneous=100,
            ):
                captured["sra_ids"] = list(sra_ids)
                captured["max_downloads"] = max_downloads
                return [
                    {
                        "id": accession,
                        "status": 200,
                        "path": str(dir_paths["updates"] / f"{accession}.sig"),
                    }
                    for accession in sra_ids
                ]

            with (
                patch("mgw_api.services.maintenance.run_command"),
                patch(
                    "mgw_api.services.maintenance.prepare_download_targets",
                    return_value=(
                        {"updates": data_dir / "updates"},
                        data_dir / "download_failed.pickle",
                        ["SRR1", "SRR2", "SRR3"],
                    ),
                ),
                patch(
                    "mgw_api.services.maintenance.download_from_wort",
                    side_effect=fake_download_from_wort,
                ),
            ):
                result = run_downloads(max_downloads=3)

        self.assertEqual(result, {"downloaded": 3})
        self.assertEqual(captured["sra_ids"], ["SRR1", "SRR2", "SRR3"])
        self.assertEqual(captured["max_downloads"], 3)

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

    @override_settings(
        DATA_DIR=Path("/tmp/mgwatch-test-data"),
        INDEX_MAX_SIGNATURES=2,
        MAX_DOWNLOADS=0,
    )
    def test_run_download_index_processes_one_index_batch_at_a_time(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            current_updates = set()
            run_index_calls = []

            async def fake_download_from_wort(
                dir_paths,
                sra_ids,
                man_fail,
                timeout_seconds,
                retry_failed=False,
                max_downloads=None,
                max_simultaneous=100,
            ):
                current_updates.update(sra_ids)
                return [
                    {
                        "id": accession,
                        "status": 200,
                        "path": str(dir_paths["updates"] / f"{accession}.sig"),
                    }
                    for accession in sra_ids
                ]

            def fake_get_update_accessions(_updates_dir):
                return set(current_updates)

            def fake_run_index_batches(
                work_dir,
                *,
                index_max_signatures=None,
                max_batches=None,
                delete_indexed_sigs=False,
            ):
                run_index_calls.append(
                    {
                        "updates": sorted(current_updates),
                        "index_max_signatures": index_max_signatures,
                        "max_batches": max_batches,
                        "delete_indexed_sigs": delete_indexed_sigs,
                    }
                )
                current_updates.clear()
                return {
                    "indexes_updated": 1,
                    "batches_processed": 1,
                    "indexing_failed": False,
                }

            with (
                override_settings(DATA_DIR=data_dir),
                patch("mgw_api.services.maintenance.run_command"),
                patch(
                    "mgw_api.services.maintenance.prepare_download_targets",
                    return_value=(
                        {"updates": data_dir / "SRA" / "metagenomes" / "updates"},
                        data_dir / "SRA" / "metagenomes" / "download_failed.pickle",
                        ["SRR1", "SRR2", "SRR3"],
                    ),
                ),
                patch(
                    "mgw_api.services.maintenance.download_from_wort",
                    side_effect=fake_download_from_wort,
                ),
                patch(
                    "mgw_api.services.maintenance.get_update_accessions",
                    side_effect=fake_get_update_accessions,
                ),
                patch(
                    "mgw_api.services.maintenance.run_index_batches",
                    side_effect=fake_run_index_batches,
                ),
            ):
                result = run_download_index(index_max_signatures=2)

        self.assertEqual(result, {"downloaded": 3, "indexes_updated": 2})
        self.assertEqual(
            run_index_calls,
            [
                {
                    "updates": ["SRR1", "SRR2"],
                    "index_max_signatures": 2,
                    "max_batches": 1,
                    "delete_indexed_sigs": True,
                },
                {
                    "updates": ["SRR3"],
                    "index_max_signatures": 2,
                    "max_batches": 1,
                    "delete_indexed_sigs": True,
                },
            ],
        )

    @override_settings(
        DATA_DIR=Path("/tmp/mgwatch-test-data"),
        INDEX_MAX_SIGNATURES=100000,
        MAX_DOWNLOADS=1,
    )
    def test_run_download_index_preserves_selected_batch_size_for_downloader(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            current_updates = set()
            captured_max_downloads = []

            async def fake_download_from_wort(
                dir_paths,
                sra_ids,
                man_fail,
                timeout_seconds,
                retry_failed=False,
                max_downloads=None,
                max_simultaneous=100,
            ):
                captured_max_downloads.append(max_downloads)
                current_updates.update(sra_ids)
                return [
                    {
                        "id": accession,
                        "status": 200,
                        "path": str(dir_paths["updates"] / f"{accession}.sig"),
                    }
                    for accession in sra_ids
                ]

            def fake_get_update_accessions(_updates_dir):
                return set(current_updates)

            def fake_run_index_batches(
                work_dir,
                *,
                index_max_signatures=None,
                max_batches=None,
                delete_indexed_sigs=False,
            ):
                current_updates.clear()
                return {
                    "indexes_updated": 1,
                    "batches_processed": 1,
                    "indexing_failed": False,
                }

            with (
                override_settings(DATA_DIR=data_dir),
                patch("mgw_api.services.maintenance.run_command"),
                patch(
                    "mgw_api.services.maintenance.prepare_download_targets",
                    return_value=(
                        {"updates": data_dir / "SRA" / "metagenomes" / "updates"},
                        data_dir / "SRA" / "metagenomes" / "download_failed.pickle",
                        ["SRR1", "SRR2", "SRR3"],
                    ),
                ),
                patch(
                    "mgw_api.services.maintenance.download_from_wort",
                    side_effect=fake_download_from_wort,
                ),
                patch(
                    "mgw_api.services.maintenance.get_update_accessions",
                    side_effect=fake_get_update_accessions,
                ),
                patch(
                    "mgw_api.services.maintenance.run_index_batches",
                    side_effect=fake_run_index_batches,
                ),
            ):
                result = run_download_index(index_max_signatures=3)

        self.assertEqual(result, {"downloaded": 3, "indexes_updated": 1})
        self.assertEqual(captured_max_downloads, [3])
