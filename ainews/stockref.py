"""A 股代码/名称全量映射：来源 akshare（免费），供自选股反查补全使用。"""
from ainews import db


def load_from_akshare() -> list[tuple[str, str]]:
    """拉取全量 A 股代码<->名称映射。akshare 各版本列名不一致，做兼容处理。"""
    import akshare  # 惰性导入：这是重依赖，保持模块导入本身轻量、测试快

    df = akshare.stock_info_a_code_name()
    if "code" in df.columns and "name" in df.columns:
        code_col, name_col = "code", "name"
    elif "A股代码" in df.columns and "A股简称" in df.columns:
        code_col, name_col = "A股代码", "A股简称"
    else:
        code_col, name_col = df.columns[0], df.columns[1]
    return list(zip(df[code_col].astype(str), df[name_col].astype(str)))


def ensure_loaded(conn, loader=load_from_akshare) -> int:
    """stock_ref 表为空时才触发 loader 加载，返回当前行数。"""
    count = db.stock_ref_count(conn)
    if count == 0:
        rows = loader()
        db.bulk_upsert_stock_ref(conn, rows)
        count = db.stock_ref_count(conn)
    return count


def resolve(conn, code: str | None = None, name: str | None = None,
            loader=load_from_akshare) -> tuple[str, str]:
    """反查补全：任填其一，另一个从全 A 股映射表补全。

    两个都填时直接透传，不触发加载（避免不必要的重依赖调用）。
    命中不到时兜底：确保 code/name 都非空（watchlist.code 非空约束）。
    """
    code = (code or "").strip() or None
    name = (name or "").strip() or None
    if code and name:
        return code, name

    ensure_loaded(conn, loader=loader)
    found_code, found_name = db.find_stock(conn, code=code, name=name)

    result_code = found_code or found_name
    result_name = found_name or found_code
    return result_code, result_name
