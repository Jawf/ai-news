from ainews.watch_match import annotate

PAYLOAD = {"top20": [
    {"title": "招商银行业绩超预期", "sentiment": "利好",
     "stocks": [{"name": "招商银行", "code": "600036"}]},
    {"title": "中芯产能受限", "sentiment": "利空",
     "stocks": [{"name": "中芯国际", "code": "688981"}]},
    {"title": "无关新闻", "sentiment": "中性", "stocks": []},
]}
WATCH = [{"code": "600036", "name": "招商银行", "aliases": ["招行"]}]


def test_annotate_marks_hits_and_related():
    out = annotate(PAYLOAD, WATCH)
    assert out["top20"][0]["watch_hits"] == [{"code": "600036", "name": "招商银行"}]
    assert out["top20"][1]["watch_hits"] == []
    related = out["watch_related"]
    assert len(related) == 1
    assert related[0]["code"] == "600036"
    assert related[0]["items"][0]["sentiment"] == "利好"


def test_annotate_matches_alias_in_title():
    payload = {"top20": [{"title": "招行获批新业务", "sentiment": "利好", "stocks": []}]}
    out = annotate(payload, WATCH)
    assert out["top20"][0]["watch_hits"][0]["code"] == "600036"


def test_annotate_empty_watch_noop():
    out = annotate(PAYLOAD, [])
    assert out["watch_related"] == []
