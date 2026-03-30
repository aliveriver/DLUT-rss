import re
from collections.abc import Callable
from typing import TypedDict

from bs4 import Tag

from parsers import parse_h2_child, parse_text_content, parse_title_attr

Parser = Callable[[Tag], str]


class SourceConfig(TypedDict, total=False):
    key: str
    name: str
    url: str
    selector: str
    parser: Parser
    category: str
    base_url: str


SOURCES: list[SourceConfig] = [
    {
        "key": "campus_jxyxbzzx",
        "name": "开发区校区教学运行保障中心",
        "url": "https://jxyxbzzx.dlut.edu.cn/tzgg/kfqxq.htm",
        "selector": "div.l_text-wrapper_3 a[href*='/info/']",
        "parser": parse_text_content,
        "category": "campus",
        "base_url": "https://jxyxbzzx.dlut.edu.cn/",
    },
    {
        "key": "teach_byxx",
        "name": "教务处部院信息",
        "url": "https://teach.dlut.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1206",
        "selector": ".list a[href*='wbnewsid=']",
        "parser": parse_title_attr,
        "category": "teaching",
        "base_url": "https://teach.dlut.edu.cn/",
    },
    {
        "key": "teach_zytg",
        "name": "教务处重要通告",
        "url": "https://teach.dlut.edu.cn/zhongyaotonggao/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1016",
        "selector": ".list a[href*='wbnewsid=']",
        "parser": parse_title_attr,
        "category": "teaching",
        "base_url": "https://teach.dlut.edu.cn/",
    },
    {
        "key": "teach_jxwj",
        "name": "教务处教学文件",
        "url": "https://teach.dlut.edu.cn/jiaoxuewenjian/list.jsp?totalpage=68&PAGENUM=3&urltype=tree.TreeTempUrl&wbtreeid=1082",
        "selector": ".list a[href*='wbnewsid=']",
        "parser": parse_title_attr,
        "category": "teaching",
        "base_url": "https://teach.dlut.edu.cn/",
    },
    {
        "key": "teach_qtwj",
        "name": "教务处其他文件",
        "url": "https://teach.dlut.edu.cn/qitawenjian/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1081",
        "selector": ".list a[href*='wbnewsid=']",
        "parser": parse_title_attr,
        "category": "teaching",
        "base_url": "https://teach.dlut.edu.cn/",
    },
    {
        "key": "ss_xshd",
        "name": "软件学院-学生活动",
        "url": "https://ss.dlut.edu.cn/xsgz/xshd.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_xsgz",
        "name": "软件学院-学工通知",
        "url": "https://ss.dlut.edu.cn/xsgz/tzgg.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_gjtz",
        "name": "软件学院-国际通知",
        "url": "https://ss.dlut.edu.cn/gjhzjl/tzgg.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_gjjl",
        "name": "软件学院-国际交流",
        "url": "https://ss.dlut.edu.cn/gjhzjl/gjjl.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_xsbg",
        "name": "软件学院-学术报告",
        "url": "https://ss.dlut.edu.cn/kxyj/xsbg.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_cxsj",
        "name": "软件学院-创新实践",
        "url": "https://ss.dlut.edu.cn/rcpy/cxsj/hdtz.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_yjszs",
        "name": "软件学院-研究生招生",
        "url": "https://ss.dlut.edu.cn/rcpy/yjspy/yjszs.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_yjstz",
        "name": "软件学院-研究生通知",
        "url": "https://ss.dlut.edu.cn/rcpy/yjspy/yjstz.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ss_bkstz",
        "name": "软件学院-本科生通知",
        "url": "https://ss.dlut.edu.cn/rcpy/bkspy/bkstz.htm",
        "selector": ".list04 .item a",
        "parser": parse_h2_child,
        "category": "ssdut",
    },
    {
        "key": "ic_bksjx",
        "name": "集成电路学院-本科生教学",
        "url": "https://ic.dlut.edu.cn/rcpy/bkspy/bksjx.htm",
        "selector": ".ny_newsListRow a",
        "parser": parse_text_content,
        "category": "ic",
        "base_url": "https://ic.dlut.edu.cn/",
    },
    {
        "key": "ic_bksgl",
        "name": "集成电路学院-本科生管理",
        "url": "https://ic.dlut.edu.cn/rcpy/bkspy/bksgl.htm",
        "selector": ".ny_newsListRow a",
        "parser": parse_text_content,
        "category": "ic",
        "base_url": "https://ic.dlut.edu.cn/",
    },
    {
        "key": "ic_yjsjx",
        "name": "集成电路学院-研究生教学",
        "url": "https://ic.dlut.edu.cn/rcpy/yjspy/yjsjx.htm",
        "selector": ".ny_newsListRow a",
        "parser": parse_text_content,
        "category": "ic",
        "base_url": "https://ic.dlut.edu.cn/",
    },
    {
        "key": "ic_yjsgl",
        "name": "集成电路学院-研究生管理",
        "url": "https://ic.dlut.edu.cn/rcpy/yjspy/yjsgl.htm",
        "selector": ".ny_newsListRow a",
        "parser": parse_text_content,
        "category": "ic",
        "base_url": "https://ic.dlut.edu.cn/",
    },
]

SOURCES_BY_KEY = {source["key"]: source for source in SOURCES}


def resolve_source(query: str) -> SourceConfig | None:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return None

    exact = SOURCES_BY_KEY.get(query.strip())
    if exact is not None:
        return exact

    matches = [
        source
        for source in SOURCES
        if normalized_query in {
            _normalize_query(source["key"]),
            _normalize_query(source["name"]),
        }
        or normalized_query in _normalize_query(source["key"])
        or normalized_query in _normalize_query(source["name"])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def format_source_lines(subscribed_keys: set[str] | None = None) -> list[str]:
    subscribed_keys = subscribed_keys or set()
    lines: list[str] = []
    for source in SOURCES:
        status = " [已单独订阅]" if source["key"] in subscribed_keys else ""
        lines.append(f"- {source['key']}: {source['name']}{status}")
    return lines


def _normalize_query(text: str) -> str:
    return re.sub(r"[\s_\-]+", "", text).casefold()




