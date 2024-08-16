# mgw_api/management/commands/create_watch.py

from django.core.management.base import BaseCommand
from django.core.management import call_command
from mgw_api.models import Fasta, Signature, Result, Settings
from django.conf import settings
from django.core.mail import send_mail

from datetime import datetime
from itertools import product
import subprocess
import os
import io
import re
import pandas as pd

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        results = Result.objects.filter(is_watched=True)
        for result in results:
            try:
                signature = Signature.objects.get(user_id=result.user.id, name=result.name)
                signature.submitted = True
                signature.save()
                new_result = self.search_watch(signature.name, signature.user.id, result.pk)
                is_equal = self.compare_results(result, new_result)
                if is_equal:
                    new_result.delete()
                    new_message = "without finding new Metagenomes"
                else:
                    self.send_notification(result.user, result, new_result)
                    new_message = "with new Metagenomes"
                self.stdout.write(self.style.SUCCESS(f"Successfully processed file '{result.name}' {new_message}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing file '{result.name}': {e}"))

    def search_watch(self, name, user_id, watch_pk):
        output = io.StringIO()
        call_command('create_search', user_id, name, watch_pk, stdout=output)
        match = re.search(r'RESULT_PK:\s*(\d+)', output.getvalue())
        result_pk = int(match.group(1)) if match else None
        new_result = Result.objects.get(pk=result_pk, user_id=user_id)
        return new_result
    
    def compare_results(self, result, new_result):
        df1 = pd.read_csv(result.file.path)
        df2 = pd.read_csv(new_result.file.path)
        is_equal = df1.equals(df2)
        #diff = df1.compare(df2)
        return is_equal

    def send_notification(self, user, result, new_result):
        self.stdout.write(self.style.SUCCESS(f"Writing Mail ..."))
        result_page = f"http://localhost:8080/mgw_api/result/{new_result.pk}/"
        subject = f"MetagenomeWatch: Found new Genomes for {new_result.name}!"
        message = f"""
        Dear {user.username},

        Your watch that was created on {result.date} has successfully found new results with your query!

        Query: {new_result.name}
        K-mer: {new_result.kmer}
        Database: {new_result.database}
        Containment: {new_result.containment}
        Link: {result_page}

        Thank you for using MetagenomeWatch!

        Best wishes,
        The MetagenomeWatch Team
        """
        from_email = settings.DEFAULT_FROM_EMAIL
        to_email = user.email
        self.stdout.write(self.style.SUCCESS(f"Send Mail ..."))
        send_mail(subject, message, from_email, [to_email], fail_silently=False,)
