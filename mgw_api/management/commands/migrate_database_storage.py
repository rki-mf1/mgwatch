import pickle
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import batch_manifest
from mgw_api.database_config import batch_root
from mgw_api.database_config import failed_downloads_path
from mgw_api.database_config import get_database_config
from mgw_api.database_config import index_path
from mgw_api.database_config import metadata_cache_dir
from mgw_api.database_config import profile_manifest
from mgw_api.database_config import read_accession_parquet
from mgw_api.database_config import signature_dirs
from mgw_api.database_config import write_accession_parquet


def _load_pickle(path):
    if not path.exists():
        return []
    with path.open("rb") as handle:
        return pickle.load(handle)


def _move_path(source, target, *, dry_run):
    if not source.exists():
        return False
    if target.exists():
        raise CommandError(f"Refusing to overwrite existing target: {target}")
    if dry_run:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return True


def _preflight_targets(targets):
    for target in targets:
        if target.exists():
            raise CommandError(f"Refusing to overwrite existing target: {target}")


class Command(BaseCommand):
    help = "Move legacy SRA/metagenomes storage into the configured database layout."

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DATABASE_ID)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **kwargs):
        database = get_database_config(kwargs["database"])
        if len(database.enabled_profiles) != 1:
            raise CommandError("Legacy migration expects exactly one enabled profile")
        configured_profiles = {profile.kmer: profile for profile in database.profiles}
        dry_run = kwargs["dry_run"]
        legacy_root = Path(settings.DATA_DIR) / "SRA" / "metagenomes"
        if not legacy_root.exists():
            self.stdout.write("No legacy SRA/metagenomes storage found.")
            return

        dirs = signature_dirs(database.id)
        moves = [
            (legacy_root / "updates", dirs["pending"]),
            (legacy_root / "signatures", dirs["indexed"]),
            (legacy_root / "indexing-failed", dirs["failed-indexing"]),
            (
                legacy_root / "tmp",
                settings.DATA_DIR / "search-databases" / database.id / "tmp",
            ),
        ]
        move_operations = [
            (source, target) for source, target in moves if source.exists()
        ]
        write_operations = []

        failed_pickle = legacy_root / "download_failed.pickle"
        if failed_pickle.exists():
            write_operations.append(failed_downloads_path(database.id))

        legacy_manifests = []
        migrated_profiles_by_kmer = {}
        for manifest_file in sorted((legacy_root / "manifests").glob("db*.pickle")):
            batch_number = int(manifest_file.stem.removeprefix("db"))
            batch_profiles = []
            for kmer, profile in configured_profiles.items():
                old_index = (
                    legacy_root / "index" / f"{kmer}mers-db{batch_number}.rocksdb"
                )
                if old_index.exists():
                    destination = index_path(database.id, profile, batch_number)
                    move_operations.append((old_index, destination))
                    write_operations.append(
                        batch_manifest(database.id, profile, batch_number)
                    )
                    batch_profiles.append(profile)
                    migrated_profiles_by_kmer[kmer] = profile
            legacy_manifests.append((manifest_file, batch_number, batch_profiles))

        if migrated_profiles_by_kmer:
            write_operations.extend(
                profile_manifest(database.id, profile)
                for profile in migrated_profiles_by_kmer.values()
            )

        legacy_metadata = Path(settings.DATA_DIR) / "SRA" / "metadata" / "parquet"
        if legacy_metadata.exists():
            move_operations.append((legacy_metadata, metadata_cache_dir()))

        _preflight_targets([target for _, target in move_operations] + write_operations)

        for source, target in moves:
            if _move_path(source, target, dry_run=dry_run):
                action = "Would move" if dry_run else "Moved"
                self.stdout.write(f"{action} {source} -> {target}")

        if failed_pickle.exists():
            failed = _load_pickle(failed_pickle)
            if dry_run:
                self.stdout.write(
                    f"Would convert {failed_pickle} -> {failed_downloads_path(database.id)}"
                )
            else:
                write_accession_parquet(failed_downloads_path(database.id), failed)

        for manifest_file, batch_number, batch_profiles in legacy_manifests:
            accessions = _load_pickle(manifest_file)
            for profile in batch_profiles:
                old_index = (
                    legacy_root
                    / "index"
                    / f"{profile.kmer}mers-db{batch_number}.rocksdb"
                )
                destination = index_path(database.id, profile, batch_number)
                if dry_run:
                    self.stdout.write(f"Would move {old_index} -> {destination}")
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_index), str(destination))
                target_manifest = batch_manifest(database.id, profile, batch_number)
                if dry_run:
                    self.stdout.write(f"Would write {target_manifest}")
                else:
                    write_accession_parquet(
                        target_manifest,
                        accessions,
                        batch=batch_number,
                    )

        if not dry_run:
            for profile in migrated_profiles_by_kmer.values():
                profile_accessions = []
                profile_dir = batch_root(database.id, profile, 0).parent
                for manifest in sorted(profile_dir.glob("batch-*/manifest.parquet")):
                    profile_accessions.extend(read_accession_parquet(manifest))
                write_accession_parquet(
                    profile_manifest(database.id, profile), profile_accessions
                )
        elif migrated_profiles_by_kmer:
            for profile in migrated_profiles_by_kmer.values():
                target_manifest = profile_manifest(database.id, profile)
                self.stdout.write(f"Would write {target_manifest}")

        if legacy_metadata.exists():
            target = metadata_cache_dir()
            if dry_run:
                self.stdout.write(f"Would move {legacy_metadata} -> {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy_metadata), str(target))

        self.stdout.write(self.style.SUCCESS("Storage migration completed"))
