import functools

from django.db import migrations
from django.db import models

ENABLED_KMERS = {"21"}
DEFAULT_KMERS = [21]


def suspend_unsupported_watches(apps, schema_editor):
    Result = apps.get_model("mgw_api", "Result")
    for result in Result.objects.filter(is_watched=True).iterator():
        kmers = getattr(result, "kmer", None)
        if not isinstance(kmers, list):
            continue
        if {str(kmer) for kmer in kmers} - ENABLED_KMERS:
            result.is_watched = False
            result.save(update_fields=["is_watched"])


def normalize_unsupported_settings(apps, schema_editor):
    Settings = apps.get_model("mgw_api", "Settings")
    for settings in Settings.objects.all().iterator():
        kmers = getattr(settings, "kmer", None)
        if not isinstance(kmers, list):
            continue
        supported_kmers = [kmer for kmer in kmers if str(kmer) in ENABLED_KMERS]
        normalized_kmers = supported_kmers or DEFAULT_KMERS
        if normalized_kmers != kmers:
            settings.kmer = normalized_kmers
            settings.save(update_fields=["kmer"])


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
