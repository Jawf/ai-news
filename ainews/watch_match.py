"""自选股与洞察的文本匹配：命中 name/code/alias 即挂 watch tag。"""
import copy


def _hit(entry_stocks: list[dict], title: str, w: dict) -> bool:
    needles = [w["name"], w["code"], *w.get("aliases", [])]
    for s in entry_stocks:
        if s.get("code") == w["code"] or s.get("name") == w["name"]:
            return True
    return any(n and n in title for n in needles)


def annotate(payload: dict, watch: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    related: dict[str, dict] = {}
    for entry in out.get("top20", []):
        hits = []
        for w in watch:
            if _hit(entry.get("stocks", []), entry.get("title", ""), w):
                hits.append({"code": w["code"], "name": w["name"]})
                rel = related.setdefault(w["code"], {"code": w["code"], "name": w["name"], "items": []})
                rel["items"].append({"title": entry.get("title", ""),
                                     "sentiment": entry.get("sentiment", "中性")})
        entry["watch_hits"] = hits
    out["watch_related"] = list(related.values())
    return out
