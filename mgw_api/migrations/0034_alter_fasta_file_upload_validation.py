# Generated manually for upload validation hardening.

import mgw_api.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mgw_api", "0033_job"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fasta",
            name="file",
            field=models.FileField(
                upload_to=mgw_api.models.user_directory_path,
                validators=[
                    mgw_api.models.validate_fasta_extension,
                    mgw_api.models.validate_fasta_content,
                ],
            ),
        ),
    ]
