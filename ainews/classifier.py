"""规则关键词分类：标题+正文命中关键词即归类，可传入自定义 rules 覆盖。"""

DEFAULT_RULES: dict[str, list[str]] = {
    "宏观政策": ["央行", "降准", "降息", "国务院", "财政部", "货币政策", "GDP", "CPI", "政策"],
    "A股": ["A股", "沪指", "深成指", "创业板", "上证", "科创板", "北向资金"],
    "港美股": ["港股", "恒生", "美股", "纳斯达克", "道琼斯", "标普", "美联储"],
    "外汇期货": ["人民币", "汇率", "外汇", "原油", "黄金", "期货", "美元"],
    "公司个股": ["公司", "财报", "业绩", "股份", "回购", "增持", "减持", "上市"],
}


def classify(title: str, content: str = "", rules: dict | None = None) -> str:
    rules = rules if rules is not None else DEFAULT_RULES
    text = f"{title} {content}"
    for category, keywords in rules.items():
        if any(kw in text for kw in keywords):
            return category
    return "其他"
