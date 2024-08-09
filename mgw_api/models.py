# mgw_api/models.py

import datetime

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib import admin
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

import re
from datetime import datetime


def validate_fasta_content(file):
    # check if first two lines are in fasta format
    try:
        first_line = file.readline().decode("utf-8")
        second_line = file.readline().decode("utf-8")
        if not re.match(r">", first_line.strip()) or not re.match(r"^[ACGTUacgtu]+$", second_line.strip()):
                print(first_line)
                print(second_line)
                raise ValidationError("File does not start with '>' character, invalid FASTA format!")
    except Exception as e:
        raise ValidationError(f"Error reading file: {str(e)}")


def user_directory_path(instance, filename):
    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"user_{instance.user.id}/{filename}-{date}"


class Fasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=True, null=True)
    file = models.FileField(upload_to=user_directory_path, 
                            validators=[
                                FileExtensionValidator(["fa", "fasta", "fsa", "fna", "FASTA"]),
                                validate_fasta_content,])
    upload_date = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField()
    processed = models.BooleanField(default=False)
    status = models.CharField(max_length=255, default="Pending")
    result_pk = models.IntegerField(null=True, blank=True)
    
    def __str__(self):
        return self.name or self.file.name

    def delete(self, *args, **kwargs):
        self.file.delete()
        super().delete(*args, **kwargs)


class Signature(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    fasta = models.ForeignKey(Fasta, null=True, on_delete=models.SET_NULL)
    file = models.FileField(upload_to=user_directory_path)
    date = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField(default=0)
    submitted = models.BooleanField(default=False)
    settings_used = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=255, default="Pending")
    result_pk = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.file.delete()
        super().delete(*args, **kwargs)


class Settings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    kmer = models.JSONField(default=list, help_text="List of k-mers")
    database = models.JSONField(default=list, help_text="List of databases")
    containment = models.FloatField(default=0.10, help_text="Containment value (between 0 and 1)")

    def clean(self):
        if not self.kmer:
            raise ValidationError('At least one kmer must be selected.')
        if not self.database:
            raise ValidationError('At least one database must be selected.')
        if not (0 <= self.containment <= 1):
            raise ValidationError('Containment value must be between 0 and 1.')

    def to_dict(self):
        return {
            "kmer": self.kmer,
            "database": self.database,
            "containment": self.containment,
        }


class Result(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    signature = models.ForeignKey(Signature, on_delete=models.CASCADE)
    file = models.FileField(upload_to=user_directory_path)
    size = models.IntegerField(default=0)
    kmer = models.JSONField(default=list)
    database = models.JSONField(default=list)
    containment = models.FloatField(default=0.10)
    created_time = models.DateTimeField(auto_now_add=True)
    created_date = models.DateField(auto_now_add=True)
    is_watched = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.file.delete()
        super().delete(*args, **kwargs)


class DateField(models.DateTimeField):
    def pre_save(self, model_instance, add):
        value = super().pre_save(model_instance, add)
        if value:
            value = value.date()
            return datetime.combine(value, datetime.min.time())
        return value


class FilterSetting(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    result = models.ForeignKey(Result, on_delete=models.CASCADE)
    filters = models.JSONField(default=dict)  # {column_index: filter_value}
    range_filters = models.JSONField(default=dict)  # {column_index: [min_value, max_value]}
    sort_column = models.IntegerField(null=True, blank=True)
    sort_reverse = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.result.name} Filters"
