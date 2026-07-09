import gzip
import io
import re
from datetime import datetime
from functools import partial
from pathlib import Path

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q

from mgw.settings import LOGGER


def validate_fasta_content(fieldfile):
    # check if first two lines are in fasta format
    try:
        if Path(fieldfile.path).suffix == ".gz":
            # Input file is gzipped. Might be in memory so we need to read
            # the actual contents and decompress them
            fasta = gzip.decompress(fieldfile.read()).decode("utf-8")
            fasta_io = io.StringIO(fasta)

            header = fasta_io.readline().strip()
            seq = fasta_io.readline().strip()
        else:
            header = fieldfile.readline().decode("utf-8").strip()
            seq = fieldfile.readline().decode("utf-8").strip()

        # Do actual validation. This is not exhaustive, it's only checking the
        # first couple of lines as a sanity check.
        if not re.match(r"^>", header):
            LOGGER.error(f"header: {header}")
            LOGGER.error(f"seq: {seq}")
            raise ValidationError(
                "File does not start with '>' character, invalid FASTA format."
            )
        elif not re.match(r"^[ACGTRYSWKMBDHVN.-]+$", seq, flags=re.IGNORECASE):
            LOGGER.error(f"header: {header}")
            LOGGER.error(f"seq: {seq}")
            raise ValidationError(
                "Sequence contains non-IUPAC characters, invalid FASTA format."
            )
    except Exception as e:
        raise ValidationError(f"Error reading file: {str(e)}")


def user_directory_path(instance, filename):
    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"user_{instance.user.id}/{date}/{filename}"


class Fasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=True, null=True)
    file = models.FileField(
        upload_to=user_directory_path,
        validators=[
            FileExtensionValidator(["fa", "fasta", "fsa", "fna", "gz"]),
            validate_fasta_content,
        ],
    )
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
    time = models.TimeField(auto_now_add=True)
    size = models.IntegerField(default=0)
    submitted = models.BooleanField(default=False)
    settings_used = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        self.file.delete()
        super().delete(*args, **kwargs)


class Settings(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    kmer = models.JSONField(default=partial(list, [21]), help_text="List of k-mers")
    database = models.JSONField(
        default=partial(list, ["SRA"]), help_text="List of databases"
    )
    containment = models.FloatField(
        default=0.10, help_text="Containment value (between 0 and 1)"
    )

    def clean(self):
        if not self.kmer:
            raise ValidationError("At least one kmer must be selected.")
        if not self.database:
            raise ValidationError("At least one database must be selected.")
        if not (0 <= self.containment <= 1):
            raise ValidationError("Containment value must be between 0 and 1.")

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
    file = models.FileField(upload_to=user_directory_path, blank=True)
    num_results = models.PositiveIntegerField(default=0)
    kmer = models.JSONField(default=list)
    database = models.JSONField(default=list)
    containment = models.FloatField(default=0.10)
    date = models.DateField(auto_now_add=True)
    time = models.DateTimeField(auto_now_add=True)
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
    range_filters = models.JSONField(
        default=dict
    )  # {column_index: [min_value, max_value]}
    sort_column = models.IntegerField(null=True, blank=True)
    sort_reverse = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.result.name} Filters"


class Job(models.Model):
    class JobType(models.TextChoices):
        SIGNATURE_PIPELINE = "signature_pipeline", "Signature pipeline"
        SEARCH = "search", "Search"
        CREATE_SIGNATURE = "create_signature", "Create signature"
        METADATA = "metadata", "Metadata"
        DOWNLOADS = "downloads", "Downloads"
        INDEX = "index", "Index"
        WATCH = "watch", "Watch"
        DAILY = "daily", "Daily"

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        WAITING = "waiting", "Waiting"
        STARTING = "starting", "Starting"
        RUNNING = "running", "Running"
        COMBINING_RESULTS = "combining_results", "Combining results"
        SAVING_RESULT = "saving_result", "Saving result"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    ACTIVE_STATES = (
        State.QUEUED,
        State.WAITING,
        State.STARTING,
        State.RUNNING,
        State.COMBINING_RESULTS,
        State.SAVING_RESULT,
    )

    job_type = models.CharField(max_length=64, choices=JobType.choices)
    state = models.CharField(max_length=32, choices=State.choices, default=State.QUEUED)
    status_message = models.CharField(max_length=255, default="Queued")
    celery_task_id = models.CharField(max_length=255, blank=True)
    queue = models.CharField(max_length=64, blank=True)
    lock_name = models.CharField(max_length=128, blank=True)
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    failure_details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    fasta = models.ForeignKey(Fasta, null=True, blank=True, on_delete=models.CASCADE)
    signature = models.ForeignKey(
        Signature, null=True, blank=True, on_delete=models.CASCADE
    )
    result = models.ForeignKey(Result, null=True, blank=True, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fasta", "job_type"],
                condition=Q(
                    fasta__isnull=False,
                    state__in=[
                        "queued",
                        "waiting",
                        "starting",
                        "running",
                        "combining_results",
                        "saving_result",
                    ],
                    job_type="signature_pipeline",
                ),
                name="uniq_active_signature_pipeline_per_fasta",
            ),
            models.UniqueConstraint(
                fields=["signature", "job_type"],
                condition=Q(
                    signature__isnull=False,
                    state__in=[
                        "queued",
                        "waiting",
                        "starting",
                        "running",
                        "combining_results",
                        "saving_result",
                    ],
                    job_type="search",
                ),
                name="uniq_active_search_per_signature",
            ),
            models.UniqueConstraint(
                fields=["job_type"],
                condition=Q(
                    state__in=[
                        "queued",
                        "waiting",
                        "starting",
                        "running",
                        "combining_results",
                        "saving_result",
                    ],
                    job_type__in=["downloads", "index", "daily"],
                ),
                name="uniq_active_global_maintenance_jobs",
            ),
        ]

    def __str__(self):
        return f"{self.job_type}:{self.pk}:{self.state}"

    @property
    def progress_percent(self):
        if not self.progress_total:
            return 0
        return min(100, int((self.progress_current / self.progress_total) * 100))
