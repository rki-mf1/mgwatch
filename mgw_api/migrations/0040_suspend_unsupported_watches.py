import functools
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations
from django.db import models

FALLBACK_KMERS = [21]
DEFAULT_DATABASE_ID = "sra_metagenomes"
LEGACY_DATABASE_ID = "SRA"


def _normalize_database_id(database_id):
    return DEFAULT_DATABASE_ID if database_id == LEGACY_DATABASE_ID else database_id


def _normalize_databases(databases):
    if not isinstance(databases, list) or not databases:
        return [DEFAULT_DATABASE_ID]
    return [_normalize_database_id(database_id) for database_id in databases]


def _load_enabled_kmers_by_database():
    config_file = Path(settings.CONFIG_DIR) / "database.yml"
    if not config_file.exists():
        return {DEFAULT_DATABASE_ID: [str(kmer) for kmer in FALLBACK_KMERS]}

    with config_file.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    enabled_kmers_by_database = {}
    for database_id, raw_database in raw_config.get("databases", {}).items():
        if not raw_database.get("enabled", True):
            continue
        enabled_kmers = []
        for profile in raw_database.get("profiles", []):
            if profile.get("enabled", True):
                kmer = str(profile["kmer"])
                if kmer not in enabled_kmers:
                    enabled_kmers.append(kmer)
        if enabled_kmers:
            enabled_kmers_by_database[database_id] = enabled_kmers

    return enabled_kmers_by_database or {
        DEFAULT_DATABASE_ID: [str(kmer) for kmer in FALLBACK_KMERS]
    }


def _enabled_kmers_for_databases(databases, enabled_kmers_by_database):
    normalized_databases = _normalize_databases(databases)
    selected_kmers = [
        enabled_kmers_by_database.get(database_id, [])
        for database_id in normalized_databases
    ]
    if not selected_kmers or any(not kmers for kmers in selected_kmers):
        return []
    shared_kmers = set(selected_kmers[0])
    for kmers in selected_kmers[1:]:
        shared_kmers &= set(kmers)
    return [kmer for kmer in selected_kmers[0] if kmer in shared_kmers]


def _first_enabled_database(enabled_kmers_by_database):
    for database_id, kmers in enabled_kmers_by_database.items():
        if kmers:
            return database_id, kmers
    return DEFAULT_DATABASE_ID, [str(kmer) for kmer in FALLBACK_KMERS]


def _default_kmers(enabled_kmers):
    return [int(enabled_kmers[0])]


def suspend_unsupported_watches(apps, schema_editor):
    enabled_kmers_by_database = _load_enabled_kmers_by_database()
    Result = apps.get_model("mgw_api", "Result")
    for result in Result.objects.filter(is_watched=True).iterator():
        kmers = getattr(result, "kmer", None)
        if not isinstance(kmers, list):
            continue
        enabled_kmers = set(
            _enabled_kmers_for_databases(
                getattr(result, "database", None),
                enabled_kmers_by_database,
            )
        )
        if {str(kmer) for kmer in kmers} - enabled_kmers:
            result.is_watched = False
            result.save(update_fields=["is_watched"])


def normalize_unsupported_settings(apps, schema_editor):
    enabled_kmers_by_database = _load_enabled_kmers_by_database()
    Settings = apps.get_model("mgw_api", "Settings")
    for settings_obj in Settings.objects.all().iterator():
        kmers = getattr(settings_obj, "kmer", None)
        if not isinstance(kmers, list):
            continue
        normalized_databases = _normalize_databases(
            getattr(settings_obj, "database", None)
        )
        database_update = None
        enabled_kmers_list = _enabled_kmers_for_databases(
            normalized_databases,
            enabled_kmers_by_database,
        )
        if not enabled_kmers_list:
            for database_id in normalized_databases:
                database_kmers = enabled_kmers_by_database.get(database_id, [])
                if database_kmers:
                    database_update = [database_id]
                    enabled_kmers_list = database_kmers
                    break
        if not enabled_kmers_list:
            fallback_database, fallback_kmers = _first_enabled_database(
                enabled_kmers_by_database
            )
            database_update = [fallback_database]
            enabled_kmers_list = fallback_kmers
        enabled_kmers = set(enabled_kmers_list)
        default_kmers = _default_kmers(
            enabled_kmers_list or [str(kmer) for kmer in FALLBACK_KMERS]
        )
        supported_kmers = [kmer for kmer in kmers if str(kmer) in enabled_kmers]
        normalized_kmers = supported_kmers or default_kmers
        update_fields = []
        if normalized_kmers != kmers:
            settings_obj.kmer = normalized_kmers
            update_fields.append("kmer")
        if database_update and database_update != getattr(
            settings_obj, "database", None
        ):
            settings_obj.database = database_update
            update_fields.append("database")
        if update_fields:
            settings_obj.save(update_fields=update_fields)


def migrate_unsupported_search_preferences(apps, schema_editor):
    suspend_unsupported_watches(apps, schema_editor)
    normalize_unsupported_settings(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0039_rename_sra_database"),
    ]

    operations = [
        migrations.RunPython(
            migrate_unsupported_search_preferences,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="settings",
            name="database",
            field=models.JSONField(
                default=functools.partial(
                    list,
                    *(["sra_metagenomes"],),
                    **{},
                ),
                help_text="List of databases",
            ),
        ),
    ]
