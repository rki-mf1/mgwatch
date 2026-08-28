from redis.maint_notifications import MaintNotificationsConfig


def disabled_maint_notifications_config():
    return MaintNotificationsConfig(enabled=False)
