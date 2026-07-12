# -*- coding: utf-8 -*-
"""
================================================================================
  网络舆情智能分析系统 — 传播溯源模块 (spread_trace.py)
================================================================================
根据事件的关联新闻报道，自动构建传播链路：

  1. 按时间排序关联新闻，确定传播时间线和首发来源
  2. 按平台分组统计报道分布，识别传播关键节点（核心转发源）
  3. 计算传播深度（经过多少个独立传播层）
  4. 估算转发量和阅读量
  5. 生成 ECharts 关系图可用的节点/边数据
  6. 所有结果写入 spread_info 表，前端可直接渲染

用法：
  python spread_trace.py                  # 对所有有分析的事件生成溯源
  python spread_trace.py --event_id 10   # 只处理指定事件
  python spread_trace.py --help          # 查看帮助
================================================================================
"""

import sys
import json
import hashlib
import argparse
import logging
from collections import Counter, defaultdict, OrderedDict
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import jieba

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent

# 复用项目的数据库连接
sys.path.insert(0, str(PROJECT_ROOT / "app"))
from core.database import get_connection

# -----------------------------------------------------------------------
# 日志
# -----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("spread_trace")

# -----------------------------------------------------------------------
# 平台类型分类（用于关系图节点样式）
# -----------------------------------------------------------------------
PLATFORM_CATEGORIES = {
    # 主流媒体
    "人民网-时政": "official", "人民网-国际": "official", "人民网-财经": "official",
    "人民网-社会": "official", "人民网-科技": "official", "人民网-教育": "official",
    # 社交平台
    "微博": "social", "抖音": "social", "知乎": "social",
    "微信公众号": "social", "B站": "social", "今日头条": "social",
    # 新闻门户
    "澎湃新闻": "portal", "界面新闻": "portal", "新华网": "portal",
    # 默认
}

# 平台品牌色（用于前端 ECharts 关系图节点颜色）
PLATFORM_COLORS = {
    "official": "#c7000b",
    "social": "#409eff",
    "portal": "#67c23a",
    "unknown": "#909399",
}


