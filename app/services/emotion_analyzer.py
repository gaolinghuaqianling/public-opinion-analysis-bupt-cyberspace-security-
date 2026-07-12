# -*- coding: utf-8 -*-
"""
================================================================================
  舆情情绪量化分析模块 (emotion_analyzer.py)
================================================================================
对事件关联的新闻报道和传播节点逐一进行情感分析，
输出正面/中性/负面情绪占比，标注情绪激化节点，分析情绪波动诱因。

复用已有数据:
  - fake_detector / spread_analyzer 已获取的传播节点
  - sentiment_analyzer (SnowNLP) 进行情感打分
  - nlp_tools (jieba) 进行关键词提取

输出结构:
  {
    "emotion_ratios": {"positive": 0.25, "neutral": 0.50, "negative": 0.25},
    "node_emotions": [
      {"node": "标题...", "score": 0.3, "label": "负面", "is_agitated": true, "trigger_words": ["愤怒","谴责"]}
    ],
    "agitated_nodes": [{"node": "...", "cause": "..."}],
    "emotion_timeline": [{"date": "2024-03-15", "avg_score": 0.45, "dominant": "负面"}],
    "fluctuation_causes": ["3月16日情绪由中性转为负面，诱因：官方媒体报道中使用谴责性措辞"]
  }
================================================================================
"""

import json
import logging
from typing import List, Dict, Optional
from collections import defaultdict
from app.core.database import get_connection
from app.services.sentiment_analyzer import analyze_sentiment
from app.services.nlp_tools import segment_text, extract_keywords

logger = logging.getLogger("services.emotion_analyzer")


# ---------------------------------------------------------------------------
# 情绪激化关键词（命中即标记为激化节点）
# ---------------------------------------------------------------------------
AGITATION_KEYWORDS = [
    "愤怒", "怒斥", "强烈谴责", "令人发指", "丧心病狂",
    "无耻", "卑鄙", "可恶", "太过分了", "恶心",
    "彻底", "绝了", "炸了", "疯了", "崩溃",
    "不配", "活该", "渣", "垃圾", "败类",
    "震惊", "不敢相信", "天理难容", "罪有应得",
    "强烈抗议", "坚决反对", "严惩", "必须道歉",
]

# 情绪转变方向映射
EMOTION_SHIFT = {
    "up": "情绪趋于正面",
    "down": "情绪趋于负面",
    "stable": "情绪保持稳定",
}


def _classify_emotion(score: float) -> str:
    """将 0~1 情感分值映射为正面/中性/负面"""
    if score >= 0.6:
        return "正面"
    elif score >= 0.4:
        return "中性"
    else:
        return "负面"


def _find_trigger_words(text: str) -> List[str]:
    """识别文本中的情绪激化关键词"""
    found = []
    for kw in AGITATION_KEYWORDS:
        if kw in text:
            found.append(kw)
    return found


