import functools

from django.db import migrations
from django.db import models


ENABLED_KMERS = {"21"}


def suspend_unsupported_watches(apps, schema_editor):
    Result = apps.get_model("mgw_api", "Result")
    for result in Result.objects.filter(is_watched=True).iterator():
        kmers = getattr(result, "kmer", None)
        if not isinstance(kmers, list):
            continue
        if not {str(kmer) for kmer in kmers} & ENABLED_KMERS:
            result.is_watched = False
            result.save(update_fields=["is_watched"])


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0039_rename_sra_database"),
    ]

    operations = [
        migrations.RunPython(
            suspend_unsupported_watches,
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
