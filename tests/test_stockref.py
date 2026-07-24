from ainews import db, stockref


def _conn():
    c = db.get_conn(":memory:")
    db.init_db(c)
    return c


def _fake_loader_factory(rows):
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return rows

    return loader, calls


# --- db.py 层：stock_ref 表 + find_stock ---

def test_bulk_upsert_stock_ref_and_count():
    c = _conn()
    assert db.stock_ref_count(c) == 0
    n = db.bulk_upsert_stock_ref(c, [("600036", "招商银行"), ("000001", "平安银行")])
    assert n == 2
    assert db.stock_ref_count(c) == 2
    # INSERT OR IGNORE：重复 code 不重复插入
    n2 = db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])
    assert n2 == 0
    assert db.stock_ref_count(c) == 2


def test_find_stock_by_code():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])
    code, name = db.find_stock(c, code="600036")
    assert (code, name) == ("600036", "招商银行")


def test_find_stock_by_name():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("000001", "平安银行")])
    code, name = db.find_stock(c, name="平安银行")
    assert (code, name) == ("000001", "平安银行")


def test_find_stock_normalizes_code_suffix():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])
    code, name = db.find_stock(c, code="600036.SH")
    assert (code, name) == ("600036", "招商银行")


def test_find_stock_unknown_code_returns_none_name():
    c = _conn()
    db.bulk_upsert_stock_ref(c, [("600036", "招商银行")])
    code, name = db.find_stock(c, code="999999")
    assert code == "999999"
    assert name is None


# --- stockref.py 层：ensure_loaded / resolve（永不真实调用 akshare） ---

def test_ensure_loaded_uses_loader_once():
    c = _conn()
    loader, calls = _fake_loader_factory([("600036", "招商银行"), ("000001", "平安银行")])
    count1 = stockref.ensure_loaded(c, loader=loader)
    count2 = stockref.ensure_loaded(c, loader=loader)
    assert calls["n"] == 1
    assert count1 == 2
    assert count2 == 2


def test_resolve_by_code_fills_name():
    c = _conn()
    loader, _ = _fake_loader_factory([("600036", "招商银行"), ("000001", "平安银行")])
    code, name = stockref.resolve(c, code="600036", loader=loader)
    assert (code, name) == ("600036", "招商银行")


def test_resolve_by_name_fills_code():
    c = _conn()
    loader, _ = _fake_loader_factory([("600036", "招商银行"), ("000001", "平安银行")])
    code, name = stockref.resolve(c, name="平安银行", loader=loader)
    assert (code, name) == ("000001", "平安银行")


def test_resolve_code_with_suffix():
    c = _conn()
    loader, _ = _fake_loader_factory([("600036", "招商银行"), ("000001", "平安银行")])
    code, name = stockref.resolve(c, code="600036.SH", loader=loader)
    assert (code, name) == ("600036", "招商银行")


def test_resolve_unknown_name_fallback():
    c = _conn()
    loader, _ = _fake_loader_factory([("600036", "招商银行"), ("000001", "平安银行")])
    code, name = stockref.resolve(c, name="某港股", loader=loader)
    assert code  # 非空
    assert name  # 非空
    assert code == name == "某港股"


def test_resolve_both_given_skips_loader():
    """两个字段都填了：不应触发 loader（保持轻量、不隐式联网）。"""
    c = _conn()
    loader, calls = _fake_loader_factory([("600036", "招商银行")])
    code, name = stockref.resolve(c, code="600036", name="招商银行", loader=loader)
    assert (code, name) == ("600036", "招商银行")
    assert calls["n"] == 0
