"""进程内 TTL 缓存，按筛选参数组合缓存查询结果。"""
from typing import Callable

from cachetools import TTLCache


class QueryCache:
    def __init__(self, ttl: float, maxsize: int = 128):
        self._store: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def get_or_set(self, key: str, producer: Callable[[], object]) -> object:
        if key in self._store:
            return self._store[key]
        value = producer()
        self._store[key] = value
        return value
