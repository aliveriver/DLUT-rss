import asyncio
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from astrbot.api import logger

from sources import SOURCES, SourceConfig

CHINA_TZ = timezone(timedelta(hours=8))
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DATE_PATTERN = re.compile(
    r"(?P<year>\d{4})\s*(?:年|[-/.])\s*(?P<month>\d{1,2})\s*(?:月|[-/.])\s*(?P<day>\d{1,2})\s*日?"
)


class Notice(TypedDict):
    id: str
    title: str
    link: str
    source: str
    source_key: str
    category: str
    date: str
    pub_date: str
    published_at: datetime


class DLUTRSSService:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def fetch_notices(self, source_keys: set[str] | None = None) -> list[Notice]:
        timeout_sec = self._cfg_int("request_timeout_seconds", 20)
        max_items = self._cfg_int("rss_max_items", 50)
        selected_sources = [
            source for source in SOURCES if source_keys is None or source["key"] in source_keys
        ]
        if source_keys is not None and not selected_sources:
            logger.warning(f"[DLUT RSS] 未找到匹配来源 source_keys={sorted(source_keys)}")

        async with httpx.AsyncClient(
            timeout=timeout_sec,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_source_notices(client, source) for source in selected_sources),
                return_exceptions=True,
            )

        notices: list[Notice] = []
        for source, result in zip(selected_sources, results):
            if isinstance(result, Exception):
                logger.warning(f"[DLUT RSS] 抓取来源失败 {source['key']} {source['url']}: {result}")
                continue
            notices.extend(result)

        deduped: dict[str, Notice] = {}
        for item in notices:
            deduped[item["link"]] = item

        ordered = sorted(
            deduped.values(),
            key=lambda item: (item["published_at"], item["source"]),
            reverse=True,
        )
        return ordered[:max_items]

    async def write_rss(self, notices: list[Notice]):
        now_str = datetime.now(CHINA_TZ).strftime("%a, %d %b %Y %H:%M:%S +0800")

        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = self._cfg_str("rss_title", "DLUT 多站点通知聚合")
        ET.SubElement(channel, "link").text = "https://jxyxbzzx.dlut.edu.cn/tzgg/kfqxq.htm"
        ET.SubElement(channel, "description").text = "大连理工大学开发区校区多来源通知聚合 RSS"
        ET.SubElement(channel, "lastBuildDate").text = now_str

        for notice in notices:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = f"[{notice['source']}] {notice['title']}"
            ET.SubElement(item, "link").text = notice["link"]
            ET.SubElement(item, "guid").text = notice["id"]
            ET.SubElement(item, "pubDate").text = notice["pub_date"]
            ET.SubElement(item, "description").text = (
                f"来源: {notice['source']} | 分类: {notice['category']} | 日期: {notice['date']}"
            )

        xml_data = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
        path = self.rss_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xml_data)

    def rss_file_path(self) -> Path:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base = get_astrbot_data_path() / "plugin_data" / "astrbot_plugin_dlut_rss"
        except Exception:
            base = Path("data") / "plugin_data" / "astrbot_plugin_dlut_rss"
        return base / "dlut_notice_rss.xml"

    async def _fetch_source_notices(
        self, client: httpx.AsyncClient, source: SourceConfig
    ) -> list[Notice]:
        page_urls = [source["url"], *source.get("extra_urls", [])]
        notices: list[Notice] = []
        seen_links: set[str] = set()

        for page_url in page_urls:
            response = await client.get(page_url, headers=self._request_headers(source, page_url))
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            tags = soup.select(source["selector"])
            if not tags:
                logger.warning(
                    f"[DLUT RSS] 选择器未命中 {source['key']} {page_url} selector={source['selector']}"
                )
                continue

            for tag in tags:
                if not isinstance(tag, Tag):
                    continue

                href = (tag.get("href") or "").strip()
                if not href:
                    continue

                title = source["parser"](tag).strip()
                if not title:
                    continue

                base_url = source.get("base_url") or page_url
                full_url = urljoin(base_url, href)
                if full_url in seen_links:
                    continue

                published_at = self._extract_published_at(tag)
                notices.append(
                    {
                        "id": self._make_notice_id(source["key"], full_url),
                        "title": title,
                        "link": full_url,
                        "source": source["name"],
                        "source_key": source["key"],
                        "category": source["category"],
                        "date": published_at.strftime("%Y-%m-%d"),
                        "pub_date": published_at.strftime("%a, %d %b %Y %H:%M:%S +0800"),
                        "published_at": published_at,
                    }
                )
                seen_links.add(full_url)

        if not notices:
            logger.warning(f"[DLUT RSS] 来源无有效条目 {source['key']} urls={page_urls}")
        return notices

    def _extract_published_at(self, tag: Tag) -> datetime:
        candidates = [
            tag.get_text(" ", strip=True),
            *self._iter_ancestor_texts(tag, depth=3),
            self._collect_sibling_text(tag),
        ]

        for text in candidates:
            extracted = self._parse_date(text)
            if extracted is not None:
                return extracted

        return datetime.now(CHINA_TZ)

    def _iter_ancestor_texts(self, tag: Tag, depth: int) -> Iterable[str]:
        current = tag.parent
        steps = 0
        while isinstance(current, Tag) and steps < depth:
            text = current.get_text(" ", strip=True)
            if text:
                yield text
            current = current.parent
            steps += 1

    def _collect_sibling_text(self, tag: Tag) -> str:
        texts: list[str] = []
        for sibling in list(tag.previous_siblings)[:2]:
            text = self._node_text(sibling)
            if text:
                texts.append(text)
        for sibling in list(tag.next_siblings)[:2]:
            text = self._node_text(sibling)
            if text:
                texts.append(text)
        return " ".join(texts)

    def _node_text(self, node: object) -> str:
        if isinstance(node, Tag):
            return node.get_text(" ", strip=True)
        return str(node).strip()

    def _parse_date(self, text: str) -> datetime | None:
        if not text:
            return None

        match = DATE_PATTERN.search(text)
        if not match:
            return None

        try:
            year = int(match.group("year"))
            month = int(match.group("month"))
            day = int(match.group("day"))
            return datetime(year, month, day, tzinfo=CHINA_TZ)
        except ValueError:
            return None

    def _make_notice_id(self, source_key: str, link: str) -> str:
        digest = sha1(f"{source_key}|{link}".encode("utf-8")).hexdigest()
        return f"{source_key}:{digest}"

    def _request_headers(self, source: SourceConfig, request_url: str | None = None) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        headers["Referer"] = source.get("base_url") or request_url or source["url"]
        return headers

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except Exception:
            return default

    def _cfg_str(self, key: str, default: str) -> str:
        value = self.config.get(key, default)
        return str(value) if value is not None else default