# -----------------------------------------------------------------------
# 数据库操作
# -----------------------------------------------------------------------
def fetch_related_news(event_id: int) -> List[Dict]:
    """
    获取事件的关联新闻（通过标题关键词匹配 raw_news）。
    返回按发布时间排序的字典列表。
    """
    conn = get_connection()
    try:
        # 先获取事件标题
        event = conn.execute(
            "SELECT title FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return []

        # 提取标题关键词（使用jieba分词，过滤单字和停用词）
        title = event["title"]
        keywords = [w for w in jieba.cut(title) if len(w.strip()) >= 2][:5]

        if not keywords:
            return []

        like_conditions = " OR ".join(["title LIKE ?" for _ in keywords])
        rows = conn.execute(
            f"SELECT id, title, content, source_platform, published_at, original_url "
            f"FROM raw_news WHERE {like_conditions} "
            f"ORDER BY published_at ASC",
            [f"%{kw}%" for kw in keywords]
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetch_event_analysis(event_id: int) -> Optional[Dict]:
    """获取事件分析数据"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_spread_info(event_id: int, trace_result: Dict) -> int:
    """
    将传播溯源结果写入 spread_info 表（upsert：存在则更新，不存在则插入）。
    返回记录 ID。
    """
    conn = get_connection()
    try:
        # 检查是否已有记录
        existing = conn.execute(
            "SELECT id FROM spread_info WHERE event_id = ?", (event_id,)
        ).fetchone()

        spread_nodes_json = json.dumps(trace_result["spread_nodes"], ensure_ascii=False)
        graph_data_json = json.dumps(trace_result["graph_data"], ensure_ascii=False)

        if existing:
            conn.execute(
                "UPDATE spread_info SET "
                "origin_platform=?, origin_url=?, spread_nodes=?, spread_depth=?, "
                "total_reposts=?, total_reads=?, graph_data=?, traced_at=datetime('now','localtime') "
                "WHERE event_id=?",
                (trace_result["origin_platform"], trace_result["origin_url"],
                 spread_nodes_json, trace_result["spread_depth"],
                 trace_result["total_reposts"], trace_result["total_reads"],
                 graph_data_json, event_id),
            )
            conn.commit()
            return existing["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO spread_info "
                "(event_id, origin_platform, origin_url, spread_nodes, "
                "spread_depth, total_reposts, total_reads, graph_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, trace_result["origin_platform"], trace_result["origin_url"],
                 spread_nodes_json, trace_result["spread_depth"],
                 trace_result["total_reposts"], trace_result["total_reads"],
                 graph_data_json),
            )
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def ensure_graph_data_column():
    """确保 spread_info 表有 graph_data 列"""
    conn = get_connection()
    try:
        conn.execute("ALTER TABLE spread_info ADD COLUMN graph_data TEXT DEFAULT '{}'")
        conn.commit()
        logger.info("已添加 graph_data 列")
    except Exception:
        pass  # 列已存在
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 传播链路构建算法
# -----------------------------------------------------------------------
def build_spread_chain(news_list: List[Dict]) -> Dict:
    """
    核心算法：根据新闻的时间序列和平台分布，构建传播链路。

    算法步骤：
      1. 按发布时间排序，确定首发来源（最早的报道）
      2. 按平台分组，统计每个平台的报道数和时间跨度
      3. 识别传播关键节点：
         - 首发节点：最早发布的报道
         - 核心放大节点：报道数最多的平台中的首条
         - 次级传播节点：其他平台的首条报道
      4. 计算传播深度：独立平台数量（至少出现2篇才算一个传播层）
      5. 估算转发量/阅读量（基于报道量和平台的传播系数）
      6. 生成 ECharts 关系图数据（nodes + links）

    参数:
        news_list: 按时间排序的关联新闻列表

    返回:
        包含所有溯源结果的字典
    """
    if not news_list:
        return {
            "origin_platform": "未知",
            "origin_url": None,
            "spread_nodes": [],
            "spread_depth": 0,
            "total_reposts": 0,
            "total_reads": 0,
            "graph_data": {"nodes": [], "links": []},
        }

    # ---- 1. 确定首发来源 ----
    first_news = news_list[0]
    origin_platform = first_news["source_platform"]
    origin_url = first_news.get("original_url")
    origin_time = first_news.get("published_at", "")
    origin_title = first_news["title"]

    logger.info("  首发来源: %s | 时间: %s", origin_platform, origin_time)

    # ---- 2. 按平台分组 ----
    platform_groups = defaultdict(list)
    for news in news_list:
        platform_groups[news["source_platform"]].append(news)

    # 按报道数降序排列
    sorted_platforms = sorted(platform_groups.items(), key=lambda x: len(x[1]), reverse=True)

    # ---- 3. 构建传播节点 ----
    spread_nodes = []
    node_id_map = {}  # 用于关系图 node_id 映射

    # 首发节点
    first_node = {
        "platform": origin_platform,
        "user": "首发来源",
        "time": origin_time,
        "title": origin_title[:60],
        "type": "origin",       # origin / amplifier / secondary
        "news_count": len(platform_groups[origin_platform]),
    }
    spread_nodes.append(first_node)
    node_id_map[origin_platform] = 0

    # 核心放大节点和次级节点
    for idx, (platform, news_items) in enumerate(sorted_platforms):
        if platform == origin_platform:
            continue  # 已作为首发节点

        first_item = news_items[0]
        count = len(news_items)

        if idx == 0 or count >= 3:
            node_type = "amplifier"  # 核心放大节点
        else:
            node_type = "secondary"  # 次级传播节点

        # 模拟传播账号名（基于平台名称 + 新闻标题关键词）
        title_keyword = first_item["title"][:10]
        user_name = f"{platform}·{title_keyword}"

        node = {
            "platform": platform,
            "user": user_name,
            "time": first_item.get("published_at", ""),
            "title": first_item["title"][:60],
            "type": node_type,
            "news_count": count,
        }
        node_id = len(spread_nodes)
        spread_nodes.append(node)
        node_id_map[platform] = node_id

    # ---- 4. 计算传播深度 ----
    # 传播深度 = 至少有2篇报道的独立平台数（过滤噪音平台）
    significant_platforms = [
        p for p, items in platform_groups.items()
        if len(items) >= 2
    ]
    spread_depth = len(significant_platforms)

    # ---- 5. 估算转发量和阅读量 ----
    # 基于平台传播系数估算
    platform_repost_factor = {
        "微博": 50, "抖音": 80, "知乎": 15,
        "微信公众号": 100, "B站": 30, "今日头条": 40,
    }

    total_reposts = 0
    total_reads = 0
    for platform, items in platform_groups.items():
        count = len(items)
        factor = platform_repost_factor.get(platform, 20)
        total_reposts += count * factor
        total_reads += count * factor * 12  # 阅读量约为转发量的12倍

    # ---- 6. 生成 ECharts 关系图数据 ----
    graph_data = build_graph_data(spread_nodes, node_id_map, platform_groups)

    logger.info("  传播深度: %d 层 | 估算转发: %d | 估算阅读: %d",
                 spread_depth, total_reposts, total_reads)

    return {
        "origin_platform": origin_platform,
        "origin_url": origin_url,
        "spread_nodes": spread_nodes,
        "spread_depth": spread_depth,
        "total_reposts": total_reposts,
        "total_reads": total_reads,
        "graph_data": graph_data,
    }


def build_graph_data(spread_nodes: List[Dict], node_id_map: Dict,
                       platform_groups: Dict) -> Dict:
    """
    生成 ECharts 关系图（力导向图）所需的 nodes 和 links 数据。

    节点属性:
      - id, name, symbolSize(按报道数), category, itemStyle

    边属性:
      - source, target, lineStyle
    """
    nodes = []
    links = []

    for idx, node in enumerate(spread_nodes):
        category = PLATFORM_CATEGORIES.get(node["platform"], "unknown")

        nodes.append({
            "id": idx,
            "name": f"{node['platform']}\n({node['user']})",
            "symbolSize": max(20, min(60, node["news_count"] * 8 + 20)),
            "category": list(PLATFORM_CATEGORIES.values()).index(category),
            "platform": node["platform"],
            "type": node["type"],
            "news_count": node["news_count"],
            "time": node.get("time", ""),
            "label": {
                "show": True,
                "fontSize": 10,
                "formatter": node["platform"],
            },
        })

    # 构建边：从首发节点连到所有其他节点
    # 放大节点之间也互相连接（表示跨平台传播）
    origin_id = 0
    amplifier_ids = [i for i, n in enumerate(spread_nodes) if n["type"] == "amplifier"]

    for idx, node in enumerate(spread_nodes):
        if idx == origin_id:
            continue  # 首发节点不连自己

        # 首发 → 当前节点
        links.append({
            "source": origin_id,
            "target": idx,
            "lineStyle": {
                "width": 2,
                "curveness": 0.2,
                "color": "rgba(64,158,255,0.6)",
            },
        })

        # 放大节点之间的互相连接（表示信息在不同大平台间流动）
        if node["type"] == "amplifier":
            for amp_id in amplifier_ids:
                if amp_id != idx:
                    links.append({
                        "source": idx,
                        "target": amp_id,
                        "lineStyle": {
                            "width": 1,
                            "curveness": 0.3,
                            "type": "dashed",
                            "color": "rgba(144,147,156,0.5)",
                        },
                    })

    return {"nodes": nodes, "links": links}


# -----------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------
def trace_event(event_id: int) -> bool:
    """
    对单个事件执行传播溯源分析。
    返回 True 表示成功生成溯源数据。
    """
    logger.info("-" * 40)
    logger.info("正在分析事件 #%d 的传播链路...", event_id)

    # 1. 获取关联新闻
    news_list = fetch_related_news(event_id)
    if not news_list:
        logger.info("  事件 #%d 无关联新闻，跳过溯源", event_id)
        return False

    logger.info("  找到 %d 条关联新闻", len(news_list))

    # 2. 构建传播链路
    result = build_spread_chain(news_list)

    # 3. 写入数据库
    save_spread_info(event_id, result)
    logger.info("  -> spread_info 已写入 (深度=%d, 节点=%d)",
                 result["spread_depth"], len(result["spread_nodes"]))

    return True


def trace_all():
    """对所有有分析数据的事件执行传播溯源"""
    conn = get_connection()
    try:
        # 获取所有有分析的事件
        events = conn.execute(
            "SELECT DISTINCT event_id FROM event_analysis"
        ).fetchall()
    finally:
        conn.close()

    total = len(events)
    traced = 0
    for i, row in enumerate(events):
        event_id = row["event_id"]
        logger.info("[%d/%d] 处理事件 #%d...", i + 1, total, event_id)
        if trace_event(event_id):
            traced += 1

    logger.info("=" * 60)
    logger.info("传播溯源完成: 共 %d 个事件, 成功 %d 个", total, traced)
    logger.info("=" * 60)


# -----------------------------------------------------------------------
# CLI 入口
# -----------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="传播溯源模块 — 构建事件传播链路",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python spread_trace.py                  # 对所有事件生成溯源
  python spread_trace.py --event_id 10   # 只处理事件 #10
        """,
    )
    parser.add_argument("--event_id", type=int, default=None, help="指定事件ID")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # 确保 graph_data 列存在
    ensure_graph_data_column()

    if args.event_id:
        trace_event(args.event_id)
    else:
        trace_all()
