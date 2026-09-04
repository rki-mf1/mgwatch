from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgw_api", "0037_fasta_initial_filter_spec"),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemStatistic",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("index_sample_count", "Index samples"),
                            ("metadata_sample_count", "Metadata samples"),
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
                        unique=True,
                    ),
                ),
                ("value", models.FloatField(default=0)),
                ("observation_count", models.PositiveIntegerField(default=0)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("recorded_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["metric"],
            },
        ),
        migrations.CreateModel(
            name="SystemStatisticSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("index_sample_count", "Index samples"),
                            ("metadata_sample_count", "Metadata samples"),
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
                ("value", models.FloatField(default=0)),
                ("observation_count", models.PositiveIntegerField(default=0)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("recorded_at", models.DateTimeField()),
            ],
            options={
                "ordering": ["-recorded_at", "-pk"],
            },
        ),
        migrations.AddIndex(
            model_name="systemstatisticsnapshot",
            index=models.Index(
                fields=["metric", "-recorded_at"],
                name="mgw_api_sys_metric_2da4d7_idx",
            ),
        ),
    ]
