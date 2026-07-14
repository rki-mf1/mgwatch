import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0034_alter_fasta_file_upload_validation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserDeprovisionState",
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
                    "source",
                    models.CharField(
                        choices=[("ldap", "LDAP"), ("local", "Local")],
                        default="ldap",
                        max_length=16,
                    ),
                ),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_in_ldap_at", models.DateTimeField(blank=True, null=True)),
                (
                    "first_missing_from_ldap_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("deletion_due_at", models.DateTimeField(blank=True, null=True)),
                ("notification_sent_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=255)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deprovision_state",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
