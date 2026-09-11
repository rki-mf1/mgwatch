from django.db import migrations


def rename_sra_database_values(apps, schema_editor):
    Settings = apps.get_model("mgw_api", "Settings")
    Result = apps.get_model("mgw_api", "Result")
    for model in (Settings, Result):
        for obj in model.objects.all().iterator():
            databases = getattr(obj, "database", None)
            if not isinstance(databases, list):
                continue
            renamed = [
                "sra_metagenomes" if database == "SRA" else database
                for database in databases
            ]
            if renamed != databases:
                obj.database = renamed
                obj.save(update_fields=["database"])


def restore_sra_database_values(apps, schema_editor):
    Settings = apps.get_model("mgw_api", "Settings")
    Result = apps.get_model("mgw_api", "Result")
    for model in (Settings, Result):
        for obj in model.objects.all().iterator():
            databases = getattr(obj, "database", None)
            if not isinstance(databases, list):
                continue
            renamed = [
                "SRA" if database == "sra_metagenomes" else database
                for database in databases
            ]
            if renamed != databases:
                obj.database = renamed
                obj.save(update_fields=["database"])


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0038_system_statistics"),
    ]

    operations = [
        migrations.RunPython(rename_sra_database_values, restore_sra_database_values),
    ]
