# mgw_api/admin.py

from django.contrib import admin

from .models import Fasta
from .models import Result
from .models import Settings
from .models import Signature

admin.site.register(Fasta)
admin.site.register(Signature)
admin.site.register(Settings)
admin.site.register(Result)
