# -*- coding: utf-8 -*-
"""
数据清洗层 — 文本规范化与跨平台标准化
==========================================================
架构位置: 清洗层，位于引擎层与存储层之间
职责:
    1. 去除 HTML/XML 标签，提取纯文本
    2. 过滤停用符号、编辑标注、HTML实体、零宽字符
    3. 统一多源时间格式为 YYYY-MM-DD HH:MM:SS
    4. 跨平台字段标准化（将不同平台的结构映射为统一的 CrawledItem）
    5. 校验内容是否为公开可分析内容
    6. 复用原有 crawler.py 中的清洗逻辑并增强扩展
==========================================================
"""

import re
import time
from datetime import datetime
from typing import Optional

from .models import CrawledItem
from .config import logger

# -----------------------------------------------------------------------
# 正则常量 — 复用原有 crawler.py 中的定义
# -----------------------------------------------------------------------

# 需要过滤的冗余符号和空白字符
# 包括: 不间断空格 \xa0、全角空格 \u3000、制表符 \t
#        零宽字符 \u200b \u200c \u200d
#        换行符 \r\n \n \r
#        [编辑：xxx]、【xxx】等编辑标注
#        HTML 数字实体 &#\d+; 和命名实体 &[a-zA-Z]+;
NOISE_PATTERN: re.Pattern = re.compile(
    r"[\xa0\u3000\t"           # 不间断空格、全角空格、制表符
    r"\u200b\u200c\u200d"      # 零宽字符
    r"\r\n|\n|\r"               # 换行
    r"\[.*?\]"                  # [编辑：xxx] 这类编辑标注
    r"【.*?】"                  # 【xxx】方括号标注
    r"&#\d+;"                   # HTML 数字实体 (如 &#160;)
    r"&[a-zA-Z]+;"             # HTML 命名实体 (如 &nbsp; &amp;)
    r"]+"
)

# 连续多余空白压缩为一个空格
MULTI_SPACE: re.Pattern = re.compile(r" {2,}")

# 私有/非公开内容的关键词（用于 validate_public_content）
_PRIVATE_KEYWORDS = [
    "仅自己可见", "仅好友可见", "已删除", "内容不存在",
    "该内容已被发布者删除", "抱歉，内容被隐藏", "因违规无法查看",
]


# -----------------------------------------------------------------------
# 基础清洗函数
# -----------------------------------------------------------------------
def strip_html_tags(text: str) -> str:
    """
    去除 HTML / XML 标签，只保留纯文本内容。

    处理逻辑:
        1. 移除所有 <xxx> 标签
        2. 移除 <!-- ... --> HTML 注释
        3. 去除首尾空白

    参数:
        text: 包含 HTML 标签的原始文本

    返回:
        纯文本字符串

    示例:
        >>> strip_html_tags('<p>这是<b>重要</b>新闻</p>')
        '这是重要新闻'
    """
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)                        # 移除所有标签
    text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)  # 移除注释
    return text.strip()


def clean_noise_symbols(text: str) -> str:
    """
    过滤停用符号和冗余标记。

    处理内容:
        - 不间断空格 (\xa0)、全角空格 (\u3000)、制表符
        - 零宽字符 (\u200b, \u200c, \u200d)
        - HTML 实体（&#160; &nbsp; &amp; 等）
        - [编辑：xxx]、【xxx】等编辑标注
        - 换行符
        - 连续多余空白压缩为单个空格

    参数:
        text: 经过去 HTML 处理后的文本

    返回:
        清洗后的纯净文本

    示例:
        >>> clean_noise_symbols('新闻&#160;[编辑：张三]　标题')
        '新闻 标题'
    """
    if not text:
        return ""
    text = NOISE_PATTERN.sub(" ", text)
    text = MULTI_SPACE.sub(" ", text)
    return text.strip()


