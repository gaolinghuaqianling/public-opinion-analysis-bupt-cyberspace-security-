# -*- coding: utf-8 -*-
"""
情感倾向分析模块
==========================================================
基于 SnowNLP 轻量中文情感分析，自动计算正面/负面/中立比例。
提供单条分析、批量分析和事件综合情感计算功能。
==========================================================
"""

import re
import logging
from typing import List, Dict

from snownlp import SnowNLP

from app.services.nlp_tools import segment_text, extract_keywords

logger = logging.getLogger("services.sentiment")


# ===================================================================
# 情感分值分类阈值常量
# ===================================================================
# 正面阈值: score > POSITIVE_THRESHOLD 视为正面情感
POSITIVE_THRESHOLD = 0.6
# 负面阈值: score < NEGATIVE_THRESHOLD 视为负面情感
NEGATIVE_THRESHOLD = 0.4
# 中性区间: NEGATIVE_THRESHOLD <= score <= POSITIVE_THRESHOLD


def analyze_sentiment(text: str) -> Dict:
    """
    分析单条文本的情感倾向。

    算法流程:
        1. 使用 SnowNLP(text).sentiments 获取基础情感分值（0~1）
           - 0 表示极负面，1 表示极正面，0.5 为中性
        2. 对长文本（> 200字）进行分段计算取平均，提升准确性
        3. 将 score 映射为正面/负面/中立比例:
           - score > 0.6 (正面区域):
             positive_ratio = score
             negative_ratio = 1 - score
             neutral_ratio  = 0
           - score < 0.4 (负面区域):
             positive_ratio = 1 - score
             negative_ratio = score
             neutral_ratio  = 0
           - 0.4 <= score <= 0.6 (中性区域):
             positive_ratio = 0
             negative_ratio = 0
             neutral_ratio  = 1.0 - abs(score - 0.5) * 5
             （越接近 0.5，中立比例越高）

    参数:
        text: 待分析的文本内容

    返回:
        包含以下键的字典:
            - score:          float, 综合情感分 (0=极负面, 0.5=中性, 1=极正面)
            - positive_ratio: float, 正面情感比例 (0~1)
            - negative_ratio: float, 负面情感比例 (0~1)
            - neutral_ratio:  float, 中立情感比例 (0~1)
            - sentiment:      str,   情感分类 "positive" / "negative" / "neutral"

    示例:
        >>> analyze_sentiment("这个产品非常好用，推荐购买")
        {'score': 0.85, 'positive_ratio': 0.85, 'negative_ratio': 0.15,
         'neutral_ratio': 0.0, 'sentiment': 'positive'}
    """
    if not text or not text.strip():
        return {
            "score": 0.5,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 1.0,
            "sentiment": "neutral",
        }

    try:
        # 对短文本直接计算
        if len(text) <= 200:
            score = SnowNLP(text).sentiments
        else:
            # 长文本分段计算，每段不超过 200 字，取平均分值
            segments = _split_text_for_sentiment(text, max_len=200)
            if not segments:
                segments = [text]

            scores = []
            for seg in segments:
                try:
                    s = SnowNLP(seg).sentiments
                    scores.append(s)
                except Exception as e:
                    logger.debug("分段情感分析失败: %s", e)
                    continue

            if scores:
                score = sum(scores) / len(scores)
            else:
                score = 0.5

        # 限制 score 在 [0, 1] 范围内
        score = max(0.0, min(1.0, score))

        # 映射为正面/负面/中立比例
        if score > POSITIVE_THRESHOLD:
            # 正面区域
            positive_ratio = score
            negative_ratio = 1.0 - score
            neutral_ratio = 0.0
        elif score < NEGATIVE_THRESHOLD:
            # 负面区域
            positive_ratio = 1.0 - score
            negative_ratio = score
            neutral_ratio = 0.0
        else:
            # 中性区域: 越接近 0.5，中立比例越高
            # score=0.5 时 neutral_ratio=1.0, score=0.4或0.6时 neutral_ratio=0.0
            neutral_ratio = 1.0 - abs(score - 0.5) * 5.0
            neutral_ratio = max(0.0, min(1.0, neutral_ratio))

            # 剩余比例分配给正面和负面
            remaining = 1.0 - neutral_ratio
            if score >= 0.5:
                positive_ratio = remaining * (score - 0.5) / 0.1
                negative_ratio = remaining - positive_ratio
            else:
                negative_ratio = remaining * (0.5 - score) / 0.1
                positive_ratio = remaining - negative_ratio

        # 确保比例非负
        positive_ratio = max(0.0, positive_ratio)
        negative_ratio = max(0.0, negative_ratio)
        neutral_ratio = max(0.0, neutral_ratio)

        # 归一化（确保三者之和为 1）
        total = positive_ratio + negative_ratio + neutral_ratio
        if total > 0:
            positive_ratio /= total
            negative_ratio /= total
            neutral_ratio /= total

        # 情感分类
        sentiment = classify_sentiment(score)

        return {
            "score": round(score, 4),
            "positive_ratio": round(positive_ratio, 4),
            "negative_ratio": round(negative_ratio, 4),
            "neutral_ratio": round(neutral_ratio, 4),
            "sentiment": sentiment,
        }

    except Exception as e:
        logger.warning("情感分析失败: %s", e)
        return {
            "score": 0.5,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 1.0,
            "sentiment": "neutral",
        }


