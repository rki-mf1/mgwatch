import inspect
import io
import re

import pandas as pd
from django.conf import settings
from django.core.mail import send_mail
from django.core.management import call_command
from django.urls import reverse

from mgw.settings import LOGGER
from mgw.settings import MGW_URL
from mgw_api.models import Result


def search_watch(name, user_id, watch_pk):
    output = io.StringIO()
    call_command("create_search", user_id, name, watch_pk, stdout=output)
    match = re.search(r"RESULT_PK:\s*(\d+)", output.getvalue())
    result_pk = int(match.group(1)) if match else None
    return Result.objects.get(pk=result_pk, user_id=user_id)


def compare_results(result, new_result):
    df1 = pd.read_csv(result.file.path)
    df2 = pd.read_csv(new_result.file.path)
    return df1.equals(df2)


def send_watch_notification(user, result, new_result):
    absolute_url = reverse("mgw_api:result_table", kwargs={"pk": new_result.pk})
    result_page = f"{MGW_URL}{absolute_url}"
    LOGGER.info(f"Preparing to send email to {user} with new results at {result_page}")
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
