import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import polars as pl
import yaml
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

DEFAULT_DATABASE_ID = "sra_metagenomes"
LEGACY_DATABASE_ID = "SRA"
DATABASE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SUPPORTED_PROFILE_KMERS = {21, 31, 51}
SUPPORTED_PROFILE_MOLTYPE = "DNA"
SUPPORTED_PROFILE_SCALED = 1000


@dataclass(frozen=True)
class IndexProfile:
    kmer: int
    scaled: int
    moltype: str = "DNA"
    enabled: bool = True

    @property
    def key(self):
        return f"k{self.kmer}-scaled{self.scaled}"


@dataclass(frozen=True)
class DatabaseConfig:
    id: str
    label: str
    enabled: bool
    mongodb_collection: str
    metadata_filter: dict
    wort_manifest_url: str
    wort_signature_endpoint: str
    profiles: tuple[IndexProfile, ...]
    download: dict
    indexing: dict

    @property
    def enabled_profiles(self):
        return tuple(profile for profile in self.profiles if profile.enabled)


def normalize_database_id(database_id):
    return DEFAULT_DATABASE_ID if database_id == LEGACY_DATABASE_ID else database_id


def normalize_database_list(databases):
    return [normalize_database_id(database_id) for database_id in databases]


def _load_yaml_config():
    config_file = Path(settings.CONFIG_DIR) / "database.yml"
    if not config_file.exists():
        raise ImproperlyConfigured(f"Database config file not found: {config_file}")
    with config_file.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _validate_database_id(database_id):
    if not DATABASE_ID_RE.match(database_id):
        raise ImproperlyConfigured(
            f"Database id must be lowercase snakecase: {database_id}"
        )


def _load_profile(raw_profile):
    profile = IndexProfile(
        kmer=int(raw_profile["kmer"]),
        scaled=int(raw_profile.get("scaled", 1000)),
        moltype=str(raw_profile.get("moltype", SUPPORTED_PROFILE_MOLTYPE)).upper(),
        enabled=bool(raw_profile.get("enabled", True)),
    )
    if profile.kmer <= 0 or profile.scaled <= 0:
        raise ImproperlyConfigured("Profile kmer and scaled must be positive")
    if profile.kmer not in SUPPORTED_PROFILE_KMERS:
        raise ImproperlyConfigured(
            f"Unsupported profile kmer {profile.kmer}; "
            f"supported values are {sorted(SUPPORTED_PROFILE_KMERS)}"
        )
    if profile.scaled != SUPPORTED_PROFILE_SCALED:
        raise ImproperlyConfigured(
            f"Unsupported profile scaled {profile.scaled}; "
            f"supported value is {SUPPORTED_PROFILE_SCALED}"
        )
    if profile.moltype != SUPPORTED_PROFILE_MOLTYPE:
        raise ImproperlyConfigured(
            f"Unsupported profile moltype {profile.moltype}; "
            f"supported value is {SUPPORTED_PROFILE_MOLTYPE}"
        )
    return profile


def _load_database(database_id, raw_database):
    _validate_database_id(database_id)
    profiles = tuple(_load_profile(raw) for raw in raw_database.get("profiles", []))
    if raw_database.get("enabled", True) and not any(
        profile.enabled for profile in profiles
    ):
        raise ImproperlyConfigured(
            f"Enabled database {database_id} must define an enabled profile"
        )
    metadata_filter = raw_database.get("metadata_filter", {})
    include = metadata_filter.get("include", {})
    exclude = metadata_filter.get("exclude", {})
    unsupported_include = set(include) - {"librarysource"}
    unsupported_exclude = set(exclude) - {"descriptive_fields_contain"}
    if unsupported_include or unsupported_exclude:
        raise ImproperlyConfigured(
            f"Unsupported metadata filter for {database_id}: "
            f"include={sorted(unsupported_include)} exclude={sorted(unsupported_exclude)}"
        )
    return DatabaseConfig(
        id=database_id,
        label=raw_database.get("label", database_id),
        enabled=bool(raw_database.get("enabled", True)),
        mongodb_collection=raw_database.get(
            "mongodb_collection", f"{database_id}_metadata"
        ),
        metadata_filter=metadata_filter,
        wort_manifest_url=raw_database["wort_manifest_url"],
        wort_signature_endpoint=raw_database["wort_signature_endpoint"].rstrip("/"),
        profiles=profiles,
        download=raw_database.get("download", {}),
        indexing=raw_database.get("indexing", {}),
    )


@lru_cache(maxsize=1)
def get_database_configs():
    raw_config = _load_yaml_config()
    raw_databases = raw_config.get("databases", {})
    databases = {
        database_id: _load_database(database_id, raw_database)
        for database_id, raw_database in raw_databases.items()
    }
    if DEFAULT_DATABASE_ID not in databases:
        raise ImproperlyConfigured(f"{DEFAULT_DATABASE_ID} is required")
    return databases


def get_database_config(database_id=DEFAULT_DATABASE_ID):
    database_id = normalize_database_id(database_id)
    try:
        return get_database_configs()[database_id]
    except KeyError as exc:
        raise ImproperlyConfigured(f"Unknown database: {database_id}") from exc


def enabled_databases():
    return [
        database for database in get_database_configs().values() if database.enabled
    ]


def database_root(database_id=DEFAULT_DATABASE_ID):
    database_id = normalize_database_id(database_id)
    return Path(settings.DATA_DIR) / "search-databases" / database_id


def metadata_cache_dir():
    return Path(settings.DATA_DIR) / "metadata" / "sra" / "parquet"


def metadata_init_flag():
    return Path(settings.DATA_DIR) / "metadata" / "sra" / "initial-setup.done"


def profile_root(database_id, profile):
    return database_root(database_id) / "profiles" / profile.key


def profile_manifest(database_id, profile):
    return profile_root(database_id, profile) / "manifest.parquet"


def batch_root(database_id, profile, batch_number):
    return profile_root(database_id, profile) / f"batch-{batch_number}"


def batch_manifest(database_id, profile, batch_number):
    return batch_root(database_id, profile, batch_number) / "manifest.parquet"


def index_path(database_id, profile, batch_number):
    return batch_root(database_id, profile, batch_number) / "index.rocksdb"


def signature_dirs(database_id=DEFAULT_DATABASE_ID):
    root = database_root(database_id) / "signatures"
    return {
        "pending": root / "pending",
        "indexed": root / "indexed",
        "failed-indexing": root / "failed-indexing",
    }


def failed_downloads_path(database_id=DEFAULT_DATABASE_ID):
    return database_root(database_id) / "signatures" / "failed-downloads.parquet"


def ensure_database_dirs(database_id=DEFAULT_DATABASE_ID):
    database = get_database_config(database_id)
    paths = {
        **signature_dirs(database.id),
        "tmp": database_root(database.id) / "tmp",
    }
    for profile in database.enabled_profiles:
        paths[f"profile-{profile.key}"] = profile_root(database.id, profile)
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def read_accession_parquet(path):
    path = Path(path)
    if not path.exists():
        return []
    return pl.read_parquet(path).get_column("accession").cast(pl.String).to_list()


def write_accession_parquet(path, accessions, **extra_columns):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    accessions = sorted(set(accessions))
    data = {"accession": accessions}
    for key, value in extra_columns.items():
        if isinstance(value, list):
            data[key] = value
        else:
            data[key] = [value] * len(accessions)
    tmp_path = path.with_name(f".{path.name}.tmp")
    pl.DataFrame(data).write_parquet(tmp_path)
    tmp_path.replace(path)
