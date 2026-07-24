"""实时行情：akshare A股全市场快照，60s TTL 缓存，测试可注入 fetcher。"""
import time

_TTL_SECONDS = 60.0
_cache: dict[str, float] = {}
_cache_at: float | None = None


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


def reset_cache() -> None:
    """清空价格缓存（测试隔离 / 手动强制刷新用）。"""
    global _cache, _cache_at
    _cache = {}
    _cache_at = None


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
