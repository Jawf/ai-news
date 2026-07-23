from ainews.classifier import classify


def test_classify_macro():
    assert classify("央行宣布降准0.5个百分点") == "宏观政策"


def test_classify_a_share():
    assert classify("A股三大指数集体上涨，沪指涨1.2%") == "A股"


def test_classify_forex():
    assert classify("在岸人民币兑美元汇率大幅波动") == "外汇期货"


def test_classify_default_other():
    assert classify("某公司发布不相关的公告内容") in ("公司个股", "其他")


def test_custom_rules_override():
    rules = {"自定义类": ["特定词"]}
    assert classify("含特定词的标题", rules=rules) == "自定义类"
    assert classify("不含关键词", rules=rules) == "其他"