def analyze_event_emotion(event_id: int) -> Dict:
    """
    对指定事件进行舆情情绪量化分析。

    流程:
      1. 获取事件关联的所有新闻
      2. 对每条新闻进行情感分析
      3. 计算整体情绪占比
      4. 识别情绪激化节点（含激化关键词的节点）
      5. 按日期统计情绪时间线
      6. 分析情绪波动诱因

    参数:
        event_id: 事件 ID

    返回:
        情绪分析结果字典
    """
    conn = get_connection()
    try:
        # 1. 获取事件信息
        event = conn.execute(
            "SELECT * FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None

        # 2. 获取关联新闻
        news_list = _get_event_news(conn, event_id, event["title"])
        if not news_list:
            return _empty_result(event_id)

        # 3. 逐一情感分析
        node_emotions = []
        sentiment_counts = {"正面": 0, "中性": 0, "负面": 0}
        date_emotions = defaultdict(list)  # date -> [scores]

        for news in news_list:
            text = f"{news['title']} {news.get('content', '')}".strip()
            if len(text) < 5:
                text = news["title"]

            result = analyze_sentiment(text)
            score = result.get("score", 0.5)
            label = _classify_emotion(score)
            sentiment_counts[label] += 1

            # 检查情绪激化
            trigger_words = _find_trigger_words(text)
            is_agitated = len(trigger_words) >= 1

            node_emotions.append({
                "node": news["title"][:50],
                "platform": news.get("source_platform", ""),
                "published_at": news.get("published_at", ""),
                "score": round(score, 4),
                "label": label,
                "is_agitated": is_agitated,
                "trigger_words": trigger_words[:5],
            })

            # 按日期聚合
            date_str = (news.get("published_at") or "")[:10]
            if date_str:
                date_emotions[date_str].append(score)

        # 4. 计算整体占比
        total = sum(sentiment_counts.values())
        emotion_ratios = {
            k: round(v / total, 4) if total > 0 else 0.33
            for k, v in sentiment_counts.items()
        }

        # 5. 识别情绪激化节点
        agitated_nodes = []
        for ne in node_emotions:
            if ne["is_agitated"]:
                cause = _explain_agitation(ne)
                agitated_nodes.append({
                    "node": ne["node"],
                    "platform": ne["platform"],
                    "score": ne["score"],
                    "trigger_words": ne["trigger_words"],
                    "cause": cause,
                })

        # 6. 构建情绪时间线
        emotion_timeline = []
        for date in sorted(date_emotions.keys()):
            scores = date_emotions[date]
            avg_score = round(sum(scores) / len(scores), 4)
            dominant = _classify_emotion(avg_score)
            emotion_timeline.append({
                "date": date,
                "avg_score": avg_score,
                "dominant": dominant,
                "news_count": len(scores),
            })

        # 7. 分析情绪波动诱因
        fluctuation_causes = _analyze_fluctuation(emotion_timeline, node_emotions)

        result = {
            "event_id": event_id,
            "emotion_ratios": emotion_ratios,
            "node_emotions": node_emotions[:20],  # 最多返回20条
            "agitated_nodes": agitated_nodes[:5],
            "emotion_timeline": emotion_timeline,
            "fluctuation_causes": fluctuation_causes,
        }

        logger.info(
            "事件 %d 情绪分析完成: 正面%.0f%% 中性%.0f%% 负面%.0f%%, 激化节点%d个",
            event_id,
            emotion_ratios["正面"] * 100,
            emotion_ratios["中性"] * 100,
            emotion_ratios["负面"] * 100,
            len(agitated_nodes),
        )

        return result

    except Exception as e:
        logger.error("情绪分析失败: event_id=%d, %s", event_id, e)
        return None
    finally:
        conn.close()


def _get_event_news(conn, event_id: int, event_title: str) -> List[Dict]:
    """获取事件关联新闻（复用 event_processor 的逻辑）"""
    # 优先通过 event_id 关联
    rows = conn.execute(
        "SELECT id, title, content, source_platform, published_at "
        "FROM raw_news WHERE event_id = ? ORDER BY published_at ASC",
        (event_id,),
    ).fetchall()

    if rows:
        return [dict(r) for r in rows]

    # 回退到关键词匹配
    if event_title:
        words = [w for w in segment_text(event_title) if len(w) >= 2][:5]
        if words:
            conditions = " OR ".join(["title LIKE ?" for _ in words])
            params = [f"%{w}%" for w in words]
            rows = conn.execute(
                f"SELECT id, title, content, source_platform, published_at "
                f"FROM raw_news WHERE {conditions} ORDER BY published_at ASC LIMIT 50",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    return []


def _explain_agitation(node: Dict) -> str:
    """解释情绪激化的原因"""
    triggers = node["trigger_words"]
    platform = node["platform"]
    score = node["score"]

    parts = []
    if triggers:
        parts.append(f"内容包含激化词汇: {', '.join(triggers[:3])}")
    if score < 0.3:
        parts.append("整体情感极度负面")
    if platform in ("微博", "抖音", "小红书"):
        parts.append(f"在{platform}平台传播，情绪易放大")

    return "；".join(parts) if parts else "情感表达较激烈"


def _analyze_fluctuation(timeline: List[Dict], node_emotions: List[Dict]) -> List[str]:
    """
    分析情绪时间线波动并生成诱因说明。
    对比相邻日期的情绪走向，结合激化节点解释变化原因。
    """
    causes = []

    if len(timeline) < 2:
        # 只有一天数据
        if timeline:
            t = timeline[0]
            if t["dominant"] != "中性":
                causes.append(
                    f"{t['date']}整体情绪偏{t['dominant']}，"
                    f"共{t['news_count']}条报道参与情绪建构"
                )
        return causes

    for i in range(1, len(timeline)):
        prev = timeline[i - 1]
        curr = timeline[i]
        shift = curr["avg_score"] - prev["avg_score"]

        # 情绪变化超过 0.1 视为明显波动
        if abs(shift) >= 0.1:
            direction = EMOTION_SHIFT["up"] if shift > 0 else EMOTION_SHIFT["down"]

            # 查找该日期的激化节点
            agitated_in_day = [
                ne for ne in node_emotions
                if ne.get("published_at", "").startswith(curr["date"]) and ne["is_agitated"]
            ]

            if agitated_in_day:
                top_trigger = agitated_in_day[0]["trigger_words"][:3]
                cause = (
                    f"{curr['date']}情绪由{prev['dominant']}转为{curr['dominant']}，"
                    f"{direction}。诱因：相关报道中出现{', '.join(top_trigger)}等情绪化表述"
                )
            else:
                cause = (
                    f"{curr['date']}情绪由{prev['dominant']}转为{curr['dominant']}，"
                    f"{direction}，新增{curr['news_count']}条报道"
                )
            causes.append(cause)

    return causes[:5]  # 最多返回5条


def _empty_result(event_id: int) -> Dict:
    """空结果默认返回"""
    return {
        "event_id": event_id,
        "emotion_ratios": {"正面": 0.33, "中性": 0.34, "负面": 0.33},
        "node_emotions": [],
        "agitated_nodes": [],
        "emotion_timeline": [],
        "fluctuation_causes": [],
    }
