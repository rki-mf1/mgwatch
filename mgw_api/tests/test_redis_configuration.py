from unittest.mock import patch

from celery import Celery
from django.conf import settings
from django.test import SimpleTestCase
from kombu import Connection
from redis.maint_notifications import MaintNotificationsConfig

from mgw.redis_transport import register_redis_transport_aliases


class RedisMaintNotificationsConfigTests(SimpleTestCase):
    def test_django_cache_disables_redis_maintenance_notifications(self):
        config = settings.CACHES["default"]["OPTIONS"]["CONNECTION_POOL_KWARGS"][
            "maint_notifications_config"
        ]

        self.assertIsInstance(config, MaintNotificationsConfig)
        self.assertIs(config.enabled, False)

    def test_celery_result_backend_disables_redis_maintenance_notifications(self):
        app = Celery("test", backend=settings.CELERY_RESULT_BACKEND)

        pool = app.backend._get_pool(**app.backend.connparams)

        self.assertIsNone(pool.maint_notifications_enabled())

    def test_celery_broker_disables_redis_maintenance_notifications(self):
        register_redis_transport_aliases()
        with patch("redis.client.Redis.ping", return_value=True):
            connection = Connection(settings.CELERY_BROKER_URL)
            self.assertEqual(connection.hostname, "mgwatch-redis")
            channel = connection.transport.Channel(connection.transport)
            pool = channel._get_pool()

        self.assertIsNone(pool.maint_notifications_enabled())
        self.assertEqual(pool.connection_kwargs["host"], "mgwatch-redis")
