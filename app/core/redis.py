from collections.abc import Generator

import redis

from app.core.config import get_settings


def create_redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Generator[redis.Redis, None, None]:
    client = create_redis_client()
    try:
        yield client
    finally:
        client.close()


class TokenDenylist:
    prefix = "denylist"

    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        self.client.setex(f"{self.prefix}:{jti}", ttl_seconds, "1")

    def is_revoked(self, jti: str) -> bool:
        return self.client.exists(f"{self.prefix}:{jti}") == 1


class RateLimiter:
    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        redis_key = f"ratelimit:{key}"
        current = self.client.incr(redis_key)
        if current == 1:
            self.client.expire(redis_key, window_seconds)
        return current <= limit
