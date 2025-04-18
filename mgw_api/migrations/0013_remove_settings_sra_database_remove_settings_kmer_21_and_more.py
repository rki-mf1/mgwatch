# Generated by Django 5.0.6 on 2024-07-16 10:32

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mgw_api', '0012_delete_uploadedfile'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='settings',
            name='SRA_database',
        ),
        migrations.RemoveField(
            model_name='settings',
            name='kmer_21',
        ),
        migrations.RemoveField(
            model_name='settings',
            name='kmer_31',
        ),
        migrations.RemoveField(
            model_name='settings',
            name='kmer_51',
        ),
        migrations.AddField(
            model_name='settings',
            name='containment',
            field=models.FloatField(default=0.1, help_text='Containment value (between 0 and 1)'),
        ),
        migrations.AddField(
            model_name='settings',
            name='database',
            field=models.JSONField(default=list, help_text='List of databases'),
        ),
        migrations.AddField(
            model_name='settings',
            name='kmer',
            field=models.JSONField(default=list, help_text='List of k-mers'),
        ),
    ]
