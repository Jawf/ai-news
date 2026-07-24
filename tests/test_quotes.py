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


# --- get_quotes：涨跌停约束 / 止盈止损触线所需的 high/low/prev_close ---

def _fake_quotes_fetcher_factory(quote_map):
    calls = {"n": 0}

    def fetcher():
        calls["n"] += 1
        return dict(quote_map)

    return fetcher, calls


def test_get_quotes_uses_injected_fetcher():
    quotes.reset_cache()
    fetcher, calls = _fake_quotes_fetcher_factory({
        "600036": {"price": 35.2, "high": 35.5, "low": 34.8, "prev_close": 35.0},
    })
    result = quotes.get_quotes(["600036"], fetcher=fetcher)
    assert result == {"600036": {"price": 35.2, "high": 35.5, "low": 34.8, "prev_close": 35.0}}
    assert calls["n"] == 1


def test_get_quotes_missing_code_absent_from_result():
    quotes.reset_cache()
    fetcher, _ = _fake_quotes_fetcher_factory({
        "600036": {"price": 35.2, "high": 35.5, "low": 34.8, "prev_close": 35.0},
    })
    result = quotes.get_quotes(["600036", "999999"], fetcher=fetcher)
    assert "999999" not in result


def test_get_quotes_caches_within_ttl():
    quotes.reset_cache()
    fetcher, calls = _fake_quotes_fetcher_factory({
        "600036": {"price": 35.2, "high": 35.5, "low": 34.8, "prev_close": 35.0},
    })
    quotes.get_quotes(["600036"], fetcher=fetcher)
    quotes.get_quotes(["600036"], fetcher=fetcher)
    assert calls["n"] == 1


def test_get_quotes_cache_independent_from_get_prices_cache():
    quotes.reset_cache()
    price_fetcher, price_calls = _fake_fetcher_factory({"600036": 35.2})
    quotes_fetcher, quotes_calls = _fake_quotes_fetcher_factory({
        "600036": {"price": 35.2, "high": 35.5, "low": 34.8, "prev_close": 35.0},
    })
    quotes.get_prices(["600036"], fetcher=price_fetcher)
    quotes.get_quotes(["600036"], fetcher=quotes_fetcher)
    assert price_calls["n"] == 1
    assert quotes_calls["n"] == 1
