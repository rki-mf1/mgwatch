import argparse
import importlib.util
import pickle
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "wort-standalone-index-builder.py"
)
SPEC = importlib.util.spec_from_file_location(
    "wort_standalone_index_builder", MODULE_PATH
)
wort_index_builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = wort_index_builder
SPEC.loader.exec_module(wort_index_builder)


class WortIndexBuilderTests(TestCase):
    def make_args(self, tmp_dir, accessions_file, **overrides):
        defaults = {
            "accessions_file": accessions_file,
            "output_dir": Path(tmp_dir) / "output",
            "mode": "incremental",
            "state_dir": None,
            "index_max_signatures": 2,
            "index_min_iterator": 38,
            "max_simultaneous": 2,
            "timeout": 1,
            "cores": 1,
            "retry_failed": False,
            "retain_indexed_signatures": False,
            "package": "none",
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_determine_next_index_number_uses_state_bundle(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output_paths = wort_index_builder.create_output_paths(tmp_path / "output")
            state_metagenomes = tmp_path / "state" / "SRA" / "metagenomes"
            (state_metagenomes / "manifests").mkdir(parents=True)
            with open(state_metagenomes / "manifests" / "db41.pickle", "wb") as handle:
                pickle.dump(["SRR1"], handle, protocol=4)
            wort_index_builder.save_json(
                tmp_path / "state" / "builder-state.json",
                {"next_index_number": 44},
            )

            next_index = wort_index_builder.determine_next_index_number(
                output_paths=output_paths,
                state_metagenomes=state_metagenomes,
                index_min_iterator=38,
            )

        self.assertEqual(next_index, 44)

    def test_fill_download_batch_stops_at_batch_size(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output_paths = wort_index_builder.create_output_paths(tmp_path / "output")

            def fake_download_signatures(**kwargs):
                accessions = kwargs["accessions"]
                for accession in accessions:
                    (output_paths.updates / f"{accession}.sig").write_text(
                        "sig", encoding="ascii"
                    )
                return accessions, kwargs["failed_downloads"]

            with patch.object(
                wort_index_builder,
                "download_signatures",
                side_effect=fake_download_signatures,
            ):
                downloaded, remaining, failed_downloads = (
                    wort_index_builder.fill_download_batch(
                        pending_accessions=["SRR1", "SRR2", "SRR3"],
                        output_paths=output_paths,
                        batch_size=2,
                        timeout=1,
                        max_simultaneous=2,
                        failed_downloads=set(),
                    )
                )

        self.assertEqual(downloaded, ["SRR1", "SRR2"])
        self.assertEqual(remaining, ["SRR3"])
        self.assertEqual(failed_downloads, set())

    def test_run_pipeline_indexes_one_batch_then_deletes_signatures(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            accessions_file = tmp_path / "accessions.txt"
            accessions_file.write_text("SRR1\nSRR2\nSRR3\n", encoding="ascii")
            args = self.make_args(tmp_dir, accessions_file)
            built_batches = []

            def fake_download_signatures(**kwargs):
                accessions = kwargs["accessions"]
                for accession in accessions:
                    (kwargs["output_paths"].updates / f"{accession}.sig").write_text(
                        "sig", encoding="ascii"
                    )
                return accessions, kwargs["failed_downloads"]

            def fake_build_index_batch(**kwargs):
                built_batches.append(
                    (
                        kwargs["index_number"],
                        [path.name for path in kwargs["sig_paths"]],
                    )
                )
                for ksize in wort_index_builder.KMERS:
                    (
                        kwargs["output_paths"].index
                        / f"{ksize}mers-db{kwargs['index_number']}.rocksdb"
                    ).mkdir()

            with (
                patch.object(
                    wort_index_builder,
                    "download_signatures",
                    side_effect=fake_download_signatures,
                ),
                patch.object(
                    wort_index_builder,
                    "build_index_batch",
                    side_effect=fake_build_index_batch,
                ),
            ):
                exit_code = wort_index_builder.run_pipeline(args)

            output_paths = wort_index_builder.create_output_paths(args.output_dir)
            manifest = pickle.loads(output_paths.manifest.read_bytes())
            state_data = wort_index_builder.load_json(output_paths.state_json, {})

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            built_batches,
            [
                (38, ["SRR1.sig", "SRR2.sig"]),
                (39, ["SRR3.sig"]),
            ],
        )
        self.assertEqual(manifest, ["SRR1", "SRR2", "SRR3"])
        self.assertEqual(list(output_paths.updates.glob("*.sig")), [])
        self.assertEqual(list(output_paths.signatures.glob("*.sig")), [])
        self.assertEqual(state_data["next_index_number"], 40)

    def test_run_pipeline_skips_manifest_entries_from_incremental_state(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            accessions_file = tmp_path / "accessions.txt"
            accessions_file.write_text("SRR1\nSRR2\nSRR3\n", encoding="ascii")
            state_metagenomes = tmp_path / "state" / "SRA" / "metagenomes"
            state_metagenomes.mkdir(parents=True)
            with open(state_metagenomes / "manifest.pickle", "wb") as handle:
                pickle.dump(["SRR1"], handle, protocol=4)
            args = self.make_args(
                tmp_dir,
                accessions_file,
                state_dir=tmp_path / "state",
            )
            built_batches = []

            def fake_download_signatures(**kwargs):
                accessions = kwargs["accessions"]
                for accession in accessions:
                    (kwargs["output_paths"].updates / f"{accession}.sig").write_text(
                        "sig", encoding="ascii"
                    )
                return accessions, kwargs["failed_downloads"]

            def fake_build_index_batch(**kwargs):
                built_batches.append(sorted(path.stem for path in kwargs["sig_paths"]))
                for ksize in wort_index_builder.KMERS:
                    (
                        kwargs["output_paths"].index
                        / f"{ksize}mers-db{kwargs['index_number']}.rocksdb"
                    ).mkdir()

            with (
                patch.object(
                    wort_index_builder,
                    "download_signatures",
                    side_effect=fake_download_signatures,
                ),
                patch.object(
                    wort_index_builder,
                    "build_index_batch",
                    side_effect=fake_build_index_batch,
                ),
            ):
                wort_index_builder.run_pipeline(args)

            output_paths = wort_index_builder.create_output_paths(args.output_dir)
            manifest = pickle.loads(output_paths.manifest.read_bytes())

        self.assertEqual(built_batches, [["SRR2", "SRR3"]])
        self.assertEqual(manifest, ["SRR1", "SRR2", "SRR3"])

    def test_resume_finishes_interrupted_indexed_batch_without_rebuilding(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            accessions_file = tmp_path / "accessions.txt"
            accessions_file.write_text("SRR1\nSRR2\n", encoding="ascii")
            args = self.make_args(tmp_dir, accessions_file)
            output_paths = wort_index_builder.create_output_paths(args.output_dir)
            for accession in ["SRR1", "SRR2"]:
                (output_paths.updates / f"{accession}.sig").write_text(
                    "sig", encoding="ascii"
                )
            for ksize in wort_index_builder.KMERS:
                (output_paths.index / f"{ksize}mers-db38.rocksdb").mkdir()
            wort_index_builder.write_state_file(
                output_paths=output_paths,
                next_index_number=38,
                manifest_ids=set(),
                failed_downloads=set(),
                remaining_accessions=0,
                batches_completed=0,
                all_accessions_digest=wort_index_builder.compute_accessions_digest(
                    ["SRR1", "SRR2"]
                ),
                active_batch=wort_index_builder.build_active_batch_state(
                    38, ["SRR1", "SRR2"], "indexed"
                ),
            )

            with patch.object(wort_index_builder, "build_index_batch") as build_mock:
                exit_code = wort_index_builder.run_pipeline(args)

            manifest = pickle.loads(output_paths.manifest.read_bytes())
            state_data = wort_index_builder.load_json(output_paths.state_json, {})

        self.assertEqual(exit_code, 0)
        build_mock.assert_not_called()
        self.assertEqual(manifest, ["SRR1", "SRR2"])
        self.assertEqual(state_data["batches_completed"], 1)
        self.assertIsNone(state_data["active_batch"])
        self.assertEqual(list(output_paths.updates.glob("*.sig")), [])

    def test_resume_restarts_at_next_unfinished_kmer(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            accessions_file = tmp_path / "accessions.txt"
            accessions_file.write_text("SRR1\nSRR2\n", encoding="ascii")
            args = self.make_args(tmp_dir, accessions_file)
            output_paths = wort_index_builder.create_output_paths(args.output_dir)
            for accession in ["SRR1", "SRR2"]:
                (output_paths.updates / f"{accession}.sig").write_text(
                    "sig", encoding="ascii"
                )
            (output_paths.index / "21mers-db38.rocksdb").mkdir()
            wort_index_builder.write_state_file(
                output_paths=output_paths,
                next_index_number=38,
                manifest_ids=set(),
                failed_downloads=set(),
                remaining_accessions=0,
                batches_completed=0,
                all_accessions_digest=wort_index_builder.compute_accessions_digest(
                    ["SRR1", "SRR2"]
                ),
                active_batch=wort_index_builder.build_active_batch_state_with_progress(
                    38, ["SRR1", "SRR2"], "indexing", [21]
                ),
            )
            built_ksizes = []

            def fake_build_single_kmer_index(**kwargs):
                built_ksizes.append(kwargs["ksize"])
                (
                    kwargs["output_paths"].index
                    / f"{kwargs['ksize']}mers-db{kwargs['index_number']}.rocksdb"
                ).mkdir()

            with patch.object(
                wort_index_builder,
                "build_single_kmer_index",
                side_effect=fake_build_single_kmer_index,
            ):
                exit_code = wort_index_builder.run_pipeline(args)

            manifest = pickle.loads(output_paths.manifest.read_bytes())
            state_data = wort_index_builder.load_json(output_paths.state_json, {})

        self.assertEqual(exit_code, 0)
        self.assertEqual(built_ksizes, [31, 51])
        self.assertEqual(manifest, ["SRR1", "SRR2"])
        self.assertIsNone(state_data["active_batch"])

    def test_finalize_retained_signatures_allows_already_moved_files(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            output_paths = wort_index_builder.create_output_paths(tmp_path / "output")
            moved_source = output_paths.updates / "SRR1.sig"
            missing_source = output_paths.updates / "SRR2.sig"
            (output_paths.signatures / "SRR1.sig").write_text("sig", encoding="ascii")
            (output_paths.updates / "SRR2.sig").write_text("sig", encoding="ascii")

            wort_index_builder.finalize_batch_files(
                sig_paths=[moved_source, missing_source],
                output_paths=output_paths,
                retain_indexed_signatures=True,
            )

            self.assertFalse(moved_source.exists())
            self.assertFalse(missing_source.exists())
            self.assertTrue((output_paths.signatures / "SRR1.sig").exists())
            self.assertTrue((output_paths.signatures / "SRR2.sig").exists())
