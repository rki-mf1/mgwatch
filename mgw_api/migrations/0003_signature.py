# Generated by Django 5.0.4 on 2024-05-31 18:42

import django.db.models.deletion
import mgw_api.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mgw_api', '0002_fasta_processed'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Signature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('file', models.FileField(upload_to=mgw_api.models.user_directory_path)),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('size', models.IntegerField()),
                ('fasta', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='mgw_api.fasta')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
