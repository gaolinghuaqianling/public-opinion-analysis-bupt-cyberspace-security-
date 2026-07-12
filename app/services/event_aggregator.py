# -*- coding: utf-8 -*-
"""
================================================================================
  舆情事件聚合模块 (event_aggregator.py)
================================================================================
基于文本相似度，自动将同一事件的多条报道聚合关联。

核心功能:
  1. 相似事件聚合 — 对 hot_event 中的事件标题计算 SimHash，按汉明距离聚类
  2. 新闻-事件关联 — 将 raw_news 关联到对应的 hot_event
  3. 相似事件检索 — 搜索与给定标题相似的事件（供前端"相似事件检索"接口使用）
  4. 关键词倒排索引 — 构建事件关键词倒排索引，支持快速检索

使用方式:
  from app.services.event_aggregator import aggregate_similar_events, link_news_to_events
  agg_result = aggregate_similar_events()
  link_result = link_news_to_events()

依赖:
  - app.core.database: 数据库连接管理
  - app.services.nlp_tools: SimHash 计算、汉明距离、关键词提取
================================================================================
"""

import logging
from collections import defaultdict

from app.core.database import get_connection
from app.services.nlp_tools import simhash, simhash_distance, extract_keywords
from app.services.nlp_tools import find_similar_texts, get_batch_embeddings, _load_semantic_model

logger = logging.getLogger("services.event_aggregator")


# ---------------------------------------------------------------------------
# 辅助函数：检查表是否包含指定字段
# ---------------------------------------------------------------------------
def _table_has_column(conn, table_name: str, column_name: str) -> bool:
    """
    检查数据库表中是否包含指定字段。

    参数:
        conn: 数据库连接
        table_name: 表名
        column_name: 字段名

    返回:
        True 表示该字段存在，False 表示不存在
    """
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


