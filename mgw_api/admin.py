from django.contrib import admin

from .models import Fasta
from .models import Job
from .models import Result
from .models import Settings
from .models import Signature
from .models import SystemStatistic
from .models import SystemStatisticSnapshot

admin.site.register(Fasta)
admin.site.register(Signature)
admin.site.register(Settings)
admin.site.register(Result)
admin.site.register(Job)


@admin.register(SystemStatistic)
class SystemStatisticAdmin(admin.ModelAdmin):
    list_display = ("metric", "value", "observation_count", "recorded_at", "updated_at")
    readonly_fields = (
        "metric",
        "value",
        "observation_count",
        "details",
        "recorded_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(SystemStatisticSnapshot)
class SystemStatisticSnapshotAdmin(admin.ModelAdmin):
    list_display = ("metric", "value", "observation_count", "recorded_at")
    list_filter = ("metric",)
    readonly_fields = ("metric", "value", "observation_count", "details", "recorded_at")

    def has_add_permission(self, request):
        return False
