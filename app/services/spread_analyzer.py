# -*- coding: utf-8 -*-
"""
事件溯源与关键传播路径分析模块
基于 raw_news 中的关联新闻报道，自动构建传播时序链，
识别首发来源、核心放大节点、官方介入节点，生成 ECharts 可视化关系图数据
"""
import json
import logging
from datetime import datetime
from collections import Counter, defaultdict
from app.core.database import get_connection
from app.services.nlp_tools import segment_text

logger = logging.getLogger("services.spread_analyzer")

# 官方媒体列表（用于识别官方介入节点）
OFFICIAL_MEDIA = [
    "人民网", "新华网", "央视", "中央", "人民日报",
    "光明网", "中国新闻网", "经济日报", "中国青年报",
    "环球时报", "解放军报", "法治日报",
]

# 平台颜色映射（用于 ECharts 节点颜色）
PLATFORM_COLORS = {
    "微博": "#E6162D",
    "知乎": "#0066FF",
    "微信": "#07C160",
    "B站": "#FB7299",
    "抖音": "#010101",
    "人民网": "#CC0000",
    "新华网": "#CC0000",
    "小红书": "#FE2C55",
}


def analyze_spread_path(event_id: int) -> dict:
    """
    分析指定事件的传播路径，构建传播图数据

    流程:
    1. 从 raw_news 中查找与该事件关联的新闻（基于 event_id 或关键词匹配）
    2. 按时间排序构建传播时序链
    3. 识别关键节点:
       - origin（首发来源）: 最早的新闻
       - amplifier（核心放大）: 转发量/互动量最高的来源
       - official（官方回应）: 首个官媒来源的新闻
       - secondary（次级传播）: 其余节点
    4. 生成 ECharts graph 格式的 nodes + links
    5. 写入/更新 spread_info 表

    参数:
        event_id: 事件 ID

    返回:
        {
            "event_id": int,
            "origin_platform": str,     # 首发平台
            "origin_url": str,          # 首发链接
            "spread_depth": int,         # 传播深度
            "total_reposts": int,        # 估算转发总量
            "total_reads": int,          # 估算阅读总量
            "spread_nodes": list,        # 传播节点列表
            "graph_data": {              # ECharts 关系图数据
                "nodes": [...],
                "links": [...],
                "categories": [...],
            }
        }
    """
    conn: object = get_connection()
    try:
        # 1. 获取事件基本信息
        event: dict | None = conn.execute(
            "SELECT * FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None

        # 2. 获取关联新闻列表
        news_list: list[dict] = _get_related_news(conn, event_id, event["title"])
        if not news_list:
            logger.info("事件 %d 无关联新闻，无法分析传播路径", event_id)
            return _build_empty_result(event_id)

        # 3. 按时间排序（发布时间优先，爬取时间兜底）
        news_list.sort(
            key=lambda x: x.get("published_at") or x.get("crawled_at") or ""
        )

        # 4. 识别关键节点（首发来源、核心放大、官方回应、次级传播）
        nodes: list[dict] = _identify_key_nodes(news_list)

        # 5. 构建 ECharts 关系图数据（nodes + links + categories）
        graph_data: dict = _build_graph_data(nodes, news_list)

        # 6. 计算汇总指标
        origin: dict | None = nodes[0] if nodes else None
        result: dict = {
            "event_id": event_id,
            "origin_platform": origin["platform"] if origin else "",
            "origin_url": origin.get("url", "") if origin else "",
            "spread_depth": min(len(nodes), 10),
            "total_reposts": sum(n.get("reposts", 0) for n in nodes),
            "total_reads": sum(n.get("reads", 0) for n in nodes),
            "spread_nodes": _format_spread_nodes(nodes),
            "graph_data": graph_data,
        }

        # 7. 写入/更新 spread_info 表
        _save_spread_info(conn, event_id, result)

        logger.info(
            "事件 %d 传播路径分析完成: %d 个节点, 深度 %d",
            event_id, len(nodes), result["spread_depth"],
        )
        return result

    except Exception as e:
        logger.error("传播路径分析失败: event_id=%d, %s", event_id, e)
        return None
    finally:
        conn.close()


def _get_related_news(conn: object, event_id: int, event_title: str) -> list[dict]:
    """
    获取与事件关联的新闻列表

    策略:
    1. 优先通过 raw_news.event_id 直接关联
    2. 若无直接关联，则对事件标题进行分词后按关键词模糊匹配

    参数:
        conn: 数据库连接对象
        event_id: 事件 ID
        event_title: 事件标题（用于关键词回退匹配）

    返回:
        新闻字典列表，按发布时间升序排列
    """
    # 优先通过 event_id 关联查询
    rows: list = conn.execute(
        "SELECT id, title, content, source_platform, published_at, original_url, crawled_at "
        "FROM raw_news WHERE event_id = ? ORDER BY published_at ASC",
        (event_id,),
    ).fetchall()

    if rows:
        return [dict(r) for r in rows]

    # 如果没有 event_id 关联，通过标题关键词模糊匹配
    if event_title:
        words: list[str] = [
            w for w in segment_text(event_title) if len(w) >= 2
        ][:5]
        if words:
            conditions: str = " OR ".join(
                ["title LIKE ?" for _ in words]
            )
            params: list[str] = [f"%{w}%" for w in words]
            rows = conn.execute(
                f"SELECT id, title, content, source_platform, published_at, original_url, crawled_at "
                f"FROM raw_news WHERE {conditions} ORDER BY published_at ASC LIMIT 50",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    return []


def _identify_key_nodes(news_list: list[dict]) -> list[dict]:
    """
    识别关键传播节点，为每条新闻分配角色类别

    分类规则:
    - 首发来源（category=0）: 时间线上的第一条新闻，symbolSize 最大
    - 核心放大（category=1）: 出现在前5条中的社媒平台新闻
    - 官方回应（category=2）: 来源平台包含官方媒体关键词的新闻
    - 次级传播（category=3）: 其余所有新闻

    参数:
        news_list: 按时间排序的新闻字典列表

    返回:
        带有 category/category_name/symbolSize 等附加字段的节点列表
    """
    nodes: list[dict] = []
    for i, news in enumerate(news_list):
        platform = news.get("source_platform", "未知")
        title = news.get("title", "")
        published = news.get("published_at") or news.get("crawled_at") or ""
        url = news.get("original_url", "")

        # 默认角色：次级传播
        category: int = 3  # secondary
        category_name: str = "次级传播"
        symbol_size: int = 20

        # 首发来源：时间线上的第一条新闻
        if i == 0:
            category = 0
            category_name = "首发来源"
            symbol_size = 40

        # 官方回应：来源平台匹配官方媒体关键词
        elif any(official in platform for official in OFFICIAL_MEDIA):
            category = 2
            category_name = "官方回应"
            symbol_size = 30

        # 核心放大：前5条中的主流社媒平台新闻
        elif platform in ["微博", "知乎", "抖音"]:
            if 0 < i < 5:
                category = 1
                category_name = "核心放大"
                symbol_size = 30

        nodes.append({
            "id": news.get("id", i),
            "name": title[:25] + ("..." if len(title) > 25 else ""),
            "full_title": title,
            "platform": platform,
            "category": category,
            "category_name": category_name,
            "symbolSize": symbol_size,
            "published_at": published,
            "url": url,
            "reposts": _estimate_interaction(title),
            "reads": _estimate_interaction(title, base=500),
        })

    return nodes


def _build_graph_data(nodes: list[dict], news_list: list[dict]) -> dict:
    """
    构建 ECharts 关系图（graph）所需的 nodes/links/categories 数据

    节点格式:
        {"name": str, "category": int, "symbolSize": int, "value": int,
         "itemStyle": {...}, "label": {...}}

    边格式:
        {"source": str, "target": str, "value": int, "lineStyle": {...}}

    连接规则:
    1. 时序链: 每条新闻按时间顺序连接到下一条（实线）
    2. 放大连接: 首发来源额外连接到前5条中的核心放大/官方回应节点（虚线）

    参数:
        nodes: 已识别角色的传播节点列表
        news_list: 原始新闻列表（暂未使用，保留扩展空间）

    返回:
        包含 nodes/links/categories 的 ECharts graph 数据字典
    """
    # 构建节点列表
    echarts_nodes = []
    for n in nodes:
        color = PLATFORM_COLORS.get(n["platform"], "#409eff")
        echarts_nodes.append({
            "name": n["name"],
            "category": n["category"],
            "symbolSize": n["symbolSize"],
            "value": n["reads"],
            "itemStyle": {
                "color": color,
                "borderColor": "#fff",
                "borderWidth": 2,
            },
            "label": {
                "show": n["symbolSize"] >= 30,  # 重要节点才显示标签
                "fontSize": 10,
                "formatter": n["name"][:15],
            },
        })

    # 构建时序边：每条新闻连接到下一条
    echarts_links = []
    for i in range(len(nodes) - 1):
        echarts_links.append({
            "source": nodes[i]["name"],
            "target": nodes[i + 1]["name"],
            "value": nodes[i].get("reposts", 10),
            "lineStyle": {
                "curveness": 0.2,
                "width": 2,
                "type": "solid",
                "opacity": 0.6,
            },
        })

    # 额外的放大连接：首发 → 核心放大/官方回应节点（虚线）
    if len(nodes) > 2:
        for i in range(1, min(len(nodes), 5)):
            if nodes[i]["category"] in [1, 2]:
                # 避免重复连接
                existing = any(
                    l["source"] == nodes[0]["name"]
                    and l["target"] == nodes[i]["name"]
                    for l in echarts_links
                )
                if not existing:
                    echarts_links.append({
                        "source": nodes[0]["name"],
                        "target": nodes[i]["name"],
                        "value": nodes[i].get("reposts", 50),
                        "lineStyle": {
                            "curveness": 0.3,
                            "width": 3,
                            "type": "dashed",
                            "opacity": 0.4,
                        },
                    })

    return {
        "nodes": echarts_nodes,
        "links": echarts_links,
        "categories": [
            {"name": "首发来源"},
            {"name": "核心放大"},
            {"name": "官方回应"},
            {"name": "次级传播"},
        ],
    }


def _estimate_interaction(title: str, base: int = 100) -> int:
    """
    根据新闻标题估算互动量（转发/阅读数）

    由于爬取数据中通常没有精确的互动量字段，
    这里基于标题长度做简单线性估算，提供一个合理的量级参考。

    参数:
        title: 新闻标题文本
        base: 基础互动量（默认100，用于转发估算；阅读估算时传入500）

    返回:
        估算的整型互动量
    """
    if not title:
        return base
    length_factor: float = min(len(title) / 20, 2.0)
    return int(base * length_factor)


def _format_spread_nodes(nodes: list[dict]) -> list[dict]:
    """
    格式化传播节点为 spread_info 表的 JSON 存储格式

    仅保留展示所需的精简字段：名称、平台、角色类别、时间、链接。

    参数:
        nodes: 完整的传播节点列表

    返回:
        精简后的节点字典列表，用于序列化存入 spread_nodes 字段
    """
    return [
        {
            "name": n["name"],
            "platform": n["platform"],
            "category": n["category_name"],
            "published_at": n["published_at"],
            "url": n["url"],
        }
        for n in nodes
    ]


def _save_spread_info(conn: object, event_id: int, result: dict) -> None:
    """
    将传播分析结果写入或更新 spread_info 表

    若 event_id 对应的记录已存在则执行 UPDATE，否则执行 INSERT。
    graph_data 和 spread_nodes 均以 JSON 字符串存储。

    参数:
        conn: 数据库连接对象
        event_id: 事件 ID
        result: analyze_spread_path 返回的完整分析结果字典
    """
    # 检查是否已有该事件的溯源记录
    existing = conn.execute(
        "SELECT id FROM spread_info WHERE event_id = ? LIMIT 1",
        (event_id,),
    ).fetchone()

    serialized_nodes: str = json.dumps(
        result["spread_nodes"], ensure_ascii=False
    )
    serialized_graph: str = json.dumps(
        result["graph_data"], ensure_ascii=False
    )

    if existing:
        conn.execute(
            "UPDATE spread_info SET "
            "origin_platform=?, origin_url=?, spread_nodes=?, spread_depth=?, "
            "total_reposts=?, total_reads=?, graph_data=? "
            "WHERE event_id=?",
            (
                result["origin_platform"],
                result["origin_url"],
                serialized_nodes,
                result["spread_depth"],
                result["total_reposts"],
                result["total_reads"],
                serialized_graph,
                event_id,
            ),
        )
    else:
        conn.execute(
            "INSERT INTO spread_info "
            "(event_id, origin_platform, origin_url, spread_nodes, spread_depth, "
            "total_reposts, total_reads, graph_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                result["origin_platform"],
                result["origin_url"],
                serialized_nodes,
                result["spread_depth"],
                result["total_reposts"],
                result["total_reads"],
                serialized_graph,
            ),
        )
    conn.commit()


def _build_empty_result(event_id: int) -> dict:
    """
    构建空结果的默认返回值

    当事件没有任何关联新闻时返回此默认结构，
    确保前端始终能接收到合法的 graph_data（空 nodes/links）而不会报错。

    参数:
        event_id: 事件 ID

    返回:
        所有数值字段为零、列表/字典字段为空的默认结果字典
    """
    return {
        "event_id": event_id,
        "origin_platform": "",
        "origin_url": "",
        "spread_depth": 0,
        "total_reposts": 0,
        "total_reads": 0,
        "spread_nodes": [],
        "graph_data": {"nodes": [], "links": [], "categories": []},
    }
