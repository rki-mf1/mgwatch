from kombu import transport as kombu_transport
from kombu.transport import redis as kombu_redis

from mgw.redis_config import disabled_maint_notifications_config


class Channel(kombu_redis.Channel):
    def _get_pool(self, asynchronous=False):
        params = self._connparams(asynchronous=asynchronous)
        params.setdefault(
            "maint_notifications_config",
            disabled_maint_notifications_config(),
        )
        self.keyprefix_fanout = self.keyprefix_fanout.format(db=params["db"])
        return kombu_redis.redis.ConnectionPool(**params)


class Transport(kombu_redis.Transport):
    Channel = Channel


def register_redis_transport_aliases():
    kombu_transport.TRANSPORT_ALIASES["redis"] = "mgw.redis_transport:Transport"
    kombu_transport.TRANSPORT_ALIASES["rediss"] = "mgw.redis_transport:Transport"
    kombu_transport._transport_cache.pop("redis", None)
    kombu_transport._transport_cache.pop("rediss", None)
