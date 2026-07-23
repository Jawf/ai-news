"""统一新闻条目模型。"""
import datetime
import hashlib
from dataclasses import dataclass


@dataclass
class NewsItem:
    source: str
    title: str
    content: str = ""
    url: str = ""
    external_id: str = ""
    category: str = "其他"
    published_at: datetime.datetime | None = None
    fetched_at: datetime.datetime | None = None

    @property
    def content_hash(self) -> str:
        basis = self.external_id or f"{self.title}|{self.published_at}"
        return hashlib.sha256(f"{self.source}|{basis}".encode("utf-8")).hexdigest()
