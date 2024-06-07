# mgw_api/apps.py

from django.apps import AppConfig


class MgwApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mgw_api'

    def ready(self):
        import mgw_api.signals
