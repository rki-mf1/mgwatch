from celery.backends.redis import RedisBackend as CeleryRedisBackend

from mgw.redis_config import disabled_maint_notifications_config


class RedisBackend(CeleryRedisBackend):
    def _get_pool(self, **params):
        params.setdefault(
            "maint_notifications_config",
            disabled_maint_notifications_config(),
        )
        return super()._get_pool(**params)
