# -*- coding: utf-8 -*-
"""
虚假文本检测模块
==========================================================
基于多维度特征加权计算文本可信度，输出置信度和判定理由。

检测维度:
  1. 信源可信度: 来源平台的权威性评分
  2. 标题党特征: 标题中的煽动性关键词
  3. 情感极端度: 情感分值是否异常极端
  4. 事实性线索: 是否包含具体时间/地点/数据等可验证信息
  5. 文本一致性: 标题与正文的关键词重叠率
  6. 煽动性语言: 感叹号密度、煽动词汇频率
==========================================================
"""

import re
import logging
from typing import List, Dict, Tuple
from app.services.nlp_tools import segment_text, extract_keywords
from app.services.sentiment_analyzer import analyze_sentiment

logger = logging.getLogger("services.fake_detector")


# ===================================================================
# 平台可信度权重
# ===================================================================
# 官方媒体/主流媒体: 权威性高，得分 >= 0.75
# 社交平台/自媒体:   权威性中等，得分 0.40~0.55
# 未知平台:           默认得分 0.50
SOURCE_CREDIBILITY = {
    # 官方媒体 — 高可信
    "人民网": 0.95, "新华网": 0.95, "央视": 0.95, "中国新闻网": 0.90,
    "光明网": 0.90, "经济日报": 0.90, "人民日报": 0.95,
    # 主流媒体 — 较高可信
    "澎湃新闻": 0.80, "界面新闻": 0.80, "第一财经": 0.80, "财新": 0.85,
    "南方周末": 0.85, "环球时报": 0.75, "中国青年报": 0.80,
    # 社交平台 — 中等可信（自媒体为主）
    "微博": 0.50, "知乎": 0.55, "微信公众号": 0.45,
    "B站": 0.50, "今日头条": 0.45,
    # 短视频平台 — 较低可信
    "抖音": 0.40, "小红书": 0.40,
}
DEFAULT_CREDIBILITY = 0.50  # 未知平台默认可信度


# ===================================================================
# 标题党关键词（正则模式列表）
# ===================================================================
CLICKBAIT_PATTERNS = [
    r"震惊", r"不转不是", r"赶紧.{0,4}看", r"速看", r"转发",
    r"必看", r"重磅", r"惊天", r"吓傻", r"吓死", r"惊呆了",
    r"竟然", r"居然", r"太.{0,2}了", r"不敢相信",
    r"内部消息", r"独家", r"秘密", r"真相.{0,3}曝光",
    r"99%的人", r"看完.{0,4}惊了", r"终于.{0,4}曝光",
    r"删前速看", r"马上删", r"看后被删",
    r"网传", r"据说", r"小道",
]


# ===================================================================
# 煽动性词汇列表
# ===================================================================
AGITATION_WORDS = [
    "愤怒", "怒斥", "强烈谴责", "令人发指", "丧心病狂",
    "无耻", "卑鄙", "可恶", "太过分了", "恶心",
    "彻底", "绝了", "炸了", "疯了", "崩溃",
    "不配", "活该", "渣", "垃圾", "败类",
]


# ===================================================================
# 事实性模式（正则 + 类型标签）
# ===================================================================
FACT_PATTERNS = [
    (r"\d{4}年\d{1,2}月\d{1,2}日", "具体日期"),
    (r"\d{1,2}月\d{1,2}日", "月日"),
    (r"星期[一二三四五六日天]", "星期"),
    (r"[省市].{0,5}市", "地名"),
    (r"[省区].{0,10}[市县区]", "行政区划"),
    (r"\d+%", "百分比数据"),
    (r"\d+[万亿]+", "数量级数据"),
    (r"\d+元", "金额"),
    (r"\d+岁", "年龄"),
    (r" said|according to|据.{0,5}报道|据.{0,5}透露", "引用来源"),
    (r"[《「].+?[》」]", "专有名词引用"),
]


# ===================================================================
# 主检测函数
# ===================================================================