def analyze_batch(texts: List[str]) -> Dict:
    """
    批量分析多条文本的情感倾向。

    对每条文本调用 analyze_sentiment 获取单条分析结果，
    然后汇总统计正面/负面/中立比例和平均分值。

    参数:
        texts: 待分析的文本列表 [text1, text2, ...]

    返回:
        包含以下键的字典:
            - scores:          list,   每条文本的情感分值列表
            - avg_score:       float,  平均情感分值
            - positive_ratio: float,  正面情感比例（按条数计算）
            - negative_ratio: float,  负面情感比例（按条数计算）
            - neutral_ratio:  float,  中立情感比例（按条数计算）
            - total:           int,    总分析条数

    示例:
        >>> analyze_batch(["今天天气真好", "产品质量太差了"])
        {'scores': [0.85, 0.15], 'avg_score': 0.5, ...}
    """
    if not texts:
        return {
            "scores": [],
            "avg_score": 0.5,
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 1.0,
            "total": 0,
        }

    scores = []
    positive_count = 0
    negative_count = 0
    neutral_count = 0

    for text in texts:
        result = analyze_sentiment(text)
        scores.append(result["score"])

        if result["sentiment"] == "positive":
            positive_count += 1
        elif result["sentiment"] == "negative":
            negative_count += 1
        else:
            neutral_count += 1

    total = len(scores)
    if total > 0:
        avg_score = sum(scores) / total
        positive_ratio = positive_count / total
        negative_ratio = negative_count / total
        neutral_ratio = neutral_count / total
    else:
        avg_score = 0.5
        positive_ratio = 0.0
        negative_ratio = 0.0
        neutral_ratio = 1.0

    return {
        "scores": [round(s, 4) for s in scores],
        "avg_score": round(avg_score, 4),
        "positive_ratio": round(positive_ratio, 4),
        "negative_ratio": round(negative_ratio, 4),
        "neutral_ratio": round(neutral_ratio, 4),
        "total": total,
    }


def classify_sentiment(score: float) -> str:
    """
    将情感分值分类为 positive / negative / neutral。

    分类规则:
        - score > 0.6:  "positive" (正面)
        - score < 0.4:  "negative" (负面)
        - 其他:         "neutral"  (中立)

    参数:
        score: 情感分值 (0~1)

    返回:
        情感分类字符串

    示例:
        >>> classify_sentiment(0.8)
        'positive'
        >>> classify_sentiment(0.2)
        'negative'
        >>> classify_sentiment(0.5)
        'neutral'
    """
    if score > POSITIVE_THRESHOLD:
        return "positive"
    elif score < NEGATIVE_THRESHOLD:
        return "negative"
    else:
        return "neutral"


def compute_event_sentiment(texts: List[str]) -> Dict:
    """
    计算一个事件的综合情感倾向（基于其所有关联报道）。

    将所有关联新闻文本作为输入，综合计算:
        - 正面/负面/中立报道比例
        - 平均情感分值
        - 有效分析的新闻数量

    适用于对同一事件下多篇报道进行整体情感评估。

    参数:
        texts: 与该事件关联的所有新闻文本列表

    返回:
        包含以下键的字典:
            - positive_ratio: float, 正面报道比例 (0~1)
            - negative_ratio: float, 负面报道比例 (0~1)
            - neutral_ratio:  float, 中立报道比例 (0~1)
            - avg_score:      float, 平均情感分值 (0~1)
            - analyzed_count: int,   有效分析的新闻条数

    示例:
        >>> compute_event_sentiment(["报道一正面内容", "报道二负面内容"])
        {'positive_ratio': 0.5, 'negative_ratio': 0.5, 'neutral_ratio': 0.0,
         'avg_score': 0.5, 'analyzed_count': 2}
    """
    if not texts:
        return {
            "positive_ratio": 0.0,
            "negative_ratio": 0.0,
            "neutral_ratio": 0.0,
            "avg_score": 0.5,
            "analyzed_count": 0,
        }

    # 使用批量分析获取汇总结果
    batch_result = analyze_batch(texts)

    return {
        "positive_ratio": batch_result["positive_ratio"],
        "negative_ratio": batch_result["negative_ratio"],
        "neutral_ratio": batch_result["neutral_ratio"],
        "avg_score": batch_result["avg_score"],
        "analyzed_count": batch_result["total"],
    }


# ===================================================================
# 内部辅助函数
# ===================================================================

def _split_text_for_sentiment(text: str, max_len: int = 200) -> List[str]:
    """
    将长文本按句子分割为多个适合情感分析的短片段。

    分割策略:
        1. 优先按中文句号（。）、问号（？）、叹号（！）分割
        2. 如果单句过长，再按逗号（，、；）分割
        3. 合并过短的片段（< 10 字）到前一个片段
        4. 确保每个片段不超过 max_len

    参数:
        text:    原始长文本
        max_len: 每个片段的最大长度

    返回:
        分割后的文本片段列表
    """
    if not text:
        return []

    # 按句号、问号、叹号分割
    sentences = re.split(r"[。！？\n]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 合并片段，使每个片段长度在合理范围内
    segments = []
    current = ""

    for sentence in sentences:
        # 如果当前片段加上新句子不超过最大长度，则合并
        if len(current) + len(sentence) <= max_len:
            current = (current + sentence).strip()
        else:
            # 保存当前片段
            if current:
                segments.append(current)
            # 如果单句超过 max_len，进一步按逗号分割
            if len(sentence) > max_len:
                sub_parts = re.split(r"[，、；：]+", sentence)
                sub_parts = [p.strip() for p in sub_parts if p.strip()]
                for part in sub_parts:
                    if len(part) > max_len:
                        # 如果还是太长，直接截断
                        segments.append(part[:max_len])
                    elif part:
                        segments.append(part)
                current = ""
            else:
                current = sentence

    if current:
        segments.append(current)

    return segments if segments else [text]