def normalize_datetime(raw_time: str) -> str:
    """
    将各种来源的时间格式统一转换为标准格式: YYYY-MM-DD HH:MM:SS

    支持的格式（按优先级排序）:
        1. RFC 822 (带时区):   "Mon, 08 Jul 2026 10:30:00 +0800"
        2. RFC 822 (无时区):   "Mon, 08 Jul 2026 10:30:00"
        3. ISO 8601 (带时区):  "2026-07-08T10:30:00+08:00"
        4. ISO 8601 (无时区):  "2026-07-08T10:30:00"
        5. 标准日期时间:       "2026-07-08 10:30:00"
        6. 紧凑格式:           "20260708 10:30:00"
        7. 中文日期时间:       "2026年07月08日 10:30:00"
        8. 中文日期:           "2026年07月08日"
        9. 斜杠格式:           "2026/07/08 10:30:00"
        10. Unix 时间戳(秒):   1689989400
        11. Unix 时间戳(毫秒): 1689989400000

    如果所有格式都解析失败，返回当前时间。

    参数:
        raw_time: 原始时间字符串

    返回:
        标准格式时间字符串 "YYYY-MM-DD HH:MM:SS"
    """
    if not raw_time or not str(raw_time).strip():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_time = str(raw_time).strip()

    # ---------- 尝试解析 Unix 时间戳 ----------
    try:
        ts = float(raw_time)
        # 毫秒级时间戳: 大于 10^10 视为毫秒
        if ts > 1e10:
            ts = ts / 1000
        # 合法范围: 2020-01-01 ~ 2030-12-31
        if 1577836800 < ts < 1924988400:
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        pass

    # ---------- 尝试解析文本时间格式 ----------
    # 解析格式列表（按常见程度排序）
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",     # RFC 822 带时区 (RSS 标准)
        "%a, %d %b %Y %H:%M:%S",         # RFC 822 无时区
        "%Y-%m-%dT%H:%M:%S%z",            # ISO 8601 带时区
        "%Y-%m-%dT%H:%M:%S",              # ISO 8601 无时区
        "%Y-%m-%d %H:%M:%S",              # 标准日期时间
        "%Y%m%d %H:%M:%S",                # 紧凑格式
        "%Y/%m/%d %H:%M:%S",             # 斜杠分隔
        "%Y年%m月%d日 %H:%M:%S",          # 中文日期时间
        "%Y年%m月%d日",                    # 中文日期
        "%Y年%m月%d日 %H时%M分",          # 中文短格式
        "%b %d, %Y %H:%M:%S",            # 英文格式 "Jul 08, 2026 10:30:00"
        "%d-%b-%Y %H:%M:%S",             # "08-Jul-2026 10:30:00"
        "%m/%d/%Y %H:%M:%S",             # 美式 "07/08/2026 10:30:00"
        "%Y-%m-%d",                        # 仅日期
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw_time, fmt)
            # 有时区信息时，转换为本地时间
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

    # 所有格式都解析失败，返回当前时间并记录警告
    logger.debug("时间格式解析失败，使用当前时间: raw='%s'", raw_time)
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(text: str) -> str:
    """
    完整的文本清洗流程。

    步骤:
        1. strip_html_tags — 去除 HTML/XML 标签
        2. clean_noise_symbols — 过滤停用符号和冗余标记
        3. strip — 去除首尾空白

    参数:
        text: 原始文本（可能包含 HTML 标签、特殊字符等）

    返回:
        清洗后的纯净文本
    """
    if not text:
        return ""
    text = strip_html_tags(text)
    text = clean_noise_symbols(text)
    return text.strip()


# -----------------------------------------------------------------------
# 跨平台标准化
# -----------------------------------------------------------------------
# 平台名称映射表 — 将各平台的内部名称统一为标准显示名
_PLATFORM_NAME_MAP = {
    "people_rss": "人民网",
    "weibo": "微博",
    "weibo_api": "微博",
    "weibo_hot": "微博热搜",
    "douyin": "抖音",
    "douyin_hot": "抖音热搜",
    "zhihu": "知乎",
    "zhihu_hot": "知乎热榜",
    "xiaohongshu": "小红书",
    "xiaohongshu_hot": "小红书热搜",
    "bilibili": "B站",
    "bilibili_hot": "B站热搜",
    "toutiao": "今日头条",
    "toutiao_rss": "今日头条",
    "wechat": "微信公众号",
    "wechat_rss": "微信公众号",
}


