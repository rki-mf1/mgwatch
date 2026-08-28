# Generated manually for pre-search advanced metadata filters.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgw_api", "0036_filtersetting_filter_spec"),
    ]

    operations = [
        migrations.AddField(
            model_name="fasta",
            name="initial_filter_spec",
            field=models.JSONField(default=dict),
        ),
    ]
