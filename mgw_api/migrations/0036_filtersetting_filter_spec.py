# Generated manually for saved metadata filter specs.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgw_api", "0035_userdeprovisionstate"),
    ]

    operations = [
        migrations.AddField(
            model_name="filtersetting",
            name="filter_spec",
            field=models.JSONField(default=dict),
        ),
    ]
