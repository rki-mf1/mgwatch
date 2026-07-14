from django.core.management.base import BaseCommand

from mgw_api.services.retention import run_retention_cleanup


class Command(BaseCommand):
    help = "Apply the configured retention cleanup policy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete expired data. Without this flag the command runs as a dry-run.",
        )

    def handle(self, *args, **kwargs):
        dry_run = not kwargs["apply"]
        summary = run_retention_cleanup(dry_run=dry_run)
        mode = "dry-run" if dry_run else "applied"
        self.stdout.write(f"Retention cleanup {mode}:")
        for key in sorted(summary):
            self.stdout.write(f"{key}: {summary[key]}")
