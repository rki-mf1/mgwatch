from django.db import migrations
from django.db import models

COUNT_METRICS = {
    "index_sample_count",
    "metadata_sample_count",
    "wort_signature_sample_count",
}
DEFAULT_DATABASE_ID = "sra_metagenomes"
LEGACY_DATABASE_ID = "SRA"


def statistic_scope(database, profile=""):
    return f"{database}:{profile}" if profile else database


def scope_legacy_count_statistics(apps, schema_editor):
    SystemStatistic = apps.get_model("mgw_api", "SystemStatistic")
    for statistic in SystemStatistic.objects.filter(metric__in=COUNT_METRICS):
        database = statistic.details.get("database", DEFAULT_DATABASE_ID)
        if database == LEGACY_DATABASE_ID:
            database = DEFAULT_DATABASE_ID
        profile = statistic.details.get("profile", "")
        statistic.scope = statistic_scope(database, profile)
        statistic.save(update_fields=["scope"])


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0040_suspend_unsupported_watches"),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemstatistic",
            name="metric",
            field=models.CharField(
                choices=[
                    ("index_sample_count", "Index samples"),
                    ("metadata_sample_count", "Metadata samples"),
                    ("wort_signature_sample_count", "Wort signature samples"),
                    (
                        "average_search_rate_sequences_per_second",
                        "Average search rate",
                    ),
                    (
                        "metadata_update_runtime_seconds",
                        "Metadata update runtime",
                    ),
                    (
                        "index_update_runtime_seconds",
                        "Index update runtime",
                    ),
                    (
                        "download_index_runtime_seconds",
                        "Sample download/index runtime",
                    ),
                ],
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="systemstatisticsnapshot",
            name="metric",
            field=models.CharField(
                choices=[
                    ("index_sample_count", "Index samples"),
                    ("metadata_sample_count", "Metadata samples"),
                    ("wort_signature_sample_count", "Wort signature samples"),
                    (
                        "average_search_rate_sequences_per_second",
                        "Average search rate",
                    ),
                    (
                        "metadata_update_runtime_seconds",
                        "Metadata update runtime",
                    ),
                    (
                        "index_update_runtime_seconds",
                        "Index update runtime",
                    ),
                    (
                        "download_index_runtime_seconds",
                        "Sample download/index runtime",
                    ),
                ],
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="systemstatistic",
            name="scope",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.RunPython(
            scope_legacy_count_statistics,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="systemstatistic",
            constraint=models.UniqueConstraint(
                fields=("metric", "scope"),
                name="mgw_api_systemstat_metric_scope_uniq",
            ),
        ),
        migrations.AlterModelOptions(
            name="systemstatistic",
            options={"ordering": ["metric", "scope"]},
        ),
    ]
