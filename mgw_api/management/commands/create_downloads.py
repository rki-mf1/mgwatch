from django.core.management.base import BaseCommand

from mgw_api.services.maintenance import run_downloads


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("-n", "--max-downloads", default=None, type=int)
        parser.add_argument("-p", "--max-simultaneous", default=100, type=int)
        parser.add_argument("-t", "--timeout", default=60, type=int)
        parser.add_argument("--ids", nargs="+")
        parser.add_argument("--retry-failed", action="store_true")

    def handle(self, *args, **kwargs):
        run_downloads(
            max_downloads=kwargs["max_downloads"],
            max_simultaneous=kwargs["max_simultaneous"],
            timeout=kwargs["timeout"],
            ids=kwargs["ids"],
            retry_failed=kwargs["retry_failed"],
        )
        self.stdout.write(self.style.SUCCESS("Signature downloads completed"))
