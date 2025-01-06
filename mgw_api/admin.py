# mgw_api/admin.py

from django.contrib import admin

from .models import Fasta, Result, Settings, Signature

admin.site.register(Fasta)
admin.site.register(Signature)
admin.site.register(Settings)
admin.site.register(Result)
