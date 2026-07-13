import importlib.util
import pickle
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "wort-state-bundle.py"
SPEC = importlib.util.spec_from_file_location("wort_state_bundle", MODULE_PATH)
wort_state_bundle = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = wort_state_bundle
SPEC.loader.exec_module(wort_state_bundle)


class WortStateBundleTests(TestCase):
    def make_work_metagenomes(self, root: Path):
        work_dir = root / "work" / "data" / "backend-data"
        metagenomes = work_dir / "SRA" / "metagenomes"
        for path in (
            metagenomes / "updates",
            metagenomes / "index",
            metagenomes / "signatures",
            metagenomes / "indexing-failed",
            metagenomes / "manifests",
        ):
            path.mkdir(parents=True, exist_ok=True)
        return work_dir, metagenomes

    def test_prepare_bundle_copies_state_files_and_writes_builder_state(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_dir, metagenomes = self.make_work_metagenomes(tmp_path)
            with open(metagenomes / "manifest.pickle", "wb") as handle:
                pickle.dump(["SRR1", "SRR2"], handle, protocol=4)
            with open(metagenomes / "download_failed.pickle", "wb") as handle:
                pickle.dump({"SRR9"}, handle, protocol=4)
            with open(metagenomes / "manifests" / "db41.pickle", "wb") as handle:
                pickle.dump(["SRR1", "SRR2"], handle, protocol=4)
            (metagenomes / "updates" / "SRR3.sig").write_text("sig", encoding="ascii")
            (metagenomes / "indexing-failed" / "SRR8.sig").write_text(
                "sig", encoding="ascii"
            )

            bundle_dir = tmp_path / "bundle"
            wort_state_bundle.prepare_bundle(bundle_dir=bundle_dir, work_dir=work_dir)

            bundle_metagenomes = bundle_dir / "SRA" / "metagenomes"
            with open(bundle_metagenomes / "manifest.pickle", "rb") as handle:
                self.assertEqual(pickle.load(handle), ["SRR1", "SRR2"])
            with open(bundle_metagenomes / "download_failed.pickle", "rb") as handle:
                self.assertEqual(pickle.load(handle), {"SRR9"})
            with open(bundle_metagenomes / "manifests" / "db41.pickle", "rb") as handle:
                self.assertEqual(pickle.load(handle), ["SRR1", "SRR2"])
            self.assertTrue((bundle_metagenomes / "updates" / "SRR3.sig").exists())
            self.assertTrue(
                (bundle_metagenomes / "indexing-failed" / "SRR8.sig").exists()
            )

            state = (bundle_dir / "builder-state.json").read_text(encoding="utf-8")

        self.assertIn('"next_index_number": 42', state)
        self.assertIn('"remaining_accessions": 1', state)
        self.assertIn('"manifest_entries": 2', state)

    def test_apply_output_merges_new_indexes_and_clears_stale_updates(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_dir, work_metagenomes = self.make_work_metagenomes(tmp_path)
            (work_metagenomes / "updates" / "SRR3.sig").write_text(
                "old", encoding="ascii"
            )
            with open(work_metagenomes / "manifest.pickle", "wb") as handle:
                pickle.dump(["SRR0", "SRR1"], handle, protocol=4)
            (work_metagenomes / "index" / "21mers-db41.rocksdb").mkdir()
            (work_metagenomes / "index" / "21mers-db41.rocksdb" / "OLD").write_text(
                "stale", encoding="ascii"
            )

            output_dir = tmp_path / "builder-output"
            _, output_metagenomes = self.make_work_metagenomes(output_dir)
            with open(output_metagenomes / "manifest.pickle", "wb") as handle:
                pickle.dump(["SRR1", "SRR2", "SRR3"], handle, protocol=4)
            with open(output_metagenomes / "download_failed.pickle", "wb") as handle:
                pickle.dump({"SRR9"}, handle, protocol=4)
            with open(output_metagenomes / "manifests" / "db41.pickle", "wb") as handle:
                pickle.dump(["SRR3"], handle, protocol=4)
            for kmer in wort_state_bundle.KMERS:
                (output_metagenomes / "index" / f"{kmer}mers-db41.rocksdb").mkdir(
                    parents=True, exist_ok=True
                )
                (
                    output_metagenomes
                    / "index"
                    / f"{kmer}mers-db41.rocksdb"
                    / "CURRENT"
                ).write_text("fresh", encoding="ascii")
            (output_metagenomes / "signatures" / "SRR3.sig").write_text(
                "sig", encoding="ascii"
            )
            (output_metagenomes / "updates" / "SRR4.sig").write_text(
                "sig", encoding="ascii"
            )

            wort_state_bundle.apply_output(
                builder_output_dir=output_dir / "work" / "data" / "backend-data",
                work_dir=work_dir,
            )

            self.assertFalse((work_metagenomes / "updates" / "SRR3.sig").exists())
            self.assertTrue((work_metagenomes / "updates" / "SRR4.sig").exists())
            self.assertTrue((work_metagenomes / "signatures" / "SRR3.sig").exists())
            self.assertFalse(
                (work_metagenomes / "index" / "21mers-db41.rocksdb" / "OLD").exists()
            )
            self.assertTrue(
                (
                    work_metagenomes / "index" / "21mers-db41.rocksdb" / "CURRENT"
                ).exists()
            )
            with open(work_metagenomes / "manifest.pickle", "rb") as handle:
                self.assertEqual(pickle.load(handle), ["SRR0", "SRR1", "SRR2", "SRR3"])
            with open(work_metagenomes / "download_failed.pickle", "rb") as handle:
                self.assertEqual(pickle.load(handle), {"SRR9"})

    def test_apply_output_refuses_active_builder_batch(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_dir, _work_metagenomes = self.make_work_metagenomes(tmp_path)
            output_dir = tmp_path / "builder-output"
            _, output_metagenomes = self.make_work_metagenomes(output_dir)
            (output_metagenomes / "index" / "21mers-db41.rocksdb").mkdir(
                parents=True, exist_ok=True
            )
            wort_state_bundle.save_json(
                output_dir / "work" / "data" / "backend-data" / "builder-state.json",
                {"active_batch": {"index_number": 41}},
            )

            with self.assertRaisesRegex(RuntimeError, "active_batch"):
                wort_state_bundle.apply_output(
                    builder_output_dir=output_dir / "work" / "data" / "backend-data",
                    work_dir=work_dir,
                )

    def test_apply_output_refuses_incomplete_kmer_siblings(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            work_dir, _work_metagenomes = self.make_work_metagenomes(tmp_path)
            output_dir = tmp_path / "builder-output"
            _, output_metagenomes = self.make_work_metagenomes(output_dir)
            (output_metagenomes / "index" / "21mers-db41.rocksdb").mkdir(
                parents=True, exist_ok=True
            )

            with self.assertRaisesRegex(RuntimeError, "missing k-mer indexes"):
                wort_state_bundle.apply_output(
                    builder_output_dir=output_dir / "work" / "data" / "backend-data",
                    work_dir=work_dir,
                )
