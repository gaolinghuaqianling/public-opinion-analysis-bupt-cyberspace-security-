# -*- coding: utf-8 -*-
"""
================================================================================
  热点事件自动发现模块 (hotspot_detector.py)
================================================================================
基于机器学习聚类算法和报道数量统计，自动从 raw_news 中发现新的热点事件。

核心算法:
  1. 查询指定时间窗口内的原始新闻
  2. 使用 Sentence-BERT 语义模型将每条新闻编码为 768 维向量
  3. 使用 DBSCAN 密度聚类算法对新闻向量进行聚类（无需预设簇数）
  4. 每组包含 >= min_news_count 条新闻的聚类识别为一个热点事件
  5. 用 TF-IDF 提取每组核心关键词作为事件标题
  6. 自动写入 hot_event 表，并创建初始 event_analysis 记录

机器学习组件:
  - Sentence-BERT (shibing624/text2vec-base-chinese): 语义特征提取
  - DBSCAN (scikit-learn): 基于密度的空间聚类
  - TF-IDF (jieba.analyse): 关键词特征表示

使用方式:
  from app.services.hotspot_detector import run_hotspot_detection
  result = run_hotspot_detection(time_window_hours=24, min_news_count=3)

依赖:
  - app.core.database: 数据库连接管理
  - app.services.nlp_tools: NLP 基础工具（语义向量、关键词提取、相似度判断）
================================================================================
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.core.database import get_connection
from app.services.nlp_tools import extract_keywords, segment_text, is_similar_text, get_batch_embeddings, _load_semantic_model

logger = logging.getLogger("services.hotspot_detector")


# ---------------------------------------------------------------------------
# 并查集(Union-Find)数据结构
# ---------------------------------------------------------------------------
class UnionFind:
    """
    并查集（Union-Find / Disjoint Set），用于高效地将共享关键词的新闻聚类。

    支持:
      - find(x): 查找 x 的根节点（带路径压缩）
      - union(x, y): 合并 x 和 y 所在的集合（按秩合并）
      - get_groups(): 返回所有集合（按根节点分组）

    时间复杂度接近 O(1)（反阿克曼函数）
    """

    def __init__(self, n: int):
        """
        初始化并查集。

        参数:
            n: 元素数量（每条新闻对应一个元素）
        """
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        """查找 x 的根节点，带路径压缩优化"""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # 路径压缩
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        """合并 x 和 y 所在的集合，按秩合并"""
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x == root_y:
            return

        # 按秩合并：将矮树挂到高树上
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1

    def get_groups(self) -> list:
        """
        获取所有聚类分组。

        返回:
            列表的列表，每个子列表包含同一组内的元素索引
        """
        groups = defaultdict(list)
        for i in range(len(self.parent)):
            groups[self.find(i)].append(i)
        return list(groups.values())


# ---------------------------------------------------------------------------
# 核心函数：基于 DBSCAN 机器学习聚类对新闻进行分组
# ---------------------------------------------------------------------------
def cluster_news_by_keywords(news_list: list) -> list:
    """
    基于语义向量 + DBSCAN 密度聚类对新闻进行分组。

    机器学习流程:
      1. 将每条新闻的标题+正文拼接，通过 Sentence-BERT 编码为 768 维语义向量
      2. 使用 DBSCAN 算法对向量矩阵进行密度聚类（无需预设簇数）
      3. eps=0.5 控制聚类半径，min_samples=2 控制最小簇大小

    参数:
        news_list: 新闻字典列表，每条需包含 "title" 和 "content" 字段

    返回:
        聚类结果列表，每个元素是同组新闻在 news_list 中的索引列表
        例如: [[0, 3, 7], [1, 5], [2, 4, 6, 8]]
    """
    if not news_list:
        return []

    n = len(news_list)

    # 尝试使用语义模型进行 ML 聚类
    model = _load_semantic_model()
    if model is not None:
        try:
            return _cluster_by_dbscan(news_list, model)
        except Exception as e:
            logger.warning("DBSCAN 聚类失败，降级到关键词聚类: %s", e)

    # Fallback: 关键词共现 + 并查集
    logger.info("语义模型不可用，使用关键词共现聚类（降级模式）")
    return _cluster_by_keywords_fallback(news_list)


def _cluster_by_dbscan(news_list: list, model) -> list:
    """
    使用 DBSCAN 密度聚类算法对新闻进行分组。

    DBSCAN (Density-Based Spatial Clustering of Applications with Noise):
      - 基于密度的空间聚类算法，无需预设簇数量
      - 能自动发现任意形状的簇
      - 自动识别噪声点（不属于任何簇的点）

    参数:
        news_list: 新闻字典列表
        model: 已加载的 SentenceTransformer 模型

    返回:
        聚类结果列表
    """
    from sklearn.cluster import DBSCAN
    import numpy as np

    n = len(news_list)

    # Step 1: 提取文本并编码为语义向量
    texts = []
    for news in news_list:
        title = news.get("title") or ""
        content = (news.get("content") or "")[:200]
        texts.append(f"{title} {content}")

    logger.info("正在对 %d 条新闻进行语义编码...", n)
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)

    # Step 2: DBSCAN 聚类
    # eps=0.5: 两点之间的最大距离（余弦相似度约 0.5）
    # min_samples=2: 形成簇的最小点数
    clustering = DBSCAN(
        eps=0.5,
        min_samples=2,
        metric="cosine",
    ).fit(embeddings)

    labels = clustering.labels_

    # Step 3: 按 label 分组（label=-1 是噪声点，单独成组）
    groups = defaultdict(list)
    for idx, label in enumerate(labels):
        groups[int(label)].append(idx)

    result = list(groups.values())
    logger.info(
        "DBSCAN 聚类完成: %d 条新闻 → %d 个簇 (含 %d 个噪声点)",
        n, len(result), len(groups.get(-1, [])),
    )
    return result


def _cluster_by_keywords_fallback(news_list: list) -> list:
    """
    关键词共现聚类的降级方案（当语义模型不可用时使用）。

    算法:
      1. 对每条新闻提取 TF-IDF 关键词
      2. 构建关键词倒排索引
      3. 共享关键词 >= 2 的新闻使用并查集归为一组
    """
    n = len(news_list)

    # 提取关键词
    news_keywords = []
    for news in news_list:
        text = (news.get("title") or "") + " " + (news.get("content") or "")
        kw_tuples = extract_keywords(text, topk=5)
        keywords = [kw for kw, _ in kw_tuples] if kw_tuples else []
        news_keywords.append(set(keywords))

    # 构建倒排索引
    keyword_index = defaultdict(set)
    for idx, kws in enumerate(news_keywords):
        for kw in kws:
            keyword_index[kw].add(idx)

    # 统计共享关键词
    shared_count = defaultdict(int)
    for kw, news_indices in keyword_index.items():
        indices_list = list(news_indices)
        for a in range(len(indices_list)):
            for b in range(a + 1, len(indices_list)):
                i, j = indices_list[a], indices_list[b]
                if i > j:
                    i, j = j, i
                shared_count[(i, j)] += 1

    # 并查集合并
    uf = UnionFind(n)
    for (i, j), count in shared_count.items():
        if count >= 2:
            uf.union(i, j)

    groups = uf.get_groups()
    logger.debug("关键词聚类完成(降级): %d 条新闻 → %d 个聚类", n, len(groups))
    return groups


# ---------------------------------------------------------------------------
# 核心函数：自动发现热点事件
# ---------------------------------------------------------------------------
def detect_hotspots(min_news_count: int = 3, time_window_hours: int = 24) -> list:
    """
    自动发现热点事件。

    机器学习流程:
      1. 查询最近 time_window_hours 小时内的 raw_news
      2. 使用 Sentence-BERT 将每条新闻编码为 768 维语义向量
      3. 使用 DBSCAN 密度聚类对新闻向量分组（无需预设簇数）
      4. 每组如果包含 >= min_news_count 条新闻，识别为一个热点事件
      5. 用 TF-IDF 提取每组核心关键词作为事件标题
      6. 按新闻数量计算 heat_score

    参数:
        min_news_count: 最少关联新闻数，低于此值的聚类不算热点
        time_window_hours: 时间窗口（小时），只分析该时间段内的新闻

    返回:
        热点事件字典列表:
        [{
            "title": str,           # 事件标题（核心关键词组合）
            "news_count": int,      # 关联新闻数
            "heat_score": float,    # 热度分
            "keywords": list,       # 核心关键词
            "sample_titles": list,  # 样本新闻标题（最多5条）
            "news_ids": list,       # 关联的 raw_news id 列表
        }]
    """
    conn = get_connection()
    try:
        # 计算时间窗口的起止时间
        now = datetime.now()
        cutoff = (now - timedelta(hours=time_window_hours)).strftime("%Y-%m-%d %H:%M:%S")
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 查询时间窗口内的新闻
        rows = conn.execute(
            "SELECT id, title, content, source_platform, published_at "
            "FROM raw_news "
            "WHERE crawled_at >= ? AND crawled_at <= ? "
            "ORDER BY crawled_at DESC",
            (cutoff, now_str),
        ).fetchall()

        if not rows:
            logger.info("最近 %d 小时内无新闻数据", time_window_hours)
            return []

        # 转换为字典列表
        news_list = [dict(row) for row in rows]
        logger.info("时间窗口内有 %d 条新闻，开始聚类分析", len(news_list))

        # 关键词聚类
        clusters = cluster_news_by_keywords(news_list)

        # 筛选满足条件的聚类（新闻数 >= min_news_count）
        hotspots = []
        for cluster_indices in clusters:
            if len(cluster_indices) < min_news_count:
                continue

            # 提取该聚类中所有新闻的关键词
            all_keywords = []
            for idx in cluster_indices:
                news = news_list[idx]
                text = (news.get("title") or "") + " " + (news.get("content") or "")
                kw_tuples = extract_keywords(text, topk=5)
                all_keywords.extend([kw for kw, _ in kw_tuples])

            # 统计关键词频率，取 top 3 作为事件标题关键词
            keyword_freq = Counter(all_keywords)
            top_keywords = [kw for kw, _ in keyword_freq.most_common(3)]

            # 生成事件标题（关键词用空格连接）
            title = " ".join(top_keywords) if top_keywords else "未知热点"

            # 收集关联数据
            news_ids = [news_list[idx]["id"] for idx in cluster_indices]
            sample_titles = [
                news_list[idx]["title"]
                for idx in cluster_indices[:5]
                if news_list[idx].get("title")
            ]

            # 计算 heat_score：新闻数量 × 10，上限 100
            heat_score = min(100.0, len(cluster_indices) * 10)

            hotspots.append({
                "title": title,
                "news_count": len(cluster_indices),
                "heat_score": heat_score,
                "keywords": top_keywords,
                "sample_titles": sample_titles,
                "news_ids": news_ids,
            })

        # 按热度降序排序
        hotspots.sort(key=lambda x: x["heat_score"], reverse=True)
        logger.info("发现 %d 个热点事件（阈值: %d 条新闻）", len(hotspots), min_news_count)
        return hotspots

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 将热点写入数据库
# ---------------------------------------------------------------------------
def promote_hotspots_to_events(hotspots: list) -> int:
    """
    将发现的热点事件写入 hot_event 表。

    规则:
      1. 检查 hot_event 是否已存在类似标题（用 is_similar_text，阈值=3）
      2. 不存在则插入新记录
      3. 更新 heat_score = news_count * 10
      4. lifecycle = "growth"（默认）
      5. risk_level = "low"（默认）
      6. summary = 取第一条相关新闻的 content 前 200 字

    参数:
        hotspots: detect_hotspots() 返回的热点事件列表

    返回:
        新增的事件数量
    """
    if not hotspots:
        return 0

    conn = get_connection()
    try:
        promoted = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for hotspot in hotspots:
            title = hotspot["title"]
            news_ids = hotspot["news_ids"]

            # 去重：检查 hot_event 中是否已存在类似标题
            existing_events = conn.execute(
                "SELECT id, title FROM hot_event"
            ).fetchall()

            is_duplicate = False
            for existing in existing_events:
                if is_similar_text(title, existing["title"], threshold=3):
                    logger.debug(
                        "热点已存在，跳过: [%s] ~ [%s]",
                        title[:30], existing["title"][:30],
                    )
                    is_duplicate = True
                    break

            if is_duplicate:
                continue

            # 获取第一条相关新闻的 content 作为摘要
            summary = ""
            if news_ids:
                first_news = conn.execute(
                    "SELECT content FROM raw_news WHERE id = ?",
                    (news_ids[0],),
                ).fetchone()
                if first_news and first_news["content"]:
                    summary = first_news["content"][:200].strip()

            # 计算热度分数
            heat_score = min(100.0, hotspot["news_count"] * 10)

            # 写入 hot_event 表
            conn.execute(
                "INSERT INTO hot_event (title, heat_score, risk_level, summary, lifecycle, created_at, updated_at) "
                "VALUES (?, ?, 'low', ?, 'growth', ?, ?)",
                (title, heat_score, summary, now_str, now_str),
            )
            promoted += 1

        conn.commit()
        logger.info("成功写入 %d 个热点事件到 hot_event 表", promoted)
        return promoted

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 完整流程入口
# ---------------------------------------------------------------------------
def run_hotspot_detection(time_window_hours: int = 24, min_news_count: int = 3) -> dict:
    """
    执行完整的热点发现流程：检测 → 写入 hot_event → 创建 event_analysis。

    流程:
      1. 调用 detect_hotspots() 从 raw_news 中发现热点
      2. 调用 promote_hotspots_to_events() 将热点写入 hot_event
      3. 查询当前 hot_event 总数

    参数:
        time_window_hours: 时间窗口（小时）
        min_news_count: 最少关联新闻数阈值

    返回:
        执行结果统计:
        {
            "detected": int,    # 检测到的热点数量
            "promoted": int,    # 成功写入的事件数量
            "total_events": int, # 当前数据库中热点事件总数
        }
    """
    # 第一步：自动发现热点
    hotspots = detect_hotspots(
        min_news_count=min_news_count,
        time_window_hours=time_window_hours,
    )
    detected = len(hotspots)

    # 第二步：写入 hot_event 表
    promoted = promote_hotspots_to_events(hotspots)

    # 第三步：查询事件总数
    total_events = 0
    conn = get_connection()
    try:
        total_events = conn.execute("SELECT COUNT(*) FROM hot_event").fetchone()[0]
    finally:
        conn.close()

    logger.info(
        "热点发现完成: 检测 %d 个, 写入 %d 个, 事件总数 %d",
        detected, promoted, total_events,
    )

    return {
        "detected": detected,
        "promoted": promoted,
        "total_events": total_events,
    }
