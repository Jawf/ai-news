from ainews import quotes


def _fake_fetcher_factory(price_map):
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        return dict(price_map)

    return fetcher, calls


def test_get_prices_uses_injected_fetcher():
    quotes.reset_cache()
    fetcher, calls = _fake_fetcher_factory({"600036": 35.2, "000001": 12.1})
    prices = quotes.get_prices(["600036", "000001"], fetcher=fetcher)
    assert prices == {"600036": 35.2, "000001": 12.1}
    assert calls["n"] == 1


def test_get_prices_missing_code_absent_from_result():
    quotes.reset_cache()
    fetcher, _ = _fake_fetcher_factory({"600036": 35.2})
    prices = quotes.get_prices(["600036", "999999"], fetcher=fetcher)
    assert prices == {"600036": 35.2}
    assert "999999" not in prices


def test_get_prices_caches_within_ttl():
    quotes.reset_cache()
    fetcher, calls = _fake_fetcher_factory({"600036": 35.2})
    quotes.get_prices(["600036"], fetcher=fetcher)
    quotes.get_prices(["600036"], fetcher=fetcher)
    assert calls["n"] == 1  # 第二次调用命中缓存，fetcher 不再被调用
