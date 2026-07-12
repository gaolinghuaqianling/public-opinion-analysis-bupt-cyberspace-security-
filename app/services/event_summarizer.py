# -*- coding: utf-8 -*-
"""
================================================================================
  事件结构化信息提取模块 (event_summarizer.py)
================================================================================
从新闻文本中提取结构化事件概述信息：时间、地点、涉事人物/机构、事件起因。
基于正则表达式 + jieba 词性标注的轻量级 NLP 方案，无需额外训练环境。

使用方式:
  from app.services.event_summarizer import extract_structured_summary
  result = extract_structured_summary(title, content)
  # result = {
  #     "time": "2024年3月15日",
  #     "location": "北京",
  #     "people": ["张三", "某公司"],
  #     "cause": "因某某原因...",
  #     "summary_text": "2024年3月15日，北京。张三、某公司。因某某原因...",
  # }

依赖:
  - jieba: 中文分词 + 词性标注
================================================================================
"""

import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("services.event_summarizer")


# ---------------------------------------------------------------------------
# 时间模式正则
# ---------------------------------------------------------------------------
TIME_PATTERNS = [
    # YYYY年M月D日
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]",
    # YYYY-MM-DD / YYYY/MM/DD
    r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})",
    # M月D日
    r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]",
    # 今天/昨天/前天 + 具体时间
    r"(今天|昨天|前天|今日|昨日)",
]

# ---------------------------------------------------------------------------
# 地点模式：中国省/市/区/县 + 常见地点后缀
# ---------------------------------------------------------------------------
LOCATION_SUFFIXES = [
    "省", "市", "区", "县", "镇", "乡", "村", "州",
    "自治区", "直辖市", "特别行政区",
    "路", "街", "道", "广场", "公园", "机场", "车站", "港口", "大桥",
    "大学", "学院", "医院", "中学", "小学",
    "体育馆", "体育场", "博物馆", "图书馆", "展览馆",
]

# 常见中国地名关键词（高频出现在新闻中）
LOCATION_KEYWORDS = [
    "北京", "上海", "广州", "深圳", "天津", "重庆", "成都", "杭州",
    "武汉", "南京", "西安", "长沙", "郑州", "济南", "青岛", "大连",
    "沈阳", "哈尔滨", "长春", "福州", "厦门", "合肥", "南昌", "昆明",
    "贵阳", "海口", "三亚", "兰州", "银川", "西宁", "呼和浩特", "太原",
    "石家庄", "乌鲁木齐", "拉萨", "南宁", "珠海", "苏州", "无锡", "宁波",
    "东莞", "佛山", "温州", "烟台", "洛阳", "唐山", "徐州", "南通",
    "美国", "英国", "日本", "韩国", "法国", "德国", "俄罗斯", "澳大利亚",
    "加拿大", "印度", "巴西", "意大利", "西班牙", "泰国", "新加坡", "马来西亚",
    "联合国", "白宫", "五角大楼", "唐宁街", "克里姆林宫",
]

# ---------------------------------------------------------------------------
# 人物/机构后缀词
# ---------------------------------------------------------------------------
PEOPLE_SUFFIXES = [
    "表示", "称", "说", "透露", "宣布", "指出", "强调", "认为",
    "回应", "否认", "承认", "呼吁", "建议", "警告", "批评", "谴责",
    "感谢", "祝贺", "悼念", "出席", "参加", "主持", "会见", "访问",
]

ORG_SUFFIXES = [
    "公司", "集团", "企业", "银行", "基金", "部门", "机关", "单位",
    "组织", "协会", "委员会", "研究院", "研究所", "实验室",
    "政府", "法院", "检察院", "公安局", "教育部", "外交部", "财政部",
    "央视", "新华社", "人民日报", "环球时报", "光明日报",
    "大学", "学院", "医院",
]


def _extract_time(text: str) -> Optional[str]:
    """
    从文本中提取时间信息。
    优先匹配完整日期（YYYY年M月D日），其次日期缩写，最后相对时间。
    """
    for pattern in TIME_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            m = matches[0]
            if isinstance(m, tuple):
                # YYYY年M月D日
                if len(m) == 3:
                    return f"{m[0]}年{m[1]}月{m[2]}日"
                # M月D日
                elif len(m) == 2:
                    return f"{m[0]}月{m[1]}日"
            else:
                return m
    return None


def _extract_locations(text: str) -> List[str]:
    """
    从文本中提取地点信息。
    策略：关键词匹配 + 后缀词识别
    """
    locations = set()

    # 1. 直接匹配已知地名关键词
    for loc in LOCATION_KEYWORDS:
        if loc in text:
            locations.add(loc)

    # 2. 用 jieba 分词 + 词性标注提取地名
    try:
        import jieba.posseg as pseg
        words = pseg.cut(text)
        for word, flag in words:
            # jieba 词性：ns=地名, f=方位词
            if flag in ("ns", "f") and len(word) >= 2:
                # 过滤非地名误识别
                if word not in ("媒体报道", "公众视线", "网络空间", "社交媒体",
                                "新闻发布会", "舆论场"):
                    locations.add(word)
            # 带地名后缀的词
            if any(word.endswith(s) for s in LOCATION_SUFFIXES) and len(word) >= 2:
                # 过滤"某大学"等过于宽泛的表述
                if not word.startswith("某") and not word.startswith("该"):
                    locations.add(word)
    except Exception as e:
        logger.debug("jieba 地名提取失败: %s", e)

    # 3. 去重子串：如已有"北京"则移除"北京市"
    loc_list = sorted(locations, key=len, reverse=True)
    filtered = []
    for loc in loc_list:
        if not any(loc != other and (loc in other or other in loc) for other in filtered):
            filtered.append(loc)

    return filtered[:5]  # 最多返回5个地点


