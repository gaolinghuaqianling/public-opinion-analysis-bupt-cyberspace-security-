# -*- coding: utf-8 -*-
"""
事件处理核心模块
==========================================================
串联: raw_news → 内容分析 → 情感分析 → hot_event → event_analysis
负责将原始新闻数据经过 NLP 分析后，聚合为事件维度的综合分析结果。
==========================================================
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Optional

from app.core.database import get_connection
from app.services.nlp_tools import (
    segment_text,
    extract_keywords,
    extract_main_content,
    is_similar_text,
)
from app.services.sentiment_analyzer import compute_event_sentiment

logger = logging.getLogger("services.event_processor")


# ===================================================================
# 1. 处理新入库新闻
# ===================================================================

def process_new_news(platform: str = "", time_window_minutes: int = 5) -> Dict:
    """
    处理最近入库的 raw_news，完成: 分词 → 关键词提取 → 情感分析 → 写入分析结果。

    流程:
        1. 查询最近 N 分钟内入库且状态为 "pending" 的 raw_news
           （可按平台过滤）
        2. 对每条新闻执行以下分析:
           a. 用 nlp_tools.segment_text 分词
           b. 用 nlp_tools.extract_keywords 提取关键词 (TF-IDF, top 10)
           c. 用 sentiment_analyzer.analyze_sentiment 计算情感分值
           d. 将分析结果以 JSON 格式写入 raw_news 的扩展字段
        3. 将新闻状态更新为 "analyzed"
        4. 返回处理统计信息

    参数:
        platform:            平台过滤（可选，为空则处理所有平台）
        time_window_minutes: 时间窗口（分钟），默认处理最近 5 分钟入库的新闻

    返回:
        包含以下键的字典:
            - processed:          int, 成功处理的新闻条数
            - keywords_extracted: int, 成功提取关键词的条数
            - sentiment_scored:    int, 成功计算情感分值的条数

    示例:
        >>> process_new_news(platform="微博", time_window_minutes=10)
        {'processed': 15, 'keywords_extracted': 15, 'sentiment_scored': 14}
    """
    stats = {
        "processed": 0,
        "keywords_extracted": 0,
        "sentiment_scored": 0,
    }

    conn = get_connection()
    try:
        # 构建查询条件: 查询最近 N 分钟内入库的 pending 状态新闻
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if platform:
            rows = conn.execute(
                "SELECT * FROM raw_news "
                "WHERE status = 'pending' "
                "  AND source_platform = ? "
                "  AND crawled_at >= datetime(?, ? || ' minutes') "
                "ORDER BY crawled_at ASC",
                (platform, now, str(-time_window_minutes)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM raw_news "
                "WHERE status = 'pending' "
                "  AND crawled_at >= datetime(?, ? || ' minutes') "
                "ORDER BY crawled_at ASC",
                (now, str(-time_window_minutes)),
            ).fetchall()

        logger.info(
            "待处理新闻 %d 条 (platform=%s, window=%dmin)",
            len(rows), platform or "全部", time_window_minutes,
        )

        for row in rows:
            news = dict(row)
            news_id = news["id"]
            title = news.get("title", "")
            content = news.get("content", "")

            # 合并标题和正文作为分析文本
            full_text = title
            if content:
                full_text = f"{title} {content}"

            if not full_text.strip():
                continue

            analysis_result = {}

            # 步骤 a: 分词
            try:
                words = segment_text(full_text)
                analysis_result["words"] = words
            except Exception as e:
                logger.warning("新闻 #%d 分词失败: %s", news_id, e)
                analysis_result["words"] = []

            # 步骤 b: 关键词提取
            try:
                keywords = extract_keywords(full_text, topk=10, method="tfidf")
                analysis_result["keywords"] = [
                    {"word": kw, "weight": round(weight, 4)}
                    for kw, weight in keywords
                ]
                stats["keywords_extracted"] += 1
            except Exception as e:
                logger.warning("新闻 #%d 关键词提取失败: %s", news_id, e)
                analysis_result["keywords"] = []

            # 步骤 c: 情感分析
            try:
                from app.services.sentiment_analyzer import analyze_sentiment
                sentiment = analyze_sentiment(full_text)
                analysis_result["sentiment"] = sentiment
                stats["sentiment_scored"] += 1
            except Exception as e:
                logger.warning("新闻 #%d 情感分析失败: %s", news_id, e)
                analysis_result["sentiment"] = {
                    "score": 0.5,
                    "sentiment": "neutral",
                }

            # 步骤 d: 将分析结果写入数据库
            try:
                analysis_json = json.dumps(
                    analysis_result, ensure_ascii=False
                )
                conn.execute(
                    "UPDATE raw_news SET status = 'analyzed', "
                    "content = CASE WHEN content IS NULL OR content = '' "
                    "  THEN ? ELSE content END "
                    "WHERE id = ?",
                    (analysis_json, news_id),
                )

                # 尝试写入 analysis_result 字段（如果表结构支持）
                try:
                    conn.execute(
                        "UPDATE raw_news SET analysis_result = ? WHERE id = ?",
                        (analysis_json, news_id),
                    )
                except Exception:
                    # 表结构可能没有 analysis_result 字段，忽略该错误
                    pass

                stats["processed"] += 1

            except Exception as e:
                logger.warning("新闻 #%d 写入分析结果失败: %s", news_id, e)

        conn.commit()

        logger.info(
            "新闻处理完成: processed=%d, keywords=%d, sentiment=%d",
            stats["processed"],
            stats["keywords_extracted"],
            stats["sentiment_scored"],
        )

    except Exception as e:
        logger.error("处理新新闻异常: %s", e)
        conn.rollback()
    finally:
        conn.close()

    return stats


# ===================================================================
# 2. 创建/更新事件分析
# ===================================================================

def create_event_analysis(
    event_id: int,
    news_texts: List[str] = None
) -> Dict:
    """
    为指定事件创建或更新 event_analysis 记录。

    流程:
        1. 如果提供了 news_texts，直接使用该文本列表进行分析
        2. 否则从 raw_news 中查找与该事件关联的新闻文本:
           a. 查询 hot_event 表获取事件标题
           b. 用 get_related_news_for_event 查找相关新闻
        3. 综合计算:
           - 情感比例 (positive_ratio, negative_ratio, neutral_ratio)
           - 高频关键词 (top 15 关键词，从所有关联新闻中汇总)
           - 平台覆盖 (各平台报道数量占比)
           - 分析时间
        4. 写入/更新 event_analysis 表（使用 INSERT OR REPLACE）

    参数:
        event_id:    热点事件的 ID（对应 hot_event.id）
        news_texts:  可选，直接传入事件关联的新闻文本列表。
                     如果为 None，则自动从数据库中查找关联新闻。

    返回:
        包含以下键的字典:
            - event_id:        int,   事件 ID
            - positive_ratio:  float, 正面情感比例
            - negative_ratio:  float, 负面情感比例
            - neutral_ratio:   float, 中立情感比例
            - high_freq_keywords: list, 高频关键词列表
            - platform_coverage: dict, 平台覆盖分布
            - analyzed_at:     str,   分析时间

    示例:
        >>> create_event_analysis(event_id=1)
        {'event_id': 1, 'positive_ratio': 0.6, 'negative_ratio': 0.3,
         'neutral_ratio': 0.1, 'high_freq_keywords': ['关键词1', ...],
         'platform_coverage': {'微博': 0.5, '人民网': 0.5}, ...}
    """
    conn = get_connection()
    try:
        # 步骤1: 获取关联新闻文本
        related_news = []
        if news_texts is not None:
            related_news = news_texts
        else:
            # 从数据库查找关联新闻
            related_news_list = get_related_news_for_event(event_id)
            if related_news_list:
                related_news = []
                for news in related_news_list:
                    text = news.get("title", "")
                    content = news.get("content", "")
                    if content:
                        text = f"{text} {content}"
                    if text.strip():
                        related_news.append(text)

        if not related_news:
            logger.warning("事件 #%d 没有关联新闻，无法分析", event_id)
            return {
                "event_id": event_id,
                "positive_ratio": 0.0,
                "negative_ratio": 0.0,
                "neutral_ratio": 0.0,
                "high_freq_keywords": [],
                "platform_coverage": {},
                "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": "无关联新闻",
            }

        # 步骤2: 计算情感比例
        sentiment_result = compute_event_sentiment(related_news)

        # 步骤3: 计算高频关键词（汇总所有新闻的关键词，取 top 15）
        all_keywords = []
        for text in related_news:
            try:
                kws = extract_keywords(text, topk=10, method="tfidf")
                all_keywords.extend([kw for kw, weight in kws])
            except Exception as e:
                logger.debug("关键词提取失败: %s", e)

        # 统计词频，取 top 15
        from collections import Counter
        keyword_counter = Counter(all_keywords)
        high_freq_keywords = [
            word for word, count in keyword_counter.most_common(15)
        ]

        # 步骤4: 计算平台覆盖
        if news_texts is None:
            # 从数据库获取的新闻列表中有平台信息
            related_news_list = get_related_news_for_event(event_id)
            platform_coverage = compute_platform_coverage(related_news_list)
        else:
            platform_coverage = {}

        # 步骤5: 写入/更新 event_analysis 表
        analyzed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        keywords_json = json.dumps(high_freq_keywords, ensure_ascii=False)
        platform_json = json.dumps(platform_coverage, ensure_ascii=False)

        # 使用 INSERT OR REPLACE 实现创建或更新
        conn.execute(
            "INSERT OR REPLACE INTO event_analysis "
            "(event_id, positive_ratio, negative_ratio, neutral_ratio, "
            " high_freq_keywords, platform_coverage, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                sentiment_result["positive_ratio"],
                sentiment_result["negative_ratio"],
                sentiment_result["neutral_ratio"],
                keywords_json,
                platform_json,
                analyzed_at,
            ),
        )
        conn.commit()

        logger.info(
            "事件 #%d 分析完成: positive=%.2f, negative=%.2f, neutral=%.2f",
            event_id,
            sentiment_result["positive_ratio"],
            sentiment_result["negative_ratio"],
            sentiment_result["neutral_ratio"],
        )

        return {
            "event_id": event_id,
            "positive_ratio": sentiment_result["positive_ratio"],
            "negative_ratio": sentiment_result["negative_ratio"],
            "neutral_ratio": sentiment_result["neutral_ratio"],
            "avg_score": sentiment_result["avg_score"],
            "high_freq_keywords": high_freq_keywords,
            "platform_coverage": platform_coverage,
            "analyzed_at": analyzed_at,
            "analyzed_count": sentiment_result["analyzed_count"],
        }

    except Exception as e:
        logger.error("事件分析失败 (event_id=%d): %s", event_id, e)
        conn.rollback()
        return {
            "event_id": event_id,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 0.0,
            "high_freq_keywords": [],
            "platform_coverage": {},
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error": str(e),
        }
    finally:
        conn.close()


# ===================================================================
# 3. 查找与事件相关的新闻
# ===================================================================

def get_related_news_for_event(event_title: str, limit: int = 50) -> List[Dict]:
    """
    查找与事件标题相关的 raw_news（基于标题关键词匹配）。

    匹配策略:
        1. 从事件标题中提取关键词（长度 >= 2 的有效词）
        2. 在 raw_news 表中查找标题包含任意关键词的新闻
        3. 按 crawled_at 降序排列，限制返回数量

    如果传入的是整数类型的 event_id，则先从 hot_event 表获取事件标题。

    参数:
        event_title: 事件标题（或事件 ID，如果是 int 类型则自动查标题）
        limit:       最大返回数量，默认 50

    返回:
        相关新闻的字典列表，每个字典包含 raw_news 表的全部列

    示例:
        >>> get_related_news_for_event("人工智能发展大会")
        [{'id': 1, 'title': '...', 'content': '...', ...}, ...]
    """
    # 兼容传入 event_id 的情况（整数）
    if isinstance(event_title, int):
        event_id = event_title
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT title FROM hot_event WHERE id = ?", (event_id,)
            ).fetchone()
            if row:
                event_title = row["title"]
            else:
                logger.warning("事件 #%d 不存在", event_id)
                return []
        finally:
            conn.close()

    if not event_title or not event_title.strip():
        return []

    # 从事件标题中提取关键词
    keywords = segment_text(event_title)
    if not keywords:
        # 如果分词无结果，直接使用标题全文进行匹配
        keywords = [event_title.strip()]

    conn = get_connection()
    try:
        # 构建 SQL LIKE 条件: 标题包含任意关键词
        # 使用 OR 连接多个 LIKE 条件
        conditions = []
        params = []
        for kw in keywords[:10]:  # 最多使用前 10 个关键词，避免 SQL 过长
            conditions.append("title LIKE ?")
            params.append(f"%{kw}%")

        if not conditions:
            return []

        where_clause = " OR ".join(conditions)
        params.append(limit)

        sql = (
            "SELECT * FROM raw_news "
            f"WHERE ({where_clause}) "
            "ORDER BY crawled_at DESC "
            "LIMIT ?"
        )

        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    except Exception as e:
        logger.error("查找相关新闻失败 (event='%s'): %s", event_title[:50], e)
        return []
    finally:
        conn.close()


# ===================================================================
# 4. 计算平台覆盖分布
# ===================================================================

def compute_platform_coverage(news_list: List[Dict]) -> Dict:
    """
    计算一组新闻的平台覆盖分布。

    统计每条新闻的 source_platform 字段，计算各平台的报道数量占比。

    参数:
        news_list: 新闻字典列表，每个字典需包含 "source_platform" 字段
                   （即 raw_news 表的行字典）

    返回:
        平台覆盖分布字典，格式为 {"平台名": 占比float, ...}
        占比总和为 1.0

    示例:
        >>> compute_platform_coverage([
        ...     {"source_platform": "微博"},
        ...     {"source_platform": "微博"},
        ...     {"source_platform": "人民网"},
        ... ])
        {'微博': 0.6667, '人民网': 0.3333}
    """
    if not news_list:
        return {}

    # 统计各平台新闻数量
    platform_counts = {}
    total = 0

    for news in news_list:
        platform = news.get("source_platform", "")
        if not platform:
            platform = "未知"

        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        total += 1

    if total == 0:
        return {}

    # 计算占比，保留 4 位小数
    coverage = {}
    for platform, count in platform_counts.items():
        ratio = round(count / total, 4)
        coverage[platform] = ratio

    return coverage
