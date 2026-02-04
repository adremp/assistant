"""Redis connection factory."""

from redis.asyncio import Redis


async def create_redis(url: str) -> Redis:
    """Create and verify Redis connection."""
    redis = Redis.from_url(url)
    await redis.ping()
    return redis
