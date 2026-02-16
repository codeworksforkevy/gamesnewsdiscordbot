import time

_cache = {}

def cache_get(key):
    entry = _cache.get(key)
    if not entry:
        return None

    value, expires_at = entry

    if expires_at and time.time() > expires_at:
        del _cache[key]
        return None

    return value


def cache_set(key, value, ttl=None):
    expires_at = None

    if ttl:
        expires_at = time.time() + ttl

    _cache[key] = (value, expires_at)
