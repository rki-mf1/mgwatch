from contextlib import contextmanager
from threading import Lock

from django.conf import settings
from django.core.cache import caches

from .services.exceptions import LockTimeoutError

_LOCAL_LOCKS = {}


def _get_local_lock(name):
    if name not in _LOCAL_LOCKS:
        _LOCAL_LOCKS[name] = Lock()
    return _LOCAL_LOCKS[name]


@contextmanager
def acquire_lock(name, *, timeout=None, blocking_timeout=None):
    timeout = timeout or settings.CELERY_LOCK_TIMEOUT
    blocking_timeout = blocking_timeout or settings.CELERY_LOCK_BLOCKING_TIMEOUT
    cache = caches["default"]
    if hasattr(cache, "lock"):
        lock = cache.lock(name, timeout=timeout, blocking_timeout=blocking_timeout)
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise LockTimeoutError(f"Could not acquire lock '{name}'.")
        try:
            yield
        finally:
            lock.release()
        return

    lock = _get_local_lock(name)
    acquired = lock.acquire(timeout=blocking_timeout)
    if not acquired:
        raise LockTimeoutError(f"Could not acquire local lock '{name}'.")
    try:
        yield
    finally:
        lock.release()
