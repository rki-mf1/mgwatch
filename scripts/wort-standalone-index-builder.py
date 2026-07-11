#!/usr/bin/env python3
"""Standalone Wort downloader and index builder for mgwatch-compatible data."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import math
import os
import pickle
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

KMERS = (21, 31, 51)
DEFAULT_INDEX_MIN_ITERATOR = 38
DEFAULT_INDEX_MAX_SIGNATURES = 100_000
SIGNATURE_ENDPOINT = "https://wort.sourmash.bio/v1/view/sra"


@dataclass
class OutputPaths:
    root: Path
    metagenomes: Path
    updates: Path
    index: Path
    signatures: Path
    indexing_failed: Path
    manifests: Path
    manifest: Path
    failed_downloads: Path
    state_json: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Wort signatures and build mgwatch-compatible rocksdb indexes "
            "without requiring Django."
        )
    )
    parser.add_argument("--accessions-file", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=("rebuild", "incremental"),
        default="incremental",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help=(
            "Optional seed state directory. This may point to either a directory "
            "containing SRA/metagenomes/ or directly to the metagenomes directory."
        ),
    )
    parser.add_argument(
        "--index-max-signatures",
        type=int,
        default=DEFAULT_INDEX_MAX_SIGNATURES,
    )
    parser.add_argument(
        "--index-min-iterator",
        type=int,
        default=DEFAULT_INDEX_MIN_ITERATOR,
    )
    parser.add_argument("--max-simultaneous", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--cores", type=int, default=None)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--retain-indexed-signatures",
        action="store_true",
        help="Keep signatures after indexing instead of deleting them.",
    )
    parser.add_argument(
        "--package",
        choices=("none", "tar"),
        default="none",
    )
    return parser.parse_args()


def resolve_metagenomes_dir(base_dir: Path | None) -> Path | None:
    if base_dir is None:
        return None
    candidate = base_dir / "SRA" / "metagenomes"
    if candidate.exists():
        return candidate
    return base_dir


def create_output_paths(output_dir: Path) -> OutputPaths:
    root = output_dir.resolve()
    metagenomes = root / "SRA" / "metagenomes"
    paths = OutputPaths(
        root=root,
        metagenomes=metagenomes,
        updates=metagenomes / "updates",
        index=metagenomes / "index",
        signatures=metagenomes / "signatures",
        indexing_failed=metagenomes / "indexing-failed",
        manifests=metagenomes / "manifests",
        manifest=metagenomes / "manifest.pickle",
        failed_downloads=metagenomes / "download_failed.pickle",
        state_json=root / "builder-state.json",
    )
    for dir_path in (
        paths.updates,
        paths.index,
        paths.signatures,
        paths.indexing_failed,
        paths.manifests,
    ):
        dir_path.mkdir(parents=True, exist_ok=True)
    return paths


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


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def read_accessions(path: Path) -> list[str]:
    seen = set()
    ordered = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            accession = raw_line.strip()
            if not accession or accession.startswith("#") or accession in seen:
                continue
            seen.add(accession)
            ordered.append(accession)
    return ordered


def compute_accessions_digest(accessions: list[str]) -> str:
    digest = hashlib.sha256()
    for accession in accessions:
        digest.update(accession.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def get_update_accessions(updates_dir: Path) -> list[str]:
    return sorted(path.stem for path in updates_dir.glob("*.sig"))


def get_downloaded_signature_paths(
    updates_dir: Path, accessions: list[str]
) -> list[Path]:
    return [updates_dir / f"{accession}.sig" for accession in accessions]


def list_db_numbers(manifests_dir: Path) -> list[int]:
    numbers = []
    for path in manifests_dir.glob("db*.pickle"):
        try:
            numbers.append(int(path.stem[2:]))
        except ValueError:
            continue
    return sorted(numbers)


def determine_next_index_number(
    *,
    output_paths: OutputPaths,
    state_metagenomes: Path | None,
    index_min_iterator: int,
) -> int:
    max_number = index_min_iterator - 1
    for number in list_db_numbers(output_paths.manifests):
        max_number = max(max_number, number)
    if state_metagenomes is not None:
        for number in list_db_numbers(state_metagenomes / "manifests"):
            max_number = max(max_number, number)
        state_json = state_metagenomes.parent.parent / "builder-state.json"
        state_data = load_json(state_json, {})
        if "next_index_number" in state_data:
            max_number = max(max_number, int(state_data["next_index_number"]) - 1)
    return max(max_number + 1, index_min_iterator)


def load_seed_manifest(
    mode: str, state_metagenomes: Path | None, output_paths: OutputPaths
) -> set[str]:
    if mode == "incremental" and state_metagenomes is not None:
        return set(load_pickle(state_metagenomes / "manifest.pickle", []))
    return set(load_pickle(output_paths.manifest, []))


def load_failed_downloads(output_paths: OutputPaths) -> set[str]:
    return set(load_pickle(output_paths.failed_downloads, set()))


def save_failed_downloads(
    output_paths: OutputPaths, failed_downloads: set[str]
) -> None:
    save_pickle(output_paths.failed_downloads, failed_downloads)


def build_pending_accessions(
    *,
    all_accessions: list[str],
    manifest_ids: set[str],
    updates_dir: Path,
    failed_downloads: set[str],
    retry_failed: bool,
) -> list[str]:
    queued = set(get_update_accessions(updates_dir))
    pending = []
    for accession in all_accessions:
        if accession in manifest_ids or accession in queued:
            continue
        if not retry_failed and accession in failed_downloads:
            continue
        pending.append(accession)
    return pending


def download_one_signature(
    accession: str,
    updates_dir: Path,
    timeout: int,
) -> tuple[str, bool, str | None]:
    destination = updates_dir / f"{accession}.sig"
    if destination.exists():
        return accession, True, None
    url = f"{SIGNATURE_ENDPOINT}/{accession}"
    ssl_context = ssl.create_default_context()
    with tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(updates_dir),
        prefix=f"{accession}.",
        suffix=".tmp",
    ) as handle:
        temp_name = Path(handle.name)
        try:
            with urllib.request.urlopen(
                url, timeout=timeout, context=ssl_context
            ) as response:
                shutil.copyfileobj(response, handle)
            os.replace(temp_name, destination)
            return accession, True, None
        except urllib.error.HTTPError as exc:
            return accession, False, f"HTTP {exc.code}"
        except Exception as exc:  # pragma: no cover - exercised via higher-level tests
            return accession, False, str(exc)
        finally:
            if temp_name.exists():
                temp_name.unlink()


def download_signatures(
    *,
    accessions: list[str],
    output_paths: OutputPaths,
    timeout: int,
    max_simultaneous: int,
    failed_downloads: set[str],
) -> tuple[list[str], set[str]]:
    if not accessions:
        return [], failed_downloads
    successful = []
    max_workers = max(1, min(max_simultaneous, len(accessions)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                download_one_signature,
                accession,
                output_paths.updates,
                timeout,
            ): accession
            for accession in accessions
        }
        for future in concurrent.futures.as_completed(future_map):
            accession, succeeded, _error = future.result()
            if succeeded:
                failed_downloads.discard(accession)
                successful.append(accession)
            else:
                failed_downloads.add(accession)
    save_failed_downloads(output_paths, failed_downloads)
    return sorted(successful), failed_downloads


def fill_download_batch(
    *,
    pending_accessions: list[str],
    output_paths: OutputPaths,
    batch_size: int,
    timeout: int,
    max_simultaneous: int,
    failed_downloads: set[str],
) -> tuple[list[str], list[str], set[str]]:
    downloaded = list(get_update_accessions(output_paths.updates))
    remaining_pending = list(pending_accessions)
    while len(downloaded) < batch_size and remaining_pending:
        remaining_capacity = batch_size - len(downloaded)
        attempted = remaining_pending[:remaining_capacity]
        remaining_pending = remaining_pending[remaining_capacity:]
        successful, failed_downloads = download_signatures(
            accessions=attempted,
            output_paths=output_paths,
            timeout=timeout,
            max_simultaneous=max_simultaneous,
            failed_downloads=failed_downloads,
        )
        downloaded.extend(successful)
    return sorted(set(downloaded)), remaining_pending, failed_downloads


def write_signature_list(sig_paths: list[Path], output_file: Path) -> None:
    with output_file.open("w", encoding="utf-8") as handle:
        for sig_path in sig_paths:
            handle.write(f"{sig_path}\n")


def build_single_kmer_index(
    *,
    sig_list: Path,
    output_paths: OutputPaths,
    index_number: int,
    ksize: int,
    worker_cores: int,
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"wort-index-{ksize}-") as work_dir_name:
        work_dir = Path(work_dir_name)
        index_dir = work_dir / f"{ksize}mers-db{index_number}.rocksdb"
        command = [
            "sourmash",
            "scripts",
            "index",
            "--ksize",
            str(ksize),
            "--moltype",
            "DNA",
            "--scaled",
            "1000",
            "--cores",
            str(worker_cores),
            "--no-store-sketches",
            "--output",
            str(index_dir),
            str(sig_list),
        ]
        subprocess.run(command, check=True)
        destination = output_paths.index / index_dir.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(index_dir), str(destination))


def build_index_batch(
    *,
    sig_paths: list[Path],
    output_paths: OutputPaths,
    index_number: int,
    cores: int | None,
    completed_kmers: list[int] | None = None,
    state_callback=None,
) -> list[int]:
    worker_cores = cores or max(1, min(8, math.floor(os.cpu_count() * 0.8)))
    completed = list(completed_kmers or [])
    with tempfile.TemporaryDirectory(prefix="wort-index-") as work_dir_name:
        work_dir = Path(work_dir_name)
        sig_list = work_dir / "sig-list.txt"
        write_signature_list(sig_paths, sig_list)
        for ksize in KMERS:
            if ksize in completed:
                continue
            build_single_kmer_index(
                sig_list=sig_list,
                output_paths=output_paths,
                index_number=index_number,
                ksize=ksize,
                worker_cores=worker_cores,
            )
            completed.append(ksize)
            if state_callback is not None:
                state_callback(sorted(completed))
    return sorted(completed)


def update_manifests(
    *,
    accessions: list[str],
    output_paths: OutputPaths,
    manifest_ids: set[str],
    index_number: int,
) -> set[str]:
    save_pickle(output_paths.manifests / f"db{index_number}.pickle", sorted(accessions))
    manifest_ids = set(manifest_ids) | set(accessions)
    save_pickle(output_paths.manifest, sorted(manifest_ids))
    return manifest_ids


def finalize_batch_files(
    *,
    sig_paths: list[Path],
    output_paths: OutputPaths,
    retain_indexed_signatures: bool,
) -> None:
    if retain_indexed_signatures:
        for sig_path in sig_paths:
            destination = output_paths.signatures / sig_path.name
            if not sig_path.exists():
                if destination.exists():
                    continue
                raise FileNotFoundError(f"cannot finalize missing signature {sig_path}")
            if destination.exists():
                destination.unlink()
            shutil.move(str(sig_path), str(destination))
        return
    for sig_path in sig_paths:
        if sig_path.exists():
            sig_path.unlink()


def move_batch_to_failed(sig_paths: list[Path], output_paths: OutputPaths) -> None:
    for sig_path in sig_paths:
        if not sig_path.exists():
            continue
        destination = output_paths.indexing_failed / sig_path.name
        if destination.exists():
            destination.unlink()
        shutil.move(str(sig_path), str(destination))


def write_state_file(
    *,
    output_paths: OutputPaths,
    next_index_number: int,
    manifest_ids: set[str],
    failed_downloads: set[str],
    remaining_accessions: int,
    batches_completed: int,
    all_accessions_digest: str,
    active_batch: dict | None = None,
) -> None:
    save_json(
        output_paths.state_json,
        {
            "active_batch": active_batch,
            "accessions_digest": all_accessions_digest,
            "batches_completed": batches_completed,
            "failed_downloads": sorted(failed_downloads),
            "manifest_entries": len(manifest_ids),
            "next_index_number": next_index_number,
            "remaining_accessions": remaining_accessions,
        },
    )


def get_index_output_paths(output_paths: OutputPaths, index_number: int) -> list[Path]:
    return [
        output_paths.index / f"{ksize}mers-db{index_number}.rocksdb" for ksize in KMERS
    ]


def build_active_batch_state(
    index_number: int, accessions: list[str], phase: str
) -> dict:
    return {
        "accessions": list(accessions),
        "completed_kmers": [],
        "index_number": index_number,
        "phase": phase,
    }


def build_active_batch_state_with_progress(
    index_number: int,
    accessions: list[str],
    phase: str,
    completed_kmers: list[int] | None,
) -> dict:
    return {
        "accessions": list(accessions),
        "completed_kmers": sorted(completed_kmers or []),
        "index_number": index_number,
        "phase": phase,
    }


def infer_completed_kmers(output_paths: OutputPaths, index_number: int) -> list[int]:
    completed = []
    for ksize in KMERS:
        if (output_paths.index / f"{ksize}mers-db{index_number}.rocksdb").exists():
            completed.append(ksize)
    return completed


def complete_indexed_batch(
    *,
    batch_state: dict,
    output_paths: OutputPaths,
    manifest_ids: set[str],
    failed_downloads: set[str],
    pending_accessions: list[str],
    batches_completed: int,
    retain_indexed_signatures: bool,
    all_accessions_digest: str,
) -> tuple[set[str], int]:
    accessions = list(batch_state["accessions"])
    index_number = int(batch_state["index_number"])
    sig_paths = get_downloaded_signature_paths(output_paths.updates, accessions)
    manifest_ids = update_manifests(
        accessions=accessions,
        output_paths=output_paths,
        manifest_ids=manifest_ids,
        index_number=index_number,
    )
    write_state_file(
        output_paths=output_paths,
        next_index_number=index_number + 1,
        manifest_ids=manifest_ids,
        failed_downloads=failed_downloads,
        remaining_accessions=len(pending_accessions),
        batches_completed=batches_completed,
        all_accessions_digest=all_accessions_digest,
        active_batch=build_active_batch_state(index_number, accessions, "manifested"),
    )
    finalize_batch_files(
        sig_paths=sig_paths,
        output_paths=output_paths,
        retain_indexed_signatures=retain_indexed_signatures,
    )
    batches_completed += 1
    write_state_file(
        output_paths=output_paths,
        next_index_number=index_number + 1,
        manifest_ids=manifest_ids,
        failed_downloads=failed_downloads,
        remaining_accessions=len(pending_accessions),
        batches_completed=batches_completed,
        all_accessions_digest=all_accessions_digest,
        active_batch=None,
    )
    return manifest_ids, batches_completed


def resume_active_batch(
    *,
    state_data: dict,
    output_paths: OutputPaths,
    manifest_ids: set[str],
    failed_downloads: set[str],
    pending_accessions: list[str],
    retain_indexed_signatures: bool,
    all_accessions_digest: str,
    cores: int | None,
) -> tuple[set[str], int]:
    active_batch = state_data.get("active_batch")
    if not active_batch:
        return manifest_ids, int(state_data.get("batches_completed", 0))
    if state_data.get("accessions_digest") not in (None, all_accessions_digest):
        raise RuntimeError(
            "accession file changed since the last interrupted run; resume is unsafe"
        )
    accessions = list(active_batch["accessions"])
    index_number = int(active_batch["index_number"])
    phase = active_batch["phase"]
    journaled_completed_kmers = sorted(active_batch.get("completed_kmers", []))
    inferred_completed_kmers = infer_completed_kmers(output_paths, index_number)
    missing_completed = [
        ksize
        for ksize in journaled_completed_kmers
        if ksize not in inferred_completed_kmers
    ]
    if missing_completed:
        raise RuntimeError(
            "cannot resume interrupted batch because some completed index outputs are "
            f"missing for k-mers: {', '.join(str(k) for k in missing_completed)}"
        )
    completed_kmers = sorted(
        set(journaled_completed_kmers) | set(inferred_completed_kmers)
    )
    if phase in {"downloaded", "indexing"}:
        sig_paths = get_downloaded_signature_paths(output_paths.updates, accessions)
        missing = [path.name for path in sig_paths if not path.exists()]
        if missing:
            raise RuntimeError(
                "cannot resume interrupted batch because some downloaded signatures "
                f"are missing from updates/: {', '.join(missing)}"
            )
        completed_kmers = build_index_batch(
            sig_paths=sig_paths,
            output_paths=output_paths,
            index_number=index_number,
            cores=cores,
            completed_kmers=completed_kmers,
            state_callback=lambda kmers: write_state_file(
                output_paths=output_paths,
                next_index_number=index_number,
                manifest_ids=manifest_ids,
                failed_downloads=failed_downloads,
                remaining_accessions=len(pending_accessions),
                batches_completed=int(state_data.get("batches_completed", 0)),
                all_accessions_digest=all_accessions_digest,
                active_batch=build_active_batch_state_with_progress(
                    index_number, accessions, "indexing", kmers
                ),
            ),
        )
        state_data = copy.deepcopy(state_data)
        state_data["active_batch"] = build_active_batch_state_with_progress(
            index_number, accessions, "indexed", completed_kmers
        )
        save_json(output_paths.state_json, state_data)
        phase = "indexed"
        active_batch = state_data["active_batch"]
    if phase == "indexed":
        index_paths = get_index_output_paths(output_paths, index_number)
        missing_indexes = [path.name for path in index_paths if not path.exists()]
        if missing_indexes:
            raise RuntimeError(
                "cannot resume interrupted batch because some index outputs are "
                f"missing: {', '.join(missing_indexes)}"
            )
        manifest_ids, batches_completed = complete_indexed_batch(
            batch_state=active_batch,
            output_paths=output_paths,
            manifest_ids=manifest_ids,
            failed_downloads=failed_downloads,
            pending_accessions=pending_accessions,
            batches_completed=int(state_data.get("batches_completed", 0)),
            retain_indexed_signatures=retain_indexed_signatures,
            all_accessions_digest=all_accessions_digest,
        )
        return manifest_ids, batches_completed
    if phase == "manifested":
        sig_paths = get_downloaded_signature_paths(output_paths.updates, accessions)
        finalize_batch_files(
            sig_paths=sig_paths,
            output_paths=output_paths,
            retain_indexed_signatures=retain_indexed_signatures,
        )
        batches_completed = int(state_data.get("batches_completed", 0)) + 1
        write_state_file(
            output_paths=output_paths,
            next_index_number=index_number + 1,
            manifest_ids=manifest_ids,
            failed_downloads=failed_downloads,
            remaining_accessions=len(pending_accessions),
            batches_completed=batches_completed,
            all_accessions_digest=all_accessions_digest,
            active_batch=None,
        )
        return manifest_ids, batches_completed
    if phase not in {"downloaded", "indexing", "indexed", "manifested"}:
        raise RuntimeError(
            f"unknown active batch phase '{phase}' in builder-state.json"
        )
    return manifest_ids, int(state_data.get("batches_completed", 0))


def package_output(output_paths: OutputPaths) -> Path:
    tar_path = output_paths.root / "wort-index-builder-output.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(output_paths.root / "SRA", arcname="SRA")
        archive.add(output_paths.state_json, arcname=output_paths.state_json.name)
    return tar_path


def run_pipeline(args: argparse.Namespace) -> int:
    if args.index_max_signatures <= 0:
        raise ValueError("--index-max-signatures must be greater than zero")
    state_metagenomes = resolve_metagenomes_dir(args.state_dir)
    output_paths = create_output_paths(args.output_dir)
    all_accessions = read_accessions(args.accessions_file)
    all_accessions_digest = compute_accessions_digest(all_accessions)
    manifest_ids = load_seed_manifest(args.mode, state_metagenomes, output_paths)
    if output_paths.manifest.exists():
        manifest_ids |= set(load_pickle(output_paths.manifest, []))
    failed_downloads = load_failed_downloads(output_paths)
    next_index_number = determine_next_index_number(
        output_paths=output_paths,
        state_metagenomes=state_metagenomes,
        index_min_iterator=args.index_min_iterator,
    )
    pending_accessions = build_pending_accessions(
        all_accessions=all_accessions,
        manifest_ids=manifest_ids,
        updates_dir=output_paths.updates,
        failed_downloads=failed_downloads,
        retry_failed=args.retry_failed,
    )
    state_data = load_json(output_paths.state_json, {})
    manifest_ids, batches_completed = resume_active_batch(
        state_data=state_data,
        output_paths=output_paths,
        manifest_ids=manifest_ids,
        failed_downloads=failed_downloads,
        pending_accessions=pending_accessions,
        retain_indexed_signatures=args.retain_indexed_signatures,
        all_accessions_digest=all_accessions_digest,
        cores=args.cores,
    )
    if output_paths.manifest.exists():
        manifest_ids = set(load_pickle(output_paths.manifest, []))
    pending_accessions = build_pending_accessions(
        all_accessions=all_accessions,
        manifest_ids=manifest_ids,
        updates_dir=output_paths.updates,
        failed_downloads=failed_downloads,
        retry_failed=args.retry_failed,
    )
    next_index_number = determine_next_index_number(
        output_paths=output_paths,
        state_metagenomes=state_metagenomes,
        index_min_iterator=args.index_min_iterator,
    )

    while True:
        queued_updates = get_update_accessions(output_paths.updates)
        if queued_updates and len(queued_updates) > args.index_max_signatures:
            raise RuntimeError(
                "updates directory contains more signatures than one index batch"
            )
        if queued_updates:
            batch_accessions = queued_updates
        else:
            batch_accessions, pending_accessions, failed_downloads = (
                fill_download_batch(
                    pending_accessions=pending_accessions,
                    output_paths=output_paths,
                    batch_size=args.index_max_signatures,
                    timeout=args.timeout,
                    max_simultaneous=args.max_simultaneous,
                    failed_downloads=failed_downloads,
                )
            )
        if not batch_accessions:
            break

        sig_paths = get_downloaded_signature_paths(
            output_paths.updates, batch_accessions
        )
        write_state_file(
            output_paths=output_paths,
            next_index_number=next_index_number,
            manifest_ids=manifest_ids,
            failed_downloads=failed_downloads,
            remaining_accessions=len(pending_accessions),
            batches_completed=batches_completed,
            all_accessions_digest=all_accessions_digest,
            active_batch=build_active_batch_state_with_progress(
                next_index_number, batch_accessions, "indexing", []
            ),
        )
        try:
            completed_kmers = build_index_batch(
                sig_paths=sig_paths,
                output_paths=output_paths,
                index_number=next_index_number,
                cores=args.cores,
                completed_kmers=[],
                state_callback=lambda kmers: write_state_file(
                    output_paths=output_paths,
                    next_index_number=next_index_number,
                    manifest_ids=manifest_ids,
                    failed_downloads=failed_downloads,
                    remaining_accessions=len(pending_accessions),
                    batches_completed=batches_completed,
                    all_accessions_digest=all_accessions_digest,
                    active_batch=build_active_batch_state_with_progress(
                        next_index_number, batch_accessions, "indexing", kmers
                    ),
                ),
            )
        except subprocess.CalledProcessError:
            move_batch_to_failed(sig_paths, output_paths)
            write_state_file(
                output_paths=output_paths,
                next_index_number=next_index_number,
                manifest_ids=manifest_ids,
                failed_downloads=failed_downloads,
                remaining_accessions=len(pending_accessions),
                batches_completed=batches_completed,
                all_accessions_digest=all_accessions_digest,
                active_batch=None,
            )
            raise

        write_state_file(
            output_paths=output_paths,
            next_index_number=next_index_number,
            manifest_ids=manifest_ids,
            failed_downloads=failed_downloads,
            remaining_accessions=len(pending_accessions),
            batches_completed=batches_completed,
            all_accessions_digest=all_accessions_digest,
            active_batch=build_active_batch_state_with_progress(
                next_index_number, batch_accessions, "indexed", completed_kmers
            ),
        )
        manifest_ids, batches_completed = complete_indexed_batch(
            batch_state=build_active_batch_state_with_progress(
                next_index_number, batch_accessions, "indexed", completed_kmers
            ),
            output_paths=output_paths,
            manifest_ids=manifest_ids,
            failed_downloads=failed_downloads,
            pending_accessions=pending_accessions,
            batches_completed=batches_completed,
            retain_indexed_signatures=args.retain_indexed_signatures,
            all_accessions_digest=all_accessions_digest,
        )
        next_index_number += 1

    write_state_file(
        output_paths=output_paths,
        next_index_number=next_index_number,
        manifest_ids=manifest_ids,
        failed_downloads=failed_downloads,
        remaining_accessions=0,
        batches_completed=batches_completed,
        all_accessions_digest=all_accessions_digest,
        active_batch=None,
    )
    if args.package == "tar":
        package_output(output_paths)
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run_pipeline(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
