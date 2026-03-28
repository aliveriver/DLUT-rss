import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


def _load_local_module(module_name: str):
    if module_name in sys.modules:
        return sys.modules[module_name]

    module_path = Path(__file__).resolve().with_name(f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(f"Cannot load local plugin module: {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


for _module_name in (
    "parsers",
    "sources",
    "rss_service",
    "command_utils",
    "subscription_store",
):
    _load_local_module(_module_name)

from command_utils import extract_command_args, format_latest_lines
from rss_service import DLUTRSSService, Notice
from sources import SourceConfig, format_source_lines, resolve_source
from subscription_store import SubscriptionStore


@register("astrbot_plugin_dlut_rss", "aliveriver", "抓取 DLUT 多站点通知并推送到订阅会话", "1.2.2")
class DLUTRSSPlugin(Star):
    def __init__(self, context: Context, config: dict[str, Any] | None = None):
        super().__init__(context)
        self.config = config or {}
        self._poll_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._rss_service = DLUTRSSService(self.config)
        self._subscription_store = SubscriptionStore(self.get_kv_data, self.put_kv_data)

    async def initialize(self):
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info("[DLUT RSS] 插件初始化完成，多源轮询任务已启动。")

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

    @dlut_group.command("help")
    async def help(self, event: AstrMessageEvent):
        """查看插件使用说明。"""
        yield event.plain_result(self._help_text())

    @dlut_group.command("sources")
    async def sources(self, event: AstrMessageEvent):
        """查看当前支持的来源及订阅状态。"""
        global_enabled = event.unified_msg_origin in await self._subscription_store.get_global_sessions()
        source_subscriptions = await self._subscription_store.get_source_subscriptions()
        subscribed_keys = set(source_subscriptions.get(event.unified_msg_origin, []))

        lines = ["可用来源:"]
        lines.extend(format_source_lines(subscribed_keys))
        if global_enabled:
            lines.append("")
            lines.append("当前会话已开启全局订阅，所有来源的新通知都会推送。")
        elif subscribed_keys:
            lines.append("")
            lines.append("当前会话仅会收到标记为“已单独订阅”的来源推送。")
        else:
            lines.append("")
            lines.append("当前会话尚未订阅任何来源。")
        yield event.plain_result("\n".join(lines))

    @dlut_group.command("subscribe")
    async def subscribe(self, event: AstrMessageEvent):
        """订阅当前会话的全部来源新通知推送。"""
        umo = event.unified_msg_origin
        sessions = await self._subscription_store.get_global_sessions()
        if umo not in sessions:
            sessions.append(umo)
            await self._subscription_store.save_global_sessions(sessions)
        yield event.plain_result("已订阅全部 DLUT 来源通知推送。")

    @dlut_group.command("unsubscribe")
    async def unsubscribe(self, event: AstrMessageEvent):
        """取消当前会话的全部来源通知推送。"""
        umo = event.unified_msg_origin
        sessions = await self._subscription_store.get_global_sessions()
        if umo in sessions:
            sessions.remove(umo)
            await self._subscription_store.save_global_sessions(sessions)
            yield event.plain_result("已取消全部 DLUT 来源通知推送。")
            return
        yield event.plain_result("当前会话尚未开启全局订阅。")

    @dlut_group.command("subscribe_source")
    async def subscribe_source(self, event: AstrMessageEvent):
        """按来源订阅当前会话的新通知推送。"""
        source, error = self._resolve_source_from_event(event, "subscribe_source")
        if source is None:
            yield event.plain_result(error)
            return

        subscriptions = await self._subscription_store.get_source_subscriptions()
        umo = event.unified_msg_origin
        subscribed_keys = subscriptions.setdefault(umo, [])
        if source["key"] not in subscribed_keys:
            subscribed_keys.append(source["key"])
            subscribed_keys.sort()
            await self._subscription_store.save_source_subscriptions(subscriptions)
        yield event.plain_result(f"已订阅来源: {source['name']} ({source['key']})")

    @dlut_group.command("unsubscribe_source")
    async def unsubscribe_source(self, event: AstrMessageEvent):
        """按来源取消当前会话的新通知推送。"""
        source, error = self._resolve_source_from_event(event, "unsubscribe_source")
        if source is None:
            yield event.plain_result(error)
            return

        subscriptions = await self._subscription_store.get_source_subscriptions()
        umo = event.unified_msg_origin
        subscribed_keys = subscriptions.get(umo, [])
        if source["key"] not in subscribed_keys:
            yield event.plain_result(f"当前会话尚未订阅来源: {source['name']}")
            return

        subscribed_keys.remove(source["key"])
        if subscribed_keys:
            subscriptions[umo] = subscribed_keys
        else:
            subscriptions.pop(umo, None)
        await self._subscription_store.save_source_subscriptions(subscriptions)
        yield event.plain_result(f"已取消订阅来源: {source['name']} ({source['key']})")

    @dlut_group.command("check")
    async def check_now(self, event: AstrMessageEvent):
        """立即检查一次通知并推送增量。"""
        pushed = await self._run_check(push=True)
        if pushed == 0:
            yield event.plain_result("检查完成，没有新的通知。")
        else:
            yield event.plain_result(f"检查完成，已推送 {pushed} 条新通知。")

    @dlut_group.command("rss")
    async def show_rss_info(self, event: AstrMessageEvent):
        """查看聚合 RSS 文件位置。"""
        path = self._rss_service.rss_file_path()
        if not path.exists():
            await self._refresh_rss_only()
        yield event.plain_result(f"聚合 RSS 已生成: {path}")

    @dlut_group.command("latest")
    async def latest(self, event: AstrMessageEvent):
        """查看全部来源的最新通知，默认显示 5 条。"""
        notices = await self._rss_service.fetch_notices()
        if not notices:
            yield event.plain_result("暂未抓取到通知，请稍后再试。")
            return
        yield event.plain_result(format_latest_lines("最新通知:", notices[:5]))

    @dlut_group.command("latest_source")
    async def latest_source(self, event: AstrMessageEvent):
        """按来源查看最新通知，默认显示 5 条。"""
        source, error = self._resolve_source_from_event(event, "latest_source")
        if source is None:
            yield event.plain_result(error)
            return

        notices = await self._rss_service.fetch_notices(source_keys={source["key"]})
        if not notices:
            yield event.plain_result(f"来源 {source['name']} 暂未抓取到通知，请稍后再试。")
            return
        title = f"最新通知: {source['name']} ({source['key']})"
        yield event.plain_result(format_latest_lines(title, notices[:5]))

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
        notices = await self._rss_service.fetch_notices()
        if not notices:
            return 0

        await self._rss_service.write_rss(notices)
        seen_ids = set(await self.get_kv_data("seen_notice_ids", []))
        current_ids = [item["id"] for item in notices]

        if not seen_ids:
            await self.put_kv_data("seen_notice_ids", current_ids)
            return 0

        new_items = [item for item in notices if item["id"] not in seen_ids]
        if not new_items:
            return 0

        new_items.reverse()
        if push:
            await self._push_new_items(new_items)

        merged = current_ids + [item_id for item_id in seen_ids if item_id not in current_ids]
        await self.put_kv_data("seen_notice_ids", merged[:1000])
        return len(new_items)

    async def _refresh_rss_only(self):
        notices = await self._rss_service.fetch_notices()
        if notices:
            await self._rss_service.write_rss(notices)

    async def _push_new_items(self, items: list[Notice]):
        global_sessions = set(await self._subscription_store.get_global_sessions())
        source_subscriptions = await self._subscription_store.get_source_subscriptions()

        for item in items:
            recipients = set(global_sessions)
            recipients.update(
                session
                for session, source_keys in source_subscriptions.items()
                if item["source_key"] in source_keys
            )
            if not recipients:
                continue

            text = (
                f"[DLUT 新通知][{item['source']}] {item['title']}\n"
                f"{item['date']}\n"
                f"{item['link']}"
            )
            for umo in recipients:
                try:
                    chain = MessageChain().message(text)
                    await self.context.send_message(umo, chain)
                except Exception as exc:
                    logger.warning(f"[DLUT RSS] 向会话推送失败 {umo}: {exc}")

    def _resolve_source_from_event(
        self, event: AstrMessageEvent, command_name: str
    ) -> tuple[SourceConfig | None, str]:
        query = extract_command_args(event, command_name)
        if not query:
            return None, (
                "请提供来源 key 或来源名。\n"
                "可先使用 /dlut sources 查看可用来源。"
            )

        source = resolve_source(query)
        if source is None:
            return None, (
                f"未找到来源: {query}\n"
                "可先使用 /dlut sources 查看可用来源。"
            )
        return source, ""

    def _cfg_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except Exception:
            return default

    def _help_text(self) -> str:
        return "\n".join(
            [
                "DLUT RSS 插件使用说明",
                "",
                "基础命令:",
                "- /dlut help: 查看本帮助",
                "- /dlut sources: 查看支持的来源和当前会话订阅状态",
                "- /dlut latest: 查看全部来源最近 5 条通知",
                "- /dlut latest_source <来源key|来源名>: 查看单个来源最近 5 条通知",
                "- /dlut rss: 查看聚合 RSS 文件路径",
                "- /dlut check: 立即检查一次并推送增量",
                "",
                "订阅命令:",
                "- /dlut subscribe: 订阅全部来源",
                "- /dlut unsubscribe: 取消全部来源订阅",
                "- /dlut subscribe_source <来源key|来源名>: 订阅单个来源",
                "- /dlut unsubscribe_source <来源key|来源名>: 取消单个来源订阅",
                "",
                "使用建议:",
                "- 想先看看有哪些来源: /dlut sources",
                "- 想订阅所有通知: /dlut subscribe",
                "- 想只订阅某个来源: /dlut subscribe_source ss_bkstz",
                "- 想查看某个来源最新通知: /dlut latest_source teach_byxx",
                "",
                "说明:",
                "- 来源参数既支持来源 key，也支持来源名或唯一部分匹配",
                "- 首次运行只建立基线，不会推送历史通知",
            ]
        )


