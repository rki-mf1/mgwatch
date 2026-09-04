import gzip
import re
from datetime import datetime
from functools import partial
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from mgw.settings import LOGGER

FASTA_EXTENSIONS = (".fa", ".fasta", ".fsa", ".fna")
FASTA_GZIP_EXTENSIONS = tuple(f"{extension}.gz" for extension in FASTA_EXTENSIONS)
FASTA_SEQUENCE_RE = re.compile(r"^[ACGTRYSWKMBDHVN.-]+$", flags=re.IGNORECASE)


def _filename(fieldfile):
    return Path(getattr(fieldfile, "name", "")).name.lower()


def validate_fasta_extension(fieldfile):
    filename = _filename(fieldfile)
    allowed_extensions = FASTA_EXTENSIONS + FASTA_GZIP_EXTENSIONS
    if not filename.endswith(allowed_extensions):
        raise ValidationError(
            "Unsupported file extension. Use FASTA files ending in .fa, .fasta, "
            ".fsa, .fna, or their .gz variants."
        )


def _reset_file(fieldfile):
    if hasattr(fieldfile, "seek"):
        fieldfile.seek(0)


def _iter_fasta_lines(fieldfile):
    if _filename(fieldfile).endswith(".gz"):
        with gzip.GzipFile(fileobj=fieldfile, mode="rb") as fasta_file:
            for line in fasta_file:
                yield line
    else:
        for line in fieldfile:
            yield line


def validate_fasta_content(fieldfile):
    upload_size = getattr(fieldfile, "size", None)
    if upload_size and upload_size > settings.MAX_FASTA_UPLOAD_SIZE:
        raise ValidationError("Uploaded FASTA file is larger than the allowed limit.")

    saw_header = False
    saw_sequence = False
    decompressed_bytes = 0
    try:
        _reset_file(fieldfile)
        for raw_line in _iter_fasta_lines(fieldfile):
            decompressed_bytes += len(raw_line)
            if decompressed_bytes > settings.MAX_FASTA_UPLOAD_SIZE:
                raise ValidationError(
                    "Uploaded FASTA content is larger than the allowed limit."
                )
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8").strip()
            else:
                line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                saw_header = True
                continue
            if not saw_header:
                LOGGER.warning("Invalid FASTA upload rejected: missing header marker.")
                raise ValidationError(
                    "File does not start with '>' character, invalid FASTA format."
                )
            if not FASTA_SEQUENCE_RE.match(line):
                LOGGER.warning(
                    "Invalid FASTA upload rejected: non-IUPAC sequence data."
                )
                raise ValidationError(
                    "Sequence contains non-IUPAC characters, invalid FASTA format."
                )
            saw_sequence = True
        if not saw_header:
            raise ValidationError(
                "File does not start with '>' character, invalid FASTA format."
            )
        if not saw_sequence:
            raise ValidationError("FASTA file does not contain sequence data.")
    except ValidationError:
        raise
    except (OSError, UnicodeDecodeError) as e:
        raise ValidationError(f"Error reading FASTA file: {str(e)}")
    finally:
        _reset_file(fieldfile)


def user_directory_path(instance, filename):
    date = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"user_{instance.user.id}/{date}/{filename}"


class Fasta(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, blank=True, null=True)
    file = models.FileField(
        upload_to=user_directory_path,
        validators=[
            validate_fasta_extension,
            validate_fasta_content,
        ],
    )
    upload_date = models.DateTimeField(auto_now_add=True)
    size = models.IntegerField()
    processed = models.BooleanField(default=False)
    status = models.CharField(max_length=255, default="Pending")
    result_pk = models.IntegerField(null=True, blank=True)
    initial_filter_spec = models.JSONField(default=dict)

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
    filter_spec = models.JSONField(default=dict)
    filters = models.JSONField(default=dict)  # Legacy {column_index: filter_value}
    range_filters = models.JSONField(
        default=dict
    )  # Legacy {column_index: [min_value, max_value]}
    sort_column = models.IntegerField(null=True, blank=True)
    sort_reverse = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - {self.result.name} Filters"


class UserDeprovisionState(models.Model):
    class Source(models.TextChoices):
        LDAP = "ldap", "LDAP"
        LOCAL = "local", "Local"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="deprovision_state"
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.LDAP
    )
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_seen_in_ldap_at = models.DateTimeField(null=True, blank=True)
    first_missing_from_ldap_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    deletion_due_at = models.DateTimeField(null=True, blank=True)
    notification_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username}:{self.source}"


class SystemStatistic(models.Model):
    class Metric(models.TextChoices):
        INDEX_SAMPLE_COUNT = "index_sample_count", "Index samples"
        METADATA_SAMPLE_COUNT = "metadata_sample_count", "Metadata samples"
        AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND = (
            "average_search_rate_sequences_per_second",
            "Average search rate",
        )
        METADATA_UPDATE_RUNTIME_SECONDS = (
            "metadata_update_runtime_seconds",
            "Metadata update runtime",
        )
        INDEX_UPDATE_RUNTIME_SECONDS = (
            "index_update_runtime_seconds",
            "Index update runtime",
        )
        DOWNLOAD_INDEX_RUNTIME_SECONDS = (
            "download_index_runtime_seconds",
            "Sample download/index runtime",
        )

    metric = models.CharField(max_length=64, choices=Metric.choices, unique=True)
    value = models.FloatField(default=0)
    observation_count = models.PositiveIntegerField(default=0)
    details = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["metric"]

    def __str__(self):
        return self.get_metric_display()


class SystemStatisticSnapshot(models.Model):
    metric = models.CharField(max_length=64, choices=SystemStatistic.Metric.choices)
    value = models.FloatField(default=0)
    observation_count = models.PositiveIntegerField(default=0)
    details = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField()

    class Meta:
        ordering = ["-recorded_at", "-pk"]
        indexes = [
            models.Index(
                fields=["metric", "-recorded_at"],
                name="mgw_api_sys_metric_2da4d7_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_metric_display()} at {self.recorded_at}"


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
