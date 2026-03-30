# astrbot_plugin_dlut_rss

抓取大连理工大学多个通知站点，生成聚合 RSS 文件，并把新增通知主动推送到已订阅会话。

## 功能

- 支持多个来源的通知抓取
- 定时轮询检测新增通知
- 生成标准 RSS 2.0 文件
- 向已订阅会话主动推送新增通知

## 当前支持来源

- 开发区校区教学运行保障中心
- 教务处部院信息
- 教务处教学文件
- 教务处其他文件
- 教务处重要通告
- 软件学院-本科生通知
- 软件学院-研究生通知
- 软件学院-研究生招生
- 软件学院-学术报告
- 软件学院-创新实践
- 软件学院-国际交流
- 软件学院-国际通知
- 软件学院-学工通知
- 软件学院-学生活动
- 集成电路学院-本科生教学
- 集成电路学院-本科生管理
- 集成电路学院-研究生教学
- 集成电路学院-研究生管理

## 依赖

- `httpx`
- `beautifulsoup4`

安装方式: 在插件目录执行依赖安装，或由 AstrBot 插件依赖管理自动安装 `requirements.txt`。

## 指令

- `/dlut help`: 查看插件帮助
- `/dlut subscribe`: 订阅当前会话
- `/dlut unsubscribe`: 取消订阅当前会话
- `/dlut sources`: 查看支持的来源与当前会话订阅状态
- `/dlut subscribe_source <来源key|来源名>`: 订阅单个来源
- `/dlut unsubscribe_source <来源key|来源名>`: 取消订阅单个来源
- `/dlut check`: 立即检查一次并推送增量
- `/dlut latest`: 查看最近 5 条聚合通知
- `/dlut latest_source <来源key|来源名>`: 查看单个来源最近 5 条通知
- `/dlut rss`: 查看聚合 RSS 文件路径

## 使用示例

- 查看帮助: `/dlut help`
- 查看所有来源: `/dlut sources`
- 订阅全部来源: `/dlut subscribe`
- 订阅软件学院本科生通知: `/dlut subscribe_source ss_bkstz`
- 查看教务处部院信息最新通知: `/dlut latest_source teach_byxx`
- 手动触发一次检查: `/dlut check`

## 配置项

配置文件 Schema 位于 `_conf_schema.json`，支持在 AstrBot WebUI 可视化配置:

- `rss_title`: 聚合 RSS 标题
- `rss_max_items`: RSS 保留条数
- `poll_interval_minutes`: 轮询间隔（分钟）
- `request_timeout_seconds`: 请求超时（秒）

## 数据存储

- 订阅会话与已推送通知 ID: AstrBot KV 存储
- RSS 文件: `data/plugin_data/astrbot_plugin_dlut_rss/dlut_notice_rss.xml`

## 说明

- 首次运行会建立通知基线，不会推送历史消息。
- 推送消息与 RSS 条目会携带来源名称，便于区分通知站点。
- 支持“全局订阅”和“按来源订阅”并存；同一会话不会收到重复推送。
- 若学校页面结构发生变化，可能需要同步调整 `sources.py` 中的选择器。
