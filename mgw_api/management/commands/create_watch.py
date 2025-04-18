# mgw_api/management/commands/create_watch.py

import inspect
import io
import re

import pandas as pd
from django.conf import settings
from django.core.mail import send_mail
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.urls import reverse

from mgw.settings import LOGGER
from mgw.settings import MGW_URL
from mgw_api.models import Result
from mgw_api.models import Signature


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
                new_result = self.search_watch(
                    signature.name, signature.user.id, result.pk
                )
                is_equal = self.compare_results(result, new_result)
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

                    self.send_notification(result.user, result, new_result)
                    new_message = "with new Metagenomes"
                LOGGER.info(
                    f"Successfully processed file '{result.name}' {new_message}"
                )
            except Exception as e:
                LOGGER.error(f"Error processing file '{result.name}': {e}")
        LOGGER.info("Running watches finished")

    def search_watch(self, name, user_id, watch_pk):
        output = io.StringIO()
        call_command("create_search", user_id, name, watch_pk, stdout=output)
        match = re.search(r"RESULT_PK:\s*(\d+)", output.getvalue())
        result_pk = int(match.group(1)) if match else None
        new_result = Result.objects.get(pk=result_pk, user_id=user_id)
        return new_result

    def compare_results(self, result, new_result):
        df1 = pd.read_csv(result.file.path)
        df2 = pd.read_csv(new_result.file.path)
        is_equal = df1.equals(df2)
        return is_equal

    def send_notification(self, user, result, new_result):
        absolute_url = reverse("mgw_api:result_table", kwargs={"pk": new_result.pk})
        result_page = f"{MGW_URL}{absolute_url}"
        LOGGER.info(
            f"Preparing to send email to {user} with new results at {result_page} ..."
        )
        subject = f"MetagenomeWatch: Found new results for watch {new_result.name}"
        message = inspect.cleandoc(f"""
        Dear MetagenomeWatch user {user.username},

        New results have been found for your watch named "{result.name}".

        You can view the results here: {result_page}

        Watch details:
            Name: {new_result.name}
            K-mer: {new_result.kmer}
            Database: {new_result.database}
            Containment threshold: {new_result.containment}

        Best wishes,
        The MetagenomeWatch Team
        """)
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [user.email]
        send_mail(
            subject,
            message,
            from_email,
            recipient_list,
            fail_silently=False,
        )
        LOGGER.info("Email sent successfully")
