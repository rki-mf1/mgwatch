# Generated by Django 5.0.6 on 2024-08-09 09:23

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mgw_api', '0026_signature_processed'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='signature',
            name='processed',
        ),
        migrations.RemoveField(
            model_name='signature',
            name='result_pk',
        ),
        migrations.RemoveField(
            model_name='signature',
            name='status',
        ),
    ]
