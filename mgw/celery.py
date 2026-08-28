import os

from celery import Celery

from mgw.redis_transport import register_redis_transport_aliases

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mgw.settings")

register_redis_transport_aliases()

app = Celery("mgw")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