def cross_platform_normalize(item: CrawledItem) -> CrawledItem:
    """
    跨平台字段标准化。

    对 CrawledItem 的各字段进行规范化处理:
        1. source_platform: 通过映射表统一平台名称
        2. title/content:  执行 clean_text 清洗
        3. published_at:   执行 normalize_datetime 时间标准化
        4. crawl_time:     自动填充当前时间（如果为空）
        5. interaction_data: 确保字典中所有值都为 int 类型
        6. author:         去除首尾空白
        7. original_url:   去除首尾空白及追踪参数

    参数:
        item: 原始采集数据（可能包含平台特有的格式）

    返回:
        标准化后的 CrawledItem（原地修改后返回）
    """
    # 平台名称标准化
    if item.source_platform in _PLATFORM_NAME_MAP:
        item.source_platform = _PLATFORM_NAME_MAP[item.source_platform]

    # 文本清洗
    item.title = clean_text(item.title)
    item.content = clean_text(item.content)
    item.author = item.author.strip() if item.author else ""

    # 时间标准化
    item.published_at = normalize_datetime(item.published_at)

    # 自动填充采集时间
    if not item.crawl_time:
        item.crawl_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # URL 清理: 去除空白，移除常见的追踪参数
    if item.original_url:
        item.original_url = item.original_url.strip()
        # 移除微博等平台常见的 utm_* 追踪参数
        item.original_url = re.sub(
            r"[?&](utm_source|utm_medium|utm_campaign|utm_term|utm_content)=[^&]*",
            "", item.original_url,
        )
        # 清理末尾残留的 ? 或 &
        item.original_url = re.sub(r"[?&]$", "", item.original_url)

    # interaction_data 数值化
    if item.interaction_data:
        normalized_interaction = {}
        for key, value in item.interaction_data.items():
            try:
                normalized_interaction[key] = int(value)
            except (ValueError, TypeError):
                normalized_interaction[key] = 0
        item.interaction_data = normalized_interaction

    return item


# -----------------------------------------------------------------------
# 内容校验
# -----------------------------------------------------------------------
def validate_public_content(item: CrawledItem) -> bool:
    """
    校验内容是否为公开可分析内容。

    判定为非公开内容的情况:
        1. 标题或正文为空
        2. 标题过短（少于 4 个字符，通常是广告或占位符）
        3. 标题或正文包含 "已删除"、"仅自己可见" 等关键词
        4. is_public 字段为 False
        5. 正文包含大量重复字符（可能是占位符/乱码）

    参数:
        item: 待校验的采集数据

    返回:
        True 表示内容有效可分析，False 表示应丢弃
    """
    # 显式标记为非公开
    if not item.is_public:
        logger.debug("非公开内容跳过: %s", item.title[:50] if item.title else "(无标题)")
        return False

    # 标题校验
    if not item.title or len(item.title.strip()) < 4:
        logger.debug("标题过短或为空，跳过")
        return False

    # 正文校验（允许正文为空，仅标题有值也可入库）
    # 但如果正文存在，需检查是否为有效内容
    if item.content:
        # 检查是否包含私密/删除关键词
        title_lower = item.title.lower()
        content_lower = item.content.lower()
        combined = title_lower + " " + content_lower

        for keyword in _PRIVATE_KEYWORDS:
            if keyword in combined:
                logger.debug("命中非公开关键词 '%s'，跳过: %s", keyword, item.title[:50])
                return False

        # 检查正文是否为大量重复字符（超过20个连续相同字符）
        repeat_match = re.search(r"(.)\1{20,}", item.content)
        if repeat_match:
            logger.debug("正文含大量重复字符，跳过: %s", item.title[:50])
            return False

    return True
