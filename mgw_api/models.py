# mgw_api/models.py

import datetime

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib import admin
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

import re


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
    return f"user_{instance.user.id}/{filename}"


class Fasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to=user_directory_path, 
                            validators=[
                                FileExtensionValidator(["fa", "fasta", "fsa", "fna", "FASTA"]),
                                validate_fasta_content,])
    upload_date = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField()
    processed = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def delete(self):
        self.file.delete()
        super().delete()


class Signature(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    fasta = models.ForeignKey(Fasta, null=True, on_delete=models.SET_NULL)
    file = models.FileField(upload_to=user_directory_path)
    date = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField(default=0)
    submitted = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def delete(self):
        self.file.delete()
        super().delete()


class Settings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    kmer_21 = models.BooleanField(default=True, help_text="21 k-mer",)
    kmer_31 = models.BooleanField(default=False, help_text="31 k-mer")
    kmer_51 = models.BooleanField(default=False, help_text="51 k-mer")
    SRA_database = models.BooleanField(default=True, help_text="SRA database")
    
    def to_dict(self):
        return {
            "kmer_21": self.kmer_21,
            "kmer_31": self.kmer_31,
            "kmer_51": self.kmer_51,
            "SRA_database": self.SRA_database,
        }


class Result(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    signature = models.ForeignKey(Signature, on_delete=models.CASCADE)
    file = models.FileField(upload_to=user_directory_path)
    settings_used = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField(default=0)
    is_watched = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def delete(self):
        self.file.delete()
        super().delete()
