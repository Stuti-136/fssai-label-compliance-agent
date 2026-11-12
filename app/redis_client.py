from __future__ import annotations
from functools import lru_cache
from .config import get_settings

_fake_server = None


@lru_cache
def _client(url: str):
    if url.startswith("fakeredis://"):  # tests / offline eval only
        import fakeredis
        global _fake_server
        if _fake_server is None:
            _fake_server = fakeredis.FakeServer()
        return fakeredis.FakeRedis(server=_fake_server, decode_responses=True)
    import redis
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=10, socket_connect_timeout=3,
                                health_check_interval=15)


def get_redis():
    url = get_settings().redis_url
    if not url:
        raise RuntimeError("REDIS_URL is not set")
    return _client(url)
