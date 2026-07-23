from ainews.cache import QueryCache


def test_cache_hits_within_ttl():
    calls = {"n": 0}
    def producer():
        calls["n"] += 1
        return calls["n"]
    cache = QueryCache(ttl=100)
    assert cache.get_or_set("k", producer) == 1
    assert cache.get_or_set("k", producer) == 1  # 命中缓存，producer 不再调用
    assert calls["n"] == 1


def test_cache_distinct_keys():
    cache = QueryCache(ttl=100)
    assert cache.get_or_set("a", lambda: "A") == "A"
    assert cache.get_or_set("b", lambda: "B") == "B"
