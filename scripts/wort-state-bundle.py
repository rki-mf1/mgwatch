#!/usr/bin/env python3
"""Prepare and apply state bundles for wort-standalone-index-builder."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import shutil
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_DIR = REPO_ROOT / "work" / "data" / "backend-data"
KMERS = (21, 31, 51)


@dataclass
class MetagenomePaths:
    root: Path
    sra: Path
    metagenomes: Path
    updates: Path
    index: Path
    signatures: Path
    indexing_failed: Path
    manifests: Path
    manifest: Path
    failed_downloads: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a standalone Wort index builder state bundle or apply a "
            "builder output back into the local work directory."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="Copy the current work state into a portable bundle directory.",
    )
    prepare.add_argument("--bundle-dir", required=True, type=Path)
    prepare.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help=(
            "Path to backend-data/, SRA/, or SRA/metagenomes/. Defaults to "
            "work/data/backend-data."
        ),
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Merge a standalone builder output directory back into work/.",
    )
    apply_parser.add_argument("--builder-output-dir", required=True, type=Path)
    apply_parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help=(
            "Path to backend-data/, SRA/, or SRA/metagenomes/. Defaults to "
            "work/data/backend-data."
        ),
    )

    return parser.parse_args()


def resolve_metagenome_paths(base_dir: Path) -> MetagenomePaths:
    base_dir = base_dir.resolve()
    if base_dir.name == "metagenomes":
        metagenomes = base_dir
    elif base_dir.name == "SRA":
        metagenomes = base_dir / "metagenomes"
    else:
        metagenomes = base_dir / "SRA" / "metagenomes"

    sra = metagenomes.parent
    return MetagenomePaths(
        root=sra.parent,
        sra=sra,
        metagenomes=metagenomes,
        updates=metagenomes / "updates",
        index=metagenomes / "index",
        signatures=metagenomes / "signatures",
        indexing_failed=metagenomes / "indexing-failed",
        manifests=metagenomes / "manifests",
        manifest=metagenomes / "manifest.pickle",
        failed_downloads=metagenomes / "download_failed.pickle",
    )


def ensure_bundle_dirs(paths: MetagenomePaths) -> None:
    for dir_path in (
        paths.updates,
        paths.index,
        paths.signatures,
        paths.indexing_failed,
        paths.manifests,
    ):
        dir_path.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_sig_files(src_dir: Path, dst_dir: Path) -> int:
    if not src_dir.exists():
        return 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for sig_path in sorted(src_dir.glob("*.sig")):
        shutil.copy2(sig_path, dst_dir / sig_path.name)
        copied += 1
    return copied


def copy_manifest_pickles(src_dir: Path, dst_dir: Path) -> int:
    if not src_dir.exists():
        return 0
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for manifest_path in sorted(src_dir.glob("db*.pickle")):
        shutil.copy2(manifest_path, dst_dir / manifest_path.name)
        copied += 1
    return copied


def load_pickle(path: Path, default):
    if not path.exists():
        return default
    with path.open("rb") as handle:
        return pickle.load(handle)


def save_pickle(path: Path, data) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("wb") as handle:
        pickle.dump(data, handle, protocol=4)
    os.replace(tmp_path, path)


def save_json(path: Path, data: dict) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def list_db_numbers(manifests_dir: Path) -> list[int]:
    numbers = []
    if not manifests_dir.exists():
        return numbers
    for path in manifests_dir.glob("db*.pickle"):
        try:
            numbers.append(int(path.stem[2:]))
        except ValueError:
            continue
    return sorted(numbers)


def determine_next_index_number(paths: MetagenomePaths) -> int:
    numbers = list_db_numbers(paths.manifests)
    if not numbers:
        return 38
    return max(numbers) + 1


def build_builder_state(paths: MetagenomePaths) -> dict:
    manifest_ids = load_pickle(paths.manifest, [])
    failed_downloads = sorted(load_pickle(paths.failed_downloads, set()))
    return {
        "active_batch": None,
        "batches_completed": len(list_db_numbers(paths.manifests)),
        "failed_downloads": failed_downloads,
        "manifest_entries": len(manifest_ids),
        "next_index_number": determine_next_index_number(paths),
        "remaining_accessions": len(
            sorted(path.stem for path in paths.updates.glob("*.sig"))
        ),
    }


def prepare_bundle(bundle_dir: Path, work_dir: Path) -> None:
    source_paths = resolve_metagenome_paths(work_dir)
    bundle_paths = resolve_metagenome_paths(bundle_dir / "SRA" / "metagenomes")
    ensure_bundle_dirs(bundle_paths)

    copy_file(source_paths.manifest, bundle_paths.manifest)
    copy_file(source_paths.failed_downloads, bundle_paths.failed_downloads)
    copied_manifests = copy_manifest_pickles(
        source_paths.manifests, bundle_paths.manifests
    )
    copied_updates = copy_sig_files(source_paths.updates, bundle_paths.updates)
    copied_failed = copy_sig_files(
        source_paths.indexing_failed, bundle_paths.indexing_failed
    )

    save_json(bundle_dir / "builder-state.json", build_builder_state(source_paths))

    print(f"Prepared bundle in {bundle_dir}")
    print(f"Copied {copied_manifests} manifest files")
    print(f"Copied {copied_updates} queued update signatures")
    print(f"Copied {copied_failed} indexing-failed signatures")


def remove_matching_signatures(directory: Path, accession_names: set[str]) -> int:
    removed = 0
    if not directory.exists():
        return removed
    for accession in sorted(accession_names):
        sig_path = directory / f"{accession}.sig"
        if sig_path.exists():
            sig_path.unlink()
            removed += 1
    return removed


def replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def find_builder_state_path(builder_output_dir: Path, source_paths: MetagenomePaths):
    candidates = [
        builder_output_dir / "builder-state.json",
        source_paths.root / "builder-state.json",
        source_paths.root.parent / "builder-state.json",
        source_paths.root.parent.parent / "builder-state.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_index_dir(path: Path):
    if not path.name.endswith(".rocksdb") or "mers-db" not in path.name:
        return None
    kmer_text, db_text = path.name.removesuffix(".rocksdb").split("mers-db", 1)
    try:
        return int(db_text), int(kmer_text)
    except ValueError:
        return None


def validate_builder_output(builder_output_dir: Path, source_paths: MetagenomePaths):
    state_path = find_builder_state_path(builder_output_dir, source_paths)
    if state_path:
        state_data = json.loads(state_path.read_text(encoding="utf-8"))
        if state_data.get("active_batch"):
            raise RuntimeError(
                f"builder output still has active_batch in {state_path}; "
                "refusing to apply incomplete output"
            )

    batches = {}
    if source_paths.index.exists():
        for index_dir in sorted(source_paths.index.glob("*.rocksdb")):
            parsed = parse_index_dir(index_dir)
            if parsed is None:
                continue
            index_number, kmer = parsed
            batches.setdefault(index_number, set()).add(kmer)
    expected_kmers = set(KMERS)
    for index_number, kmers in sorted(batches.items()):
        if kmers != expected_kmers:
            missing = sorted(expected_kmers - kmers)
            raise RuntimeError(
                f"builder output is missing k-mer indexes {missing} "
                f"for db{index_number}"
            )


def merge_manifest(source_manifest: Path, work_manifest: Path) -> bool:
    if not source_manifest.exists():
        return False
    merged = set(load_pickle(work_manifest, [])) | set(load_pickle(source_manifest, []))
    save_pickle(work_manifest, sorted(merged))
    return True


def apply_output(builder_output_dir: Path, work_dir: Path) -> None:
    source_paths = resolve_metagenome_paths(builder_output_dir)
    work_paths = resolve_metagenome_paths(work_dir)
    ensure_bundle_dirs(work_paths)
    validate_builder_output(builder_output_dir, source_paths)

    copied_indexes = 0
    if source_paths.index.exists():
        for index_dir in sorted(source_paths.index.glob("*.rocksdb")):
            replace_tree(index_dir, work_paths.index / index_dir.name)
            copied_indexes += 1

    copied_manifests = copy_manifest_pickles(
        source_paths.manifests, work_paths.manifests
    )
    merged_manifest = merge_manifest(source_paths.manifest, work_paths.manifest)
    replaced_failed_downloads = copy_file(
        source_paths.failed_downloads, work_paths.failed_downloads
    )

    copied_updates = copy_sig_files(source_paths.updates, work_paths.updates)
    copied_signatures = copy_sig_files(source_paths.signatures, work_paths.signatures)
    copied_failed = copy_sig_files(
        source_paths.indexing_failed, work_paths.indexing_failed
    )

    indexed_accessions = set()
    if source_paths.manifests.exists():
        for manifest_path in sorted(source_paths.manifests.glob("db*.pickle")):
            indexed_accessions.update(load_pickle(manifest_path, []))
    removed_updates = remove_matching_signatures(work_paths.updates, indexed_accessions)

    print(f"Applied builder output from {builder_output_dir}")
    print(f"Copied {copied_indexes} rocksdb indexes")
    print(f"Copied {copied_manifests} manifest batch files")
    print(f"Merged aggregate manifest: {'yes' if merged_manifest else 'no'}")
    print(
        f"Replaced failed-download state: {'yes' if replaced_failed_downloads else 'no'}"
    )
    print(f"Copied {copied_updates} update signatures")
    print(f"Copied {copied_signatures} retained signatures")
    print(f"Copied {copied_failed} indexing-failed signatures")
    print(f"Removed {removed_updates} stale update signatures")


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        prepare_bundle(bundle_dir=args.bundle_dir.resolve(), work_dir=args.work_dir)
        return 0
    if args.command == "apply":
        apply_output(
            builder_output_dir=args.builder_output_dir.resolve(),
            work_dir=args.work_dir,
        )
        return 0
    raise ValueError(f"unsupported command '{args.command}'")


if __name__ == "__main__":
    raise SystemExit(main())
