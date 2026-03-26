import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_dlut_rss", "GitHub Copilot", "抓取大工开发区校区通知并推送到订阅会话", "1.0.0")
class DLUTRSSPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config or {}
        self._poll_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def initialize(self):
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info("[DLUT RSS] 插件初始化完成，后台轮询任务已启动。")

    async def terminate(self):
        self._stop_event.set()
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[DLUT RSS] 插件已停止。")

    @filter.command_group("dlut")
    def dlut_group(self):
        pass

    @dlut_group.command("subscribe")
    async def subscribe(self, event: AstrMessageEvent):
        """订阅当前会话的新通知推送。"""
        umo = event.unified_msg_origin
        sessions = await self._get_subscribed_sessions()
        if umo not in sessions:
            sessions.append(umo)
            await self.put_kv_data("subscribed_sessions", sessions)
        yield event.plain_result("已订阅 DLUT 通知推送。")

    @dlut_group.command("unsubscribe")
    async def unsubscribe(self, event: AstrMessageEvent):
        """取消订阅当前会话的新通知推送。"""
        umo = event.unified_msg_origin
        sessions = await self._get_subscribed_sessions()
        if umo in sessions:
            sessions.remove(umo)
            await self.put_kv_data("subscribed_sessions", sessions)
            yield event.plain_result("已取消订阅 DLUT 通知推送。")
            return
        yield event.plain_result("当前会话尚未订阅。")

    @dlut_group.command("check")
    async def check_now(self, event: AstrMessageEvent):
        """立即检查一次通知并推送增量。"""
        pushed = await self._run_check(push=True)
        if pushed == 0:
            yield event.plain_result("检查完成，没有新通知。")
        else:
            yield event.plain_result(f"检查完成，已推送 {pushed} 条新通知。")

    @dlut_group.command("rss")
    async def show_rss_info(self, event: AstrMessageEvent):
        """查看 RSS 文件位置。"""
        path = self._rss_file_path()
        if not path.exists():
            await self._refresh_rss_only()
        yield event.plain_result(f"RSS 已生成: {path}")

    @dlut_group.command("latest")
    async def latest(self, event: AstrMessageEvent):
        """查看最新通知（默认 5 条）。"""
        notices = await self._fetch_notices()
        if not notices:
            yield event.plain_result("暂未抓取到通知，请稍后再试。")
            return
        lines = ["最新通知："]
        for item in notices[:5]:
            lines.append(f"- {item['date']} | {item['title']}")
            lines.append(item["link"])
        yield event.plain_result("\n".join(lines))

    async def _polling_loop(self):
        await asyncio.sleep(3)
        while not self._stop_event.is_set():
            try:
                await self._run_check(push=True)
            except Exception as exc:
                logger.error(f"[DLUT RSS] 轮询检查失败: {exc}")

            interval_minutes = self._cfg_int("poll_interval_minutes", 15)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_minutes * 60)
            except asyncio.TimeoutError:
                continue

    async def _run_check(self, push: bool) -> int:
        notices = await self._fetch_notices()
        if not notices:
            return 0

        await self._write_rss(notices)

        seen_ids = set(await self.get_kv_data("seen_notice_ids", []))
        current_ids = [item["id"] for item in notices]

        if not seen_ids:
            # 首次运行仅建立基线，避免一次性推送历史消息
            await self.put_kv_data("seen_notice_ids", current_ids)
            return 0

        new_items = [item for item in notices if item["id"] not in seen_ids]
        if not new_items:
            return 0

        new_items = list(reversed(new_items))
        if push:
            await self._push_new_items(new_items)

        merged = current_ids + [sid for sid in seen_ids if sid not in current_ids]
        await self.put_kv_data("seen_notice_ids", merged[:500])
        return len(new_items)

    async def _refresh_rss_only(self):
        notices = await self._fetch_notices()
        if notices:
            await self._write_rss(notices)

    async def _push_new_items(self, items: list[dict[str, str]]):
        sessions = await self._get_subscribed_sessions()
        if not sessions:
            return

        for item in items:
            text = f"[DLUT 新通知] {item['title']}\n{item['date']}\n{item['link']}"
            for umo in sessions:
                try:
                    chain = MessageChain().message(text)
                    await self.context.send_message(umo, chain)
                except Exception as exc:
                    logger.warning(f"[DLUT RSS] 向会话推送失败 {umo}: {exc}")

    async def _get_subscribed_sessions(self) -> list[str]:
        sessions = await self.get_kv_data("subscribed_sessions", [])
        if isinstance(sessions, list):
            return [str(s) for s in sessions]
        return []

    async def _fetch_notices(self) -> list[dict[str, str]]:
        page_url = self._cfg_str("source_url", "https://jxyxbzzx.dlut.edu.cn/tzgg/kfqxq.htm")
        base_url = self._cfg_str("base_url", "https://jxyxbzzx.dlut.edu.cn/")
        timeout_sec = self._cfg_int("request_timeout_seconds", 20)
        max_items = self._cfg_int("rss_max_items", 30)

        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            response = await client.get(page_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        id_pattern = re.compile(r"/(\d+)\.htm$")

        notices: list[dict[str, str]] = []
        seen_links: set[str] = set()

        # 优先按页面条目容器解析，避免把标题中的日期误当发布日期
        for row in soup.select("div.l_text-wrapper_3"):
            link = row.select_one("a[href*='/info/']")
            if not link:
                continue

            href = (link.get("href") or "").strip()
            title = link.get_text(" ", strip=True)
            if not href or not title:
                continue

            abs_link = urljoin(base_url, href)
            if abs_link in seen_links:
                continue

            date_text_raw = ""
            date_span = row.select_one("span.l_text_22")
            if date_span:
                date_text_raw = date_span.get_text(" ", strip=True)

            date_text = self._extract_date_iso(date_text_raw)
            if not date_text:
                # 兜底：在同一条目文本中取最后一个日期，通常是右侧发布日期
                date_text = self._extract_date_iso(row.get_text(" ", strip=True), pick_last=True)
            if not date_text:
                continue

            id_match = id_pattern.search(abs_link)
            notice_id = id_match.group(1) if id_match else abs_link

            notices.append(
                {
                    "id": notice_id,
                    "title": title,
                    "link": abs_link,
                    "date": date_text,
                    "pub_date": self._to_rfc2822(date_text),
                }
            )
            seen_links.add(abs_link)

        # 兜底：若页面结构变化导致条目容器失效，再回退到全页面链接扫描
        if not notices:
            for link in soup.select("a[href]"):
                href = (link.get("href") or "").strip()
                title = link.get_text(" ", strip=True)
                if not href or not title or "/info/" not in href:
                    continue

                abs_link = urljoin(base_url, href)
                if abs_link in seen_links:
                    continue

                context_text = " ".join(
                    t for t in [link.parent.get_text(" ", strip=True), self._collect_sibling_text(link)] if t
                )
                date_text = self._extract_date_iso(context_text, pick_last=True)
                if not date_text:
                    continue

                id_match = id_pattern.search(abs_link)
                notice_id = id_match.group(1) if id_match else abs_link

                notices.append(
                    {
                        "id": notice_id,
                        "title": title,
                        "link": abs_link,
                        "date": date_text,
                        "pub_date": self._to_rfc2822(date_text),
                    }
                )
                seen_links.add(abs_link)

        notices.sort(key=lambda x: x["date"], reverse=True)
        return notices[:max_items]

    def _extract_date_iso(self, text: str, pick_last: bool = False) -> str:
        if not text:
            return ""
        matches = list(re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text))
        if not matches:
            return ""
        m = matches[-1] if pick_last else matches[0]
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    def _collect_sibling_text(self, link) -> str:
        texts = []
        for node in link.next_siblings:
            txt = str(node).strip()
            if txt:
                texts.append(txt)
            if len(" ".join(texts)) > 60:
                break
        return " ".join(texts)

    def _to_rfc2822(self, date_str: str) -> str:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            tz = timezone(timedelta(hours=8))
            return dt.replace(tzinfo=tz).strftime("%a, %d %b %Y 00:00:00 +0800")
        except ValueError:
            return datetime.now(timezone(timedelta(hours=8))).strftime("%a, %d %b %Y %H:%M:%S +0800")

    async def _write_rss(self, notices: list[dict[str, str]]):
        now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%a, %d %b %Y %H:%M:%S +0800")

        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = self._cfg_str("rss_title", "DLUT 开发区校区通知")
        ET.SubElement(channel, "link").text = self._cfg_str("source_url", "https://jxyxbzzx.dlut.edu.cn/tzgg/kfqxq.htm")
        ET.SubElement(channel, "description").text = "大连理工大学教学运行保障中心开发区校区通知"
        ET.SubElement(channel, "lastBuildDate").text = now_str

        for n in notices:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = n["title"]
            ET.SubElement(item, "link").text = n["link"]
            ET.SubElement(item, "guid").text = n["id"]
            ET.SubElement(item, "pubDate").text = n["pub_date"]
            ET.SubElement(item, "description").text = f"发布日期: {n['date']}"

        xml_data = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
        path = self._rss_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xml_data)

    def _rss_file_path(self) -> Path:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            base = get_astrbot_data_path() / "plugin_data" / "astrbot_plugin_dlut_rss"
        except Exception:
            base = Path("data") / "plugin_data" / "astrbot_plugin_dlut_rss"
        return base / "dlut_notice_rss.xml"

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except Exception:
            return default

    def _cfg_str(self, key: str, default: str) -> str:
        value = self.config.get(key, default)
        return str(value) if value is not None else default