def _extract_people_and_orgs(text: str) -> Dict[str, List[str]]:
    """
    从文本中提取涉事人物和机构。
    策略：jieba 词性标注 + 后缀匹配
    返回: {"people": [...], "organizations": [...]}
    """
    people = set()
    orgs = set()

    try:
        import jieba.posseg as pseg
        words = pseg.cut(text)
        prev_word = ""

        for word, flag in words:
            # 人名：nr（人名）+ 2~4字
            if flag == "nr" and 2 <= len(word) <= 4:
                # 过滤常见非人名词
                if word not in ("自己", "我们", "他们", "她们", "大家", "网友",
                                "粉丝", "公众", "市民", "居民", "消费者"):
                    people.add(word)
            # 机构名：nt（机构名）
            if flag == "nt" and len(word) >= 2:
                orgs.add(word)

            # 前缀 + 机构后缀 组合检测
            if any(word.endswith(s) for s in ORG_SUFFIXES) and len(word) >= 3:
                orgs.add(word)

            # "XXX表示/称/说" → 可能是人名
            if any(prev_word.endswith(s) for s in PEOPLE_SUFFIXES):
                if 2 <= len(word) <= 4 and word not in ("了", "的", "是", "在"):
                    # 向前回溯找可能的姓名
                    pass  # jieba nr 已覆盖

            prev_word = word

    except Exception as e:
        logger.debug("jieba 人物/机构提取失败: %s", e)

    return {
        "people": list(people)[:5],
        "organizations": list(orgs)[:5],
    }


def _extract_cause(text: str, title: str = "") -> str:
    """
    提取事件起因/背景信息。
    策略：
      1. 优先从标题中识别"因/由于/因为/据/曝/爆料/回应"等起因引导词
      2. 截取引导词后面的内容作为起因描述
      3. 如无明确起因，取内容前100字作为背景概述
    """
    cause_text = title + " " + text

    # 起因引导模式
    cause_patterns = [
        r"(?:因|因为|由于|据|据报道|据.*?透露|曝|爆料|爆料称|据.*?报道)[：:]?\s*(.{10,80})",
        r"(?:回应|回应称|表示|指出|承认|否认|宣布)[：:]?\s*(.{10,80})",
        r"(?:引发|导致|造成|引起|源于|起因是)[：:]?\s*(.{10,80})",
    ]

    for pattern in cause_patterns:
        match = re.search(pattern, cause_text)
        if match:
            cause = match.group(1).strip()
            # 截断到句号或逗号
            for punct in ["。", "！", "？", "\n"]:
                if punct in cause:
                    cause = cause[:cause.index(punct)]
            return cause[:100]

    # 无明确起因，返回内容前100字
    clean_text = text.strip()
    if clean_text:
        return clean_text[:100] + "..." if len(clean_text) > 100 else clean_text

    return ""


def extract_structured_summary(title: str, content: str) -> Dict[str, object]:
    """
    从事件标题和正文提取结构化概述信息。

    参数:
        title:   事件标题
        content: 事件正文/内容

    返回:
        结构化摘要字典:
        {
            "time":           str | None,  # 事件时间
            "locations":      list[str],    # 涉及地点
            "people":         list[str],    # 涉事人物
            "organizations":  list[str],    # 涉事机构
            "cause":          str,          # 事件起因/背景
            "summary_text":   str,          # 组合后的结构化摘要文本
        }
    """
    full_text = f"{title} {content}" if content else title

    # 提取各维度
    time_info = _extract_time(full_text)
    locations = _extract_locations(full_text)
    entities = _extract_people_and_orgs(full_text)
    cause_info = _extract_cause(content, title)

    # 组合结构化摘要文本
    parts = []
    if time_info:
        parts.append(f"【时间】{time_info}")
    if locations:
        parts.append(f"【地点】{'、'.join(locations)}")
    people_list = entities.get("people", [])
    org_list = entities.get("organizations", [])
    if people_list or org_list:
        all_entities = people_list + org_list
        parts.append(f"【相关】{'、'.join(all_entities[:6])}")
    if cause_info:
        parts.append(f"【概述】{cause_info}")

    summary_text = " ".join(parts) if parts else (content[:200] if content else title)

    result = {
        "time": time_info,
        "locations": locations,
        "people": people_list,
        "organizations": org_list,
        "cause": cause_info,
        "summary_text": summary_text,
    }

    logger.debug("结构化摘要: time=%s, loc=%s, people=%s",
                 time_info, locations, people_list)

    return result
