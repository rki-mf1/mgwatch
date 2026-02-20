# mgw_api/management/commands/create_watch.py

from django.core.management.base import BaseCommand

from mgw.settings import LOGGER
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.services.watch_service import compare_results
from mgw_api.services.watch_service import search_watch
from mgw_api.services.watch_service import send_watch_notification


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        results = Result.objects.filter(is_watched=True)
        LOGGER.info(f"Starting watches for a total of {len(results)} watched results.")
        for result in results:
            try:
                signature = Signature.objects.get(
                    user_id=result.user.id, name=result.name
                )
                signature.submitted = True
                signature.save()
                new_result = search_watch(signature.name, signature.user.id, result.pk)
                is_equal = compare_results(result, new_result)
                if is_equal:
                    new_result.delete()
                    new_message = "without finding new Metagenomes"
                else:
                    # Move the watch to the latest result, so that the next
                    # time we run the watch query we are comparing with the
                    # latest search results
                    result.is_watched = False
                    new_result.is_watched = True
                    result.save()
                    new_result.save()

                    send_watch_notification(result.user, result, new_result)
                    new_message = "with new Metagenomes"
                LOGGER.info(
                    f"Successfully processed file '{result.name}' {new_message}"
                )
            except Exception as e:
                LOGGER.error(f"Error processing file '{result.name}': {e}")
        LOGGER.info("Running watches finished")