def detect_fake_text(
    title: str,
    content: str = "",
    source_platform: str = "",
    author: str = "",
) -> Dict:
    """
    虚假文本检测主函数。

    综合六个维度对文本进行可信度评估:
        1. 信源可信度   → _check_source_credibility()
        2. 标题党特征   → _check_clickbait()
        3. 情感极端度   → _check_sentiment_extremity()
        4. 事实性线索   → _check_factual_clues()
        5. 标题正文一致性 → _check_title_content_consistency()
        6. 煽动性语言   → _check_agitation()

    各维度加权汇总得到 credibility_score（0~1），越接近 1 越可信。
    等级判定: >=0.7 高可信, >=0.4 待验证, <0.4 疑似虚假。

    参数:
        title:           文本标题
        content:         正文内容（可为空）
        source_platform: 来源平台名称
        author:          作者/账号名（当前版本未使用，预留）

    返回:
        包含以下键的字典:
            - credibility_score: float,   综合可信度评分 (0~1)
            - level:             str,     可信度等级 "高可信" / "待验证" / "疑似虚假"
            - details:           dict,    各维度得分明细
            - reasons:           list,    判定理由列表（中文描述）
            - fake_flags:         list,    命中的虚假特征标记列表

    示例:
        >>> detect_fake_text(
        ...     title="震惊！这件事竟然是真的",
        ...     content="据报道，2024年3月15日北京市发生了一起事件。",
        ...     source_platform="微博",
        ... )
        {'credibility_score': 0.52, 'level': '待验证', ...}
    """
    details = {}
    reasons = []
    fake_flags = []

    # 1. 信源可信度
    source_score = _check_source_credibility(source_platform)
    details["source_score"] = source_score
    if source_score < 0.5:
        reasons.append(f"信源为自媒体/未知平台（可信度 {source_score:.0%}）")
    elif source_score >= 0.9:
        reasons.append(f"信源为官方媒体（可信度 {source_score:.0%}）")

    # 2. 标题党检测
    clickbait_score, cb_flags = _check_clickbait(title)
    details["clickbait_score"] = clickbait_score
    fake_flags.extend(cb_flags)
    if clickbait_score > 0.3:
        reasons.append(f"标题含煽动性关键词: {', '.join(cb_flags[:3])}")

    # 3. 情感极端度
    sentiment_score = _check_sentiment_extremity(title, content)
    details["sentiment_score"] = sentiment_score
    if sentiment_score < 0.5:
        reasons.append("情感倾向极端（过度正面或负面）")

    # 4. 事实性线索
    fact_score, fact_types = _check_factual_clues(title + " " + content)
    details["fact_score"] = fact_score
    if fact_types:
        reasons.append(f"包含事实性线索: {', '.join(fact_types[:3])}")
    else:
        reasons.append("缺少事实性引用（无具体时间/地点/数据）")

    # 5. 标题正文一致性
    consistency_score = _check_title_content_consistency(title, content) if content else 0.5
    details["consistency_score"] = consistency_score
    if consistency_score < 0.3:
        reasons.append("标题与正文内容一致性低（可能标题党）")

    # 6. 煽动性语言
    agitation_score = _check_agitation(title + " " + content)
    details["agitation_score"] = agitation_score
    if agitation_score > 0.3:
        reasons.append(f"含煽动性/情绪化语言（密度 {agitation_score:.0%}）")

    # ---- 综合评分 ----
    # 各维度权重: 信源与事实性占比较高，其余平分
    weights = {
        "source_score": 0.20,
        "clickbait_score": 0.15,
        "sentiment_score": 0.15,
        "fact_score": 0.20,
        "consistency_score": 0.15,
        "agitation_score": 0.15,
    }

    credibility = sum(details[k] * weights[k] for k in weights)
    credibility = round(max(0.0, min(1.0, credibility)), 4)

    # 等级判定
    if credibility >= 0.7:
        level = "高可信"
    elif credibility >= 0.4:
        level = "待验证"
    else:
        level = "疑似虚假"

    return {
        "credibility_score": credibility,
        "level": level,
        "details": {k: round(v, 4) for k, v in details.items()},
        "reasons": reasons,
        "fake_flags": fake_flags,
    }


# ===================================================================
# 批量检测
# ===================================================================

def batch_detect(news_list: List[Dict]) -> List[Dict]:
    """
    批量检测多条新闻的虚假特征。

    对列表中的每条新闻调用 detect_fake_text，返回结果列表。
    适用于一次性分析多篇报道的可信度。

    参数:
        news_list: 新闻字典列表，每个字典需包含:
            - title:           str, 新闻标题（必需）
            - content:         str, 正文内容（可选）
            - source_platform: str, 来源平台（可选）

    返回:
        detect_fake_text 结果字典列表，顺序与输入一致

    示例:
        >>> batch_detect([
        ...     {"title": "标题一", "content": "正文一", "source_platform": "人民网"},
        ...     {"title": "标题二", "content": "正文二"},
        ... ])
        [{'credibility_score': 0.85, ...}, {'credibility_score': 0.55, ...}]
    """
    results = []
    for item in news_list:
        result = detect_fake_text(
            title=item.get("title", ""),
            content=item.get("content", ""),
            source_platform=item.get("source_platform", ""),
        )
        results.append(result)
    return results


# ===================================================================
# 内部辅助函数
# ===================================================================

