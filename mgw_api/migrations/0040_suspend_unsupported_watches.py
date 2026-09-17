import functools
from pathlib import Path

import yaml
from django.conf import settings
from django.db import migrations
from django.db import models

FALLBACK_KMERS = [21]


def _load_enabled_kmers():
    config_file = Path(settings.CONFIG_DIR) / "database.yml"
    if not config_file.exists():
        return [str(kmer) for kmer in FALLBACK_KMERS]

    with config_file.open("r", encoding="utf-8") as handle:
        raw_config = yaml.safe_load(handle) or {}

    enabled_kmers = []
    for raw_database in raw_config.get("databases", {}).values():
        if not raw_database.get("enabled", True):
            continue
        for profile in raw_database.get("profiles", []):
            if profile.get("enabled", True):
                kmer = str(profile["kmer"])
                if kmer not in enabled_kmers:
                    enabled_kmers.append(kmer)

    return enabled_kmers or [str(kmer) for kmer in FALLBACK_KMERS]


def _default_kmers(enabled_kmers):
    return [int(enabled_kmers[0])]


def suspend_unsupported_watches(apps, schema_editor):
    enabled_kmers = set(_load_enabled_kmers())
    Result = apps.get_model("mgw_api", "Result")
    for result in Result.objects.filter(is_watched=True).iterator():
        kmers = getattr(result, "kmer", None)
        if not isinstance(kmers, list):
            continue
        if {str(kmer) for kmer in kmers} - enabled_kmers:
            result.is_watched = False
            result.save(update_fields=["is_watched"])


def normalize_unsupported_settings(apps, schema_editor):
    enabled_kmers_list = _load_enabled_kmers()
    enabled_kmers = set(enabled_kmers_list)
    default_kmers = _default_kmers(enabled_kmers_list)
    Settings = apps.get_model("mgw_api", "Settings")
    for settings_obj in Settings.objects.all().iterator():
        kmers = getattr(settings_obj, "kmer", None)
        if not isinstance(kmers, list):
            continue
        supported_kmers = [kmer for kmer in kmers if str(kmer) in enabled_kmers]
        normalized_kmers = supported_kmers or default_kmers
        if normalized_kmers != kmers:
            settings_obj.kmer = normalized_kmers
            settings_obj.save(update_fields=["kmer"])


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
