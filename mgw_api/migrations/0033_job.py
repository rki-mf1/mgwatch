from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0032_remove_result_size_result_num_results"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Job",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_type", models.CharField(choices=[("signature_pipeline", "Signature pipeline"), ("search", "Search"), ("create_signature", "Create signature"), ("metadata", "Metadata"), ("downloads", "Downloads"), ("index", "Index"), ("watch", "Watch"), ("daily", "Daily")], max_length=64)),
                ("state", models.CharField(choices=[("queued", "Queued"), ("waiting", "Waiting"), ("starting", "Starting"), ("running", "Running"), ("combining_results", "Combining results"), ("saving_result", "Saving result"), ("completed", "Completed"), ("failed", "Failed")], default="queued", max_length=32)),
                ("status_message", models.CharField(default="Queued", max_length=255)),
                ("celery_task_id", models.CharField(blank=True, max_length=255)),
                ("queue", models.CharField(blank=True, max_length=64)),
                ("lock_name", models.CharField(blank=True, max_length=128)),
                ("progress_current", models.PositiveIntegerField(default=0)),
                ("progress_total", models.PositiveIntegerField(default=0)),
                ("error_message", models.TextField(blank=True)),
                ("failure_details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("fasta", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="mgw_api.fasta")),
                ("result", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="mgw_api.result")),
                ("signature", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="mgw_api.signature")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                condition=Q(("fasta__isnull", False), ("job_type", "signature_pipeline"), ("state__in", ("queued", "waiting", "starting", "running", "combining_results", "saving_result"))),
                fields=("fasta", "job_type"),
                name="uniq_active_signature_pipeline_per_fasta",
            ),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                condition=Q(("job_type", "search"), ("signature__isnull", False), ("state__in", ("queued", "waiting", "starting", "running", "combining_results", "saving_result"))),
                fields=("signature", "job_type"),
                name="uniq_active_search_per_signature",
            ),
        ),
        migrations.AddConstraint(
            model_name="job",
            constraint=models.UniqueConstraint(
                condition=Q(("job_type__in", ("downloads", "index", "daily")), ("state__in", ("queued", "waiting", "starting", "running", "combining_results", "saving_result"))),
                fields=("job_type",),
                name="uniq_active_global_maintenance_jobs",
            ),
        ),
    ]