def _check_source_credibility(platform: str) -> float:
    """
    信源可信度评分。

    评分逻辑:
        1. 若 platform 为空，返回默认值 DEFAULT_CREDIBILITY (0.50)
        2. 精确匹配 SOURCE_CREDIBILITY 字典中的平台名称
        3. 模糊匹配（包含关系）: 若平台名包含字典 key 或反之
        4. 以上均未命中则返回默认值

    参数:
        platform: 来源平台名称

    返回:
        可信度得分 (0~1)
    """
    if not platform:
        return DEFAULT_CREDIBILITY
    # 精确匹配
    for key, score in SOURCE_CREDIBILITY.items():
        if key in platform:
            return score
    # 模糊匹配（包含关系）
    for key, score in SOURCE_CREDIBILITY.items():
        if platform in key or key in platform:
            return max(score, DEFAULT_CREDIBILITY)
    return DEFAULT_CREDIBILITY


def _check_clickbait(title: str) -> Tuple[float, List[str]]:
    """
    标题党检测。

    通过正则匹配标题中是否包含煽动性/标题党关键词。
    每命中一个模式扣 0.15 分，最低 0 分。

    参数:
        title: 新闻标题

    返回:
        (得分, 命中关键词列表): 得分 0~1，越高越可信
    """
    if not title:
        return (1.0, [])
    hits = []
    for pattern in CLICKBAIT_PATTERNS:
        if re.search(pattern, title):
            keyword = pattern.replace(r".{0,4}", "").replace(r".{0,3}", "")
            hits.append(keyword)
    score = max(0.0, 1.0 - len(hits) * 0.15)
    return (round(score, 4), hits)


def _check_sentiment_extremity(title: str, content: str) -> float:
    """
    情感极端度评分。

    调用 analyze_sentiment 获取情感分值 (0~1):
        - 0.5 表示中性，越接近 0 或 1 越极端
        - 极端情感扣分: distance * 0.6
        - 返回 1.0 - distance * 0.6，越高越可信

    参数:
        title:   新闻标题
        content: 正文内容

    返回:
        情感合理性得分 (0~1)，越高越可信
    """
    text = (title + " " + content).strip()
    if len(text) < 5:
        return 0.5
    try:
        result = analyze_sentiment(text)
        score = result.get("score", 0.5)
        # 越接近 0 或 1 越极端
        distance = abs(score - 0.5) * 2  # 归一化到 0~1
        # 极端则扣分
        return round(1.0 - distance * 0.6, 4)
    except Exception:
        return 0.5


def _check_factual_clues(text: str) -> Tuple[float, List[str]]:
    """
    事实性线索检测。

    通过正则匹配文本中是否包含可验证的事实性信息:
        - 具体日期、地名、行政区划
        - 百分比数据、数量级、金额、年龄
        - 引用来源、专有名词引用

    每命中一种类型加 0.2 分，最多 1.0 分。

    参数:
        text: 待检测文本（标题 + 正文）

    返回:
        (得分, 命中类型列表): 得分 0~1，越高事实性越强
    """
    if not text:
        return (0.0, [])
    found_types = []
    for pattern, label in FACT_PATTERNS:
        if re.search(pattern, text):
            found_types.append(label)
    # 最多 5 个线索得满分
    score = min(1.0, len(found_types) * 0.2)
    return (round(score, 4), found_types)


def _check_title_content_consistency(title: str, content: str) -> float:
    """
    标题与正文一致性检测（关键词重叠率）。

    计算逻辑:
        1. 分别对标题和正文进行 jieba 分词
        2. 计算标题词集与正文词集的交集比例
        3. 加 0.2 基础分（避免完全无关时得 0 分）

    参数:
        title:   新闻标题
        content: 正文内容

    返回:
        一致性得分 (0~1)，越高越一致
    """
    if not title or not content:
        return 0.5
    title_words = set(segment_text(title))
    content_words = set(segment_text(content))
    if not title_words:
        return 0.5
    overlap = title_words & content_words
    score = len(overlap) / len(title_words)
    return round(min(1.0, score + 0.2), 4)  # 加 0.2 基础分


def _check_agitation(text: str) -> float:
    """
    煽动性语言密度检测。

    统计文本中:
        - 煽动性词汇命中次数
        - 感叹号数量（中英文各计一次，权重 * 2）

    密度 = (命中次数 + 感叹号数 * 2) / (文本长度 / 50)
    最终得分 = min(1.0, 密度 * 0.5)

    参数:
        text: 待检测文本（标题 + 正文）

    返回:
        煽动性密度得分 (0~1)，越高越煽动
    """
    if not text:
        return 0.0
    hits = sum(1 for word in AGITATION_WORDS if word in text)
    # 感叹号密度
    excl_density = text.count("！") + text.count("!")
    total = len(text)
    density = (hits + excl_density * 2) / max(total / 50, 1)
    return round(min(1.0, density * 0.5), 4)
