# igw/app/utils/redis_cache.py
from __future__ import annotations

import redis  # pip install redis
from igw.app.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """
    Lazy, module-level Redis client.
    Uses decode_responses=True so we work with str/JSON easily.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client
