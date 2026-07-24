"""实时行情：akshare A股全市场快照，60s TTL 缓存，测试可注入 fetcher。"""
import time

_TTL_SECONDS = 60.0
_cache: dict[str, float] = {}
_cache_at: float | None = None
_quotes_cache: dict[str, dict] = {}
_quotes_cache_at: float | None = None


def _akshare_spot() -> dict[str, float]:
    """全市场快照：code -> 最新价。akshare 各版本列名不一致，做兼容处理。"""
    import akshare  # 惰性导入：重依赖，保持模块导入本身轻量、测试快

    df = akshare.stock_zh_a_spot_em()
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    price_col = "最新价" if "最新价" in df.columns else df.columns[1]
    result: dict[str, float] = {}
    for code, price in zip(df[code_col].astype(str), df[price_col]):
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p != p or p == 0:  # NaN（自比较不等）或 0 视为无效价格，跳过
            continue
        result[code] = p
    return result


def _akshare_quotes() -> dict[str, dict]:
    """全市场快照：code -> {price, high, low, prev_close}，同一 spot_em 帧派生。

    涨跌停约束 / 止盈止损触线需要最高/最低/昨收，get_prices 的纯价格快照不够用。
    """
    import akshare  # 惰性导入：重依赖，保持模块导入本身轻量、测试快

    df = akshare.stock_zh_a_spot_em()
    code_col = "代码" if "代码" in df.columns else df.columns[0]
    price_col = "最新价" if "最新价" in df.columns else df.columns[1]
    high_col = "最高" if "最高" in df.columns else None
    low_col = "最低" if "最低" in df.columns else None
    prev_col = "昨收" if "昨收" in df.columns else None

    def _num(row, col, default):
        if col is None:
            return default
        try:
            v = float(row[col])
        except (TypeError, ValueError):
            return default
        return default if v != v else v  # NaN 回退到 default（自比较不等）

    result: dict[str, dict] = {}
    for _, row in df.iterrows():
        code = str(row[code_col])
        try:
            price = float(row[price_col])
        except (TypeError, ValueError):
            continue
        if price != price or price == 0:
            continue
        result[code] = {
            "price": price,
            "high": _num(row, high_col, price),
            "low": _num(row, low_col, price),
            "prev_close": _num(row, prev_col, price),
        }
    return result


def reset_cache() -> None:
    """清空价格缓存（测试隔离 / 手动强制刷新用）。"""
    global _cache, _cache_at, _quotes_cache, _quotes_cache_at
    _cache = {}
    _cache_at = None
    _quotes_cache = {}
    _quotes_cache_at = None


def get_prices(codes: list[str], fetcher=None) -> dict[str, float]:
    """返回 codes 中可解析到价格的 code -> 最新价（缺失的 code 直接不在结果中）。

    内部维护一份全市场快照缓存（TTL 60s），同一周期内多次调用不重复触发 fetcher。
    """
    global _cache, _cache_at
    fetcher = fetcher or _akshare_spot
    now = time.monotonic()
    if _cache_at is None or (now - _cache_at) > _TTL_SECONDS:
        _cache = fetcher()
        _cache_at = now
    return {c: _cache[c] for c in codes if c in _cache}


def get_quotes(codes: list[str], fetcher=None) -> dict[str, dict]:
    """返回 codes 中可解析到行情的 code -> {price, high, low, prev_close}。

    独立于 get_prices 的缓存（fetcher 返回结构不同：整市场 dict[code, dict] 而非
    dict[code, float]），TTL 60s，同一周期内多次调用不重复触发 fetcher。
    """
    global _quotes_cache, _quotes_cache_at
    fetcher = fetcher or _akshare_quotes
    now = time.monotonic()
    if _quotes_cache_at is None or (now - _quotes_cache_at) > _TTL_SECONDS:
        _quotes_cache = fetcher()
        _quotes_cache_at = now
    return {c: _quotes_cache[c] for c in codes if c in _quotes_cache}