# ---------------------------------------------------------------------------
# 核心函数1：聚合 hot_event 中相似的事件
# ---------------------------------------------------------------------------
def aggregate_similar_events() -> dict:
    """
    聚合 hot_event 中相似的事件。

    算法:
      1. 获取所有 hot_event 的标题
      2. 计算每条标题的 SimHash 指纹
      3. 两两比较汉明距离 <= 3 的归为同一组
      4. 每组保留最新/热度最高的一条作为主事件
      5. 其余事件标记为"已聚合"（更新 hot_event 添加 merged_to 字段指向主事件）

    注意:
      - 如果 hot_event 表没有 merged_to 字段，则跳过标记步骤，仅返回聚合建议
      - 只处理标题长度 >= 2 的事件（过滤空标题）

    返回:
        聚合结果统计:
        {
            "total_events": int,       # 参与比较的事件总数
            "groups_found": int,       # 发现的相似事件组数
            "merge_suggestions": [     # 合并建议列表
                {
                    "primary_id": int,          # 主事件 ID（保留）
                    "primary_title": str,       # 主事件标题
                    "merged_ids": [int, ...],   # 待合并事件 ID 列表
                    "merged_titles": [str, ...], # 待合并事件标题列表
                },
                ...
            ]
        }
    """
    conn = get_connection()
    try:
        # 获取所有热点事件
        events = conn.execute(
            "SELECT id, title, heat_score, created_at FROM hot_event "
            "WHERE title IS NOT NULL AND length(title) >= 2 "
            "ORDER BY heat_score DESC"
        ).fetchall()

        total_events = len(events)
        if total_events == 0:
            logger.info("无热点事件数据，跳过聚合")
            return {"total_events": 0, "groups_found": 0, "merge_suggestions": []}

        # 计算每条事件的 SimHash 指纹
        event_hashes = []  # [(event_id, title, heat_score, created_at, simhash_value), ...]
        for event in events:
            h = simhash(event["title"])
            if h > 0:  # 只保留有效 SimHash 的事件
                event_hashes.append((
                    event["id"],
                    event["title"],
                    event["heat_score"],
                    event["created_at"],
                    h,
                ))

        if len(event_hashes) <= 1:
            return {"total_events": total_events, "groups_found": 0, "merge_suggestions": []}

        # 两两比较汉明距离，按距离 <= 3 聚类
        # 使用并查集思想进行分组
        n = len(event_hashes)
        parent = list(range(n))  # 并查集 parent 数组

        def find(x):
            """查找根节点（路径压缩）"""
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            """合并两个集合"""
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # 两两比较
        for i in range(n):
            for j in range(i + 1, n):
                dist = simhash_distance(event_hashes[i][4], event_hashes[j][4])
                if dist <= 3:
                    union(i, j)

        # 收集聚类组
        groups_dict = defaultdict(list)
        for i in range(n):
            groups_dict[find(i)].append(i)

        # 筛选有多个事件的组（这些是需要合并的）
        merge_suggestions = []
        for root, indices in groups_dict.items():
            if len(indices) < 2:
                continue

            # 按热度降序排列，第一个作为主事件
            indices.sort(
                key=lambda idx: (event_hashes[idx][2], event_hashes[idx][3]),
                reverse=True,
            )

            primary_idx = indices[0]
            merged_indices = indices[1:]

            primary = event_hashes[primary_idx]
            merged_events = [event_hashes[idx] for idx in merged_indices]

            merge_suggestions.append({
                "primary_id": primary[0],
                "primary_title": primary[1],
                "merged_ids": [m[0] for m in merged_events],
                "merged_titles": [m[1] for m in merged_events],
            })

        # 检查 hot_event 表是否有 merged_to 字段
        has_merged_to = _table_has_column(conn, "hot_event", "merged_to")

        if has_merged_to and merge_suggestions:
            # 尝试标记被合并的事件
            marked = 0
            for suggestion in merge_suggestions:
                primary_id = suggestion["primary_id"]
                for merged_id in suggestion["merged_ids"]:
                    try:
                        conn.execute(
                            "UPDATE hot_event SET merged_to = ? WHERE id = ?",
                            (primary_id, merged_id),
                        )
                        marked += 1
                    except Exception as e:
                        logger.debug("标记合并关系失败 (事件 %d → %d): %s", merged_id, primary_id, e)
            conn.commit()
            logger.info("已标记 %d 个事件为已聚合", marked)
        elif not has_merged_to and merge_suggestions:
            logger.info(
                "hot_event 表缺少 merged_to 字段，仅返回聚合建议，未执行标记"
            )

        logger.info(
            "事件聚合完成: 总事件 %d, 发现 %d 个相似组",
            total_events, len(merge_suggestions),
        )

        return {
            "total_events": total_events,
            "groups_found": len(merge_suggestions),
            "merge_suggestions": merge_suggestions,
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数1.5：基于语义相似度聚合事件（补充 aggregate_similar_events）
# ---------------------------------------------------------------------------
def aggregate_events_semantic(threshold: float = 0.7) -> dict:
    """
    基于语义向量相似度聚合 hot_event 中的事件。

    与 aggregate_similar_events（基于 SimHash 汉明距离）互补，
    本函数使用 sentence-transformers 模型计算标题间的语义余弦相似度，
    能捕捉 SimHash 无法识别的语义相近但用词不同的事件。

    算法:
      1. 获取所有 hot_event 的 id + title
      2. 尝试加载语义模型
      3. 如果模型可用：
         a. 对每个事件的 title，用 find_similar_texts 在其余事件中查找
            语义相似度 > threshold 的标题
         b. 按相似关系构建分组（并查集）
         c. 每组保留热度最高的一条作为主事件
      4. 如果模型不可用，fallback 到 aggregate_similar_events 的 SimHash 逻辑

    参数:
        threshold: 语义相似度阈值（0~1），默认 0.7

    返回:
        与 aggregate_similar_events 返回格式一致:
        {
            "total_events": int,
            "groups_found": int,
            "merge_suggestions": [...],
            "method": str,  # "semantic" 或 "simhash_fallback"
        }
    """
    conn = get_connection()
    try:
        # 获取所有热点事件
        events = conn.execute(
            "SELECT id, title, heat_score, created_at FROM hot_event "
            "WHERE title IS NOT NULL AND length(title) >= 2 "
            "ORDER BY heat_score DESC"
        ).fetchall()

        total_events = len(events)
        if total_events == 0:
            logger.info("无热点事件数据，跳过语义聚合")
            return {
                "total_events": 0, "groups_found": 0,
                "merge_suggestions": [], "method": "semantic",
            }

        # 尝试加载语义模型
        model = _load_semantic_model()
        if model is None:
            logger.info("语义模型不可用，fallback 到 SimHash 关键词匹配逻辑")
            result = aggregate_similar_events()
            result["method"] = "simhash_fallback"
            return result

        # 构建标题列表和 id 映射
        event_ids = [e["id"] for e in events]
        event_titles = [e["title"] for e in events]
        event_map = {e["id"]: e for e in events}  # id -> event row

        # 对每个事件，查找语义相似的其他事件
        # 用并查集管理分组
        n = len(events)
        parent = list(range(n))
        id_to_idx = {eids: i for i, eids in enumerate(event_ids)}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # 逐个事件进行语义匹配
        for i, title in enumerate(event_titles):
            # find_similar_texts 中 candidate_texts 会排除自身
            candidates = event_titles[:i] + event_titles[i + 1:]
            if not candidates:
                continue

            similar_results = find_similar_texts(
                title, candidates, topk=len(candidates), threshold=threshold
            )

            for result in similar_results:
                # result["index"] 是在 candidates 中的索引
                # 需要映射回原始事件列表的索引
                cand_idx = result["index"]
                # candidates 由 [0..i-1] + [i+1..n-1] 组成
                if cand_idx < i:
                    original_idx = cand_idx
                else:
                    original_idx = cand_idx + 1  # 跳过了 i 本身
                union(i, original_idx)

        # 收集聚类组
        groups_dict = defaultdict(list)
        for i in range(n):
            groups_dict[find(i)].append(i)

        # 筛选有多个事件的组
        merge_suggestions = []
        for root, indices in groups_dict.items():
            if len(indices) < 2:
                continue

            # 按热度降序，第一个作为主事件
            indices.sort(
                key=lambda idx: (events[idx][2], events[idx][3]),
                reverse=True,
            )

            primary_idx = indices[0]
            merged_indices = indices[1:]

            primary = events[primary_idx]
            merged_events = [events[idx] for idx in merged_indices]

            merge_suggestions.append({
                "primary_id": primary["id"],
                "primary_title": primary["title"],
                "merged_ids": [m["id"] for m in merged_events],
                "merged_titles": [m["title"] for m in merged_events],
            })

        # 尝试标记 merged_to（与 aggregate_similar_events 逻辑一致）
        has_merged_to = _table_has_column(conn, "hot_event", "merged_to")
        if has_merged_to and merge_suggestions:
            marked = 0
            for suggestion in merge_suggestions:
                primary_id = suggestion["primary_id"]
                for merged_id in suggestion["merged_ids"]:
                    try:
                        conn.execute(
                            "UPDATE hot_event SET merged_to = ? WHERE id = ?",
                            (primary_id, merged_id),
                        )
                        marked += 1
                    except Exception as e:
                        logger.debug(
                            "语义聚合标记合并关系失败 (事件 %d → %d): %s",
                            merged_id, primary_id, e,
                        )
            conn.commit()
            logger.info("语义聚合已标记 %d 个事件为已聚合", marked)

        logger.info(
            "语义事件聚合完成: 总事件 %d, 发现 %d 个相似组, 方法=semantic",
            total_events, len(merge_suggestions),
        )

        return {
            "total_events": total_events,
            "groups_found": len(merge_suggestions),
            "merge_suggestions": merge_suggestions,
            "method": "semantic",
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数2：将 raw_news 关联到对应的 hot_event
# ---------------------------------------------------------------------------
def link_news_to_events() -> dict:
    """
    将 raw_news 关联到对应的 hot_event。

    算法:
      1. 获取所有 hot_event 的标题和关键词
      2. 对每条 raw_news（未关联的）:
         a. 计算其标题与所有 hot_event 标题的 SimHash 距离
         b. 距离最近的且 <= 5 的，关联到该事件
      3. 在 raw_news 表中添加 event_id 字段（如果字段存在则更新）

    注意:
      - 检查 raw_news 表是否有 event_id 字段，如果没有则跳过写入
      - 只处理 event_id 为 NULL 的新闻（避免重复关联）

    返回:
        关联结果统计:
        {
            "linked": int,      # 成功关联的新闻数
            "unlinked": int,    # 未找到匹配事件的新闻数
        }
    """
    conn = get_connection()
    try:
        # 检查 raw_news 是否有 event_id 字段
        has_event_id = _table_has_column(conn, "raw_news", "event_id")

        if not has_event_id:
            logger.info("raw_news 表缺少 event_id 字段，跳过关联写入")
            # 仍然进行匹配统计，但只返回计数
            events = conn.execute(
                "SELECT id, title FROM hot_event WHERE title IS NOT NULL AND length(title) >= 2"
            ).fetchall()

            if not events:
                return {"linked": 0, "unlinked": 0}

            event_hashes = [(e["id"], e["title"], simhash(e["title"])) for e in events if simhash(e["title"]) > 0]
            if not event_hashes:
                return {"linked": 0, "unlinked": 0}

            # 获取所有新闻
            news_rows = conn.execute(
                "SELECT id, title FROM raw_news WHERE title IS NOT NULL AND length(title) >= 2"
            ).fetchall()

            linked = 0
            unlinked = 0
            for news in news_rows:
                news_hash = simhash(news["title"])
                if news_hash == 0:
                    unlinked += 1
                    continue

                best_dist = 999
                for eid, etitle, ehash in event_hashes:
                    dist = simhash_distance(news_hash, ehash)
                    if dist < best_dist:
                        best_dist = dist

                if best_dist <= 5:
                    linked += 1
                else:
                    unlinked += 1

            return {"linked": linked, "unlinked": unlinked}

        # event_id 字段存在，执行关联写入
        # 获取所有热点事件的 SimHash
        events = conn.execute(
            "SELECT id, title FROM hot_event WHERE title IS NOT NULL AND length(title) >= 2"
        ).fetchall()

        if not events:
            logger.info("无热点事件，跳过关联")
            return {"linked": 0, "unlinked": 0}

        event_hashes = [(e["id"], e["title"], simhash(e["title"])) for e in events if simhash(e["title"]) > 0]
        if not event_hashes:
            return {"linked": 0, "unlinked": 0}

        # 获取未关联的新闻（event_id IS NULL）
        news_rows = conn.execute(
            "SELECT id, title FROM raw_news "
            "WHERE title IS NOT NULL AND length(title) >= 2 "
            "AND event_id IS NULL"
        ).fetchall()

        linked = 0
        unlinked = 0

        for news in news_rows:
            news_hash = simhash(news["title"])
            if news_hash == 0:
                unlinked += 1
                continue

            # 找到距离最近的事件
            best_dist = 999
            best_event_id = None

            for eid, etitle, ehash in event_hashes:
                dist = simhash_distance(news_hash, ehash)
                if dist < best_dist:
                    best_dist = dist
                    best_event_id = eid

            # 距离 <= 5 则关联
            if best_dist <= 5 and best_event_id is not None:
                conn.execute(
                    "UPDATE raw_news SET event_id = ? WHERE id = ?",
                    (best_event_id, news["id"]),
                )
                linked += 1
            else:
                unlinked += 1

        conn.commit()
        logger.info(
            "新闻-事件关联完成: 关联 %d 条, 未关联 %d 条",
            linked, unlinked,
        )

        return {"linked": linked, "unlinked": unlinked}

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数3：搜索相似事件
# ---------------------------------------------------------------------------
def search_similar_events(title: str, topk: int = 5) -> list:
    """
    搜索与给定标题相似的事件（用于前端"相似事件检索"接口）。

    算法:
      1. 计算输入标题的 SimHash
      2. 获取所有 hot_event 标题的 SimHash
      3. 按汉明距离排序，返回最近的 topk 个

    参数:
        title: 待搜索的标题文本
        topk: 返回的最大结果数

    返回:
        相似事件列表（按距离从小到大排序）:
        [{
            "event_id": int,      # 事件 ID
            "title": str,          # 事件标题
            "distance": int,       # SimHash 汉明距离（越小越相似）
            "heat_score": float,   # 热度分数
        }, ...]
    """
    if not title or not title.strip():
        return []

    conn = get_connection()
    try:
        # 计算输入标题的 SimHash
        input_hash = simhash(title)
        if input_hash == 0:
            logger.debug("输入标题 SimHash 计算结果为 0，无法匹配")
            return []

        # 获取所有热点事件
        events = conn.execute(
            "SELECT id, title, heat_score FROM hot_event "
            "WHERE title IS NOT NULL AND length(title) >= 2"
        ).fetchall()

        # 计算每个事件的 SimHash 和汉明距离
        candidates = []
        for event in events:
            event_hash = simhash(event["title"])
            if event_hash == 0:
                continue
            dist = simhash_distance(input_hash, event_hash)
            candidates.append({
                "event_id": event["id"],
                "title": event["title"],
                "distance": dist,
                "heat_score": event["heat_score"],
            })

        # 按汉明距离排序，取 topk
        candidates.sort(key=lambda x: x["distance"])
        result = candidates[:topk]

        logger.debug("相似事件检索: 输入='%s', 候选=%d, 返回=%d", title[:30], len(candidates), len(result))
        return result

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数4：构建事件关键词倒排索引
# ---------------------------------------------------------------------------
def build_event_keyword_index() -> dict:
    """
    构建事件关键词倒排索引，用于快速检索。

    算法:
      1. 获取所有 hot_event 的标题
      2. 对每个标题提取关键词
      3. 构建关键词 → 事件 ID 列表的倒排映射

    返回:
        倒排索引字典:
        {
            "关键词1": [event_id_1, event_id_2, ...],
            "关键词2": [event_id_3, ...],
            ...
        }

    使用示例:
        index = build_event_keyword_index()
        # 搜索包含"人工智能"的事件
        ai_event_ids = index.get("人工智能", [])
    """
    conn = get_connection()
    try:
        events = conn.execute(
            "SELECT id, title FROM hot_event "
            "WHERE title IS NOT NULL AND length(title) >= 2"
        ).fetchall()

        # 构建倒排索引: keyword → [event_id_1, event_id_2, ...]
        index = defaultdict(list)

        for event in events:
            kw_tuples = extract_keywords(event["title"], topk=5)
            keywords = [kw for kw, _ in kw_tuples] if kw_tuples else []
            for kw in keywords:
                # 去重：同一事件不重复添加
                if event["id"] not in index[kw]:
                    index[kw].append(event["id"])

        logger.info(
            "关键词倒排索引构建完成: %d 个事件, %d 个关键词",
            len(events), len(index),
        )

        return dict(index)

    finally:
        conn.close()
