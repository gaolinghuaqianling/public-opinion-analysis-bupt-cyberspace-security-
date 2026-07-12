# -*- coding: utf-8 -*-
"""
================================================================================
 人民网 RSS 新闻爬虫模块
================================================================================
功能：
  1. 通过 RSS 订阅源抓取人民网各频道新闻
  2. 数据清洗：去除 HTML 标签、去重（标题+URL 双重校验）、过滤停用符号、统一时间格式
  3. 清洗后的数据自动存入 SQLite 的 raw_news 表
  4. 支持定时循环抓取，内置随机延时防封禁
  5. 可直接运行：python crawler.py

用法：
  单次抓取：  python crawler.py --once
  定时抓取：  python crawler.py --interval 30        # 每30分钟抓一次
  指定频道：  python crawler.py --channels politics,finance
  查看帮助：  python crawler.py --help
================================================================================
"""

import re
import sys
import time
import random
import logging
import hashlib
import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from pathlib import Path

# -----------------------------------------------------------------------
# 日志配置
# -----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("crawler")

# -----------------------------------------------------------------------
# RSS 订阅源配置 —— 人民网各频道
# -----------------------------------------------------------------------
# 每个频道包含：名称（用于 source_platform 字段）和 RSS URL
RSS_CHANNELS: List[Dict[str, str]] = [
    {
        "name": "人民网-时政",
        "url": "http://www.people.com.cn/rss/politics.xml",
    },
    {
        "name": "人民网-国际",
        "url": "http://www.people.com.cn/rss/world.xml",
    },
    {
        "name": "人民网-财经",
        "url": "http://www.people.com.cn/rss/finance.xml",
    },
    {
        "name": "人民网-社会",
        "url": "http://www.people.com.cn/rss/society.xml",
    },
    {
        "name": "人民网-科技",
        "url": "http://www.people.com.cn/rss/tech.xml",
    },
    {
        "name": "人民网-教育",
        "url": "http://www.people.com.cn/rss/edu.xml",
    },
]

# -----------------------------------------------------------------------
# 反爬配置 —— 随机延时与请求头
# -----------------------------------------------------------------------
# 每次请求前的最小/最大等待秒数，防止短时间高频请求被封锁
# 使用列表包装以便在函数内修改（避免 global 声明问题）
_DELAY_RANGE = [1.5, 4.0]   # [最小秒数, 最大秒数]

# 每轮（抓取完所有频道后）的额外休息时间
ROUND_REST_MIN = 5
ROUND_REST_MAX = 10

# 模拟浏览器 User-Agent，降低被识别为爬虫的概率
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# -----------------------------------------------------------------------
# 数据清洗 —— 停用符号 / 正则
# -----------------------------------------------------------------------
# 需要过滤的冗余符号和空白字符
NOISE_PATTERN = re.compile(
    r"[\xa0\u3000\t"           # 不间断空格、全角空格、制表符
    r"\u200b\u200c\u200d"      # 零宽字符
    r"\r\n|\n|\r"               # 换行
    r"\[.*?\]"                  # [编辑：xxx] 这类编辑标注
    r"【.*?】"                  # 【xxx】方括号标注
    r"&#\d+;"                   # HTML 数字实体
    r"&[a-zA-Z]+;"              # HTML 命名实体 (如 &nbsp;)
    r"]+"
)

# 连续多余空白压缩为一个空格
MULTI_SPACE = re.compile(r" {2,}")

# -----------------------------------------------------------------------
# 数据库操作
# -----------------------------------------------------------------------
# 数据库路径：与 FastAPI 项目共用同一个 SQLite 文件
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "sentiment.db"


def get_connection():
    """
    获取 SQLite 数据库连接。
    启用 WAL 模式和外键约束，使用字典风格行访问。
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table_exists():
    """
    确保 raw_news 表已创建。
    爬虫可以独立于 FastAPI 运行，因此需要自行检查并创建表结构。
    """
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_news (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT    NOT NULL,
                content         TEXT    NOT NULL DEFAULT '',
                source_platform TEXT    NOT NULL,
                published_at    TEXT,
                original_url    TEXT    UNIQUE,
                crawled_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                status          TEXT    NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_news_url ON raw_news(original_url)")
        conn.commit()
    finally:
        conn.close()


def is_url_exists(url: str) -> bool:
    """检查 original_url 是否已存在数据库中，实现去重"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM raw_news WHERE original_url = ?", (url,)).fetchone()
        return row is not None
    finally:
        conn.close()


def is_title_exists(title: str) -> bool:
    """
    通过标题模糊匹配辅助去重。
    有些新闻 URL 可能略有差异（如末尾参数），但标题完全相同，需要二次校验。
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT 1 FROM raw_news WHERE title = ?", (title.strip(),)).fetchone()
        return row is not None
    finally:
        conn.close()


def save_news(title: str, content: str, source_platform: str,
              published_at: Optional[str], original_url: Optional[str]) -> bool:
    """
    将清洗后的新闻存入 raw_news 表。
    返回 True 表示成功写入，False 表示因冲突未写入。
    """
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO raw_news (title, content, source_platform, published_at, original_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, content, source_platform, published_at, original_url),
        )
        conn.commit()
        # 通过 changes 判断是否真的插入了新行
        return conn.total_changes > 0
    except Exception as e:
        logger.warning("入库异常: %s", e)
        return False
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 数据清洗工具函数
# -----------------------------------------------------------------------
def strip_html_tags(text: str) -> str:
    """
    去除 HTML / XML 标签，只保留纯文本内容。
    例如: '<p>这是<b>重要</b>新闻</p>' -> '这是重要新闻'
    """
    text = re.sub(r"<[^>]+>", "", text)       # 移除所有 <xxx> 标签
    text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)  # 移除 HTML 注释
    return text.strip()


def clean_noise_symbols(text: str) -> str:
    """
    过滤停用符号和冗余标记：
    - 不间断空格、全角空格、零宽字符
    - HTML 实体（如 &#160; &nbsp;）
    - [编辑：xxx]、【xxx】等编辑标注
    - 连续空白压缩
    """
    text = NOISE_PATTERN.sub(" ", text)
    text = MULTI_SPACE.sub(" ", text)
    return text.strip()


def normalize_datetime(raw_time: str) -> str:
    """
    将各种来源的时间格式统一转换为标准格式: YYYY-MM-DD HH:MM:SS
    支持的人民网 RSS 时间格式包括：
      - RFC 822 格式: "Mon, 08 Jul 2026 10:30:00 +0800"
      - ISO 8601 格式: "2026-07-08T10:30:00+08:00"
      - 中文格式: "2026年07月08日 10:30:00"
      - 简单格式: "2026-07-08 10:30:00"
    如果解析失败，返回当前时间。
    """
    if not raw_time or not raw_time.strip():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_time = raw_time.strip()

    # 尝试的时间解析格式列表（按常见程度排序）
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",     # RFC 822 (RSS 标准)
        "%a, %d %b %Y %H:%M:%S",        # RFC 822 无时区
        "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
        "%Y-%m-%dT%H:%M:%S",             # ISO 8601 无时区
        "%Y-%m-%d %H:%M:%S",             # 常见格式
        "%Y%m%d %H:%M:%S",              # 紧凑格式
        "%Y年%m月%d日 %H:%M:%S",          # 中文格式
        "%Y年%m月%d日",                    # 中文日期
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw_time, fmt)
            # 转换为本地时间（去掉时区信息）
            if dt.tzinfo is not None:
                import datetime as _dt
                dt = dt.astimezone(_dt.timezone.utc).astimezone()  # 转本地
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

    # 所有格式都解析失败，返回当前时间
    logger.debug("时间格式解析失败，使用当前时间: raw='%s'", raw_time)
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(text: str) -> str:
    """
    完整的文本清洗流程：
    1. 去除 HTML 标签
    2. 过滤停用符号
    3. 去除首尾空白
    """
    if not text:
        return ""
    text = strip_html_tags(text)
    text = clean_noise_symbols(text)
    return text.strip()


# -----------------------------------------------------------------------
# RSS 抓取核心
# -----------------------------------------------------------------------
def fetch_rss_feed(channel: Dict[str, str]) -> List[Dict[str, str]]:
    """
    抓取单个 RSS 频道，返回解析后的新闻条目列表。
    每条新闻是一个字典，包含 title, link, description, pubDate 字段。

    参数:
        channel: 包含 'name'（频道名）和 'url'（RSS地址）的字典

    返回:
        解析后的新闻列表，失败时返回空列表
    """
    url = channel["url"]
    channel_name = channel["name"]
    logger.info("正在抓取: %s (%s)", channel_name, url)

    # ---------- 发送 HTTP 请求 ----------
    req = Request(url, headers=HEADERS)
    try:
        response = urlopen(req, timeout=15)
    except HTTPError as e:
        logger.error("HTTP 错误 %s: %s %s", channel_name, e.code, url)
        return []
    except URLError as e:
        logger.error("网络错误 %s: %s %s", channel_name, e.reason, url)
        return []
    except Exception as e:
        logger.error("未知错误 %s: %s %s", channel_name, e, url)
        return []

    # ---------- 解析 XML ----------
    raw_xml = response.read()
    try:
        # 处理编码：RSS 常用 UTF-8，但也可能是 GB2312/GBK
        try:
            raw_xml = raw_xml.decode("utf-8")
        except UnicodeDecodeError:
            raw_xml = raw_xml.decode("gb2312", errors="ignore")

        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        logger.error("XML 解析失败 %s: %s", channel_name, e)
        return []

    # RSS 命名空间（部分人民网 RSS 使用默认命名空间）
    ns = {"rss": "http://purl.org/rss/1.0/"}

    news_list = []
    items = root.findall(".//item") or root.findall(".//{http://purl.org/rss/1.0/}item")

    for item in items:
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        date_el = item.find("pubDate")

        title = title_el.text if title_el is not None and title_el.text else ""
        link = link_el.text if link_el is not None and link_el.text else ""
        description = desc_el.text if desc_el is not None and desc_el.text else ""
        pub_date = date_el.text if date_el is not None and date_el.text else ""

        # 跳过标题为空的条目
        if not title.strip():
            continue

        news_list.append({
            "title": title,
            "link": link,
            "description": description,
            "pubDate": pub_date,
        })

    logger.info("%s: 获取到 %d 条新闻", channel_name, len(news_list))
    return news_list


# -----------------------------------------------------------------------
# 主抓取流程
# -----------------------------------------------------------------------
def crawl_channel(channel: Dict[str, str]) -> int:
    """
    抓取单个频道，执行清洗+去重+入库，返回新入库数量。
    """
    # 1. 抓取 RSS
    news_items = fetch_rss_feed(channel)
    if not news_items:
        return 0

    channel_name = channel["name"]
    new_count = 0
    duplicate_count = 0

    for item in news_items:
        # ---------- 2. 数据清洗 ----------
        title = clean_text(item["title"])
        content = clean_text(item["description"])
        published_at = normalize_datetime(item["pubDate"])
        original_url = item["link"].strip() if item["link"] else None

        # 跳过标题过短的条目（通常是广告或无效信息）
        if len(title) < 6:
            continue

        # ---------- 3. URL 去重 ----------
        if original_url and is_url_exists(original_url):
            duplicate_count += 1
            continue

        # ---------- 4. 标题去重（二次校验）----------
        if is_title_exists(title):
            duplicate_count += 1
            continue

        # ---------- 5. 入库 ----------
        if save_news(
            title=title,
            content=content,
            source_platform=channel_name,
            published_at=published_at,
            original_url=original_url,
        ):
            new_count += 1
            logger.info("  [入库] %s", title[:60])
        else:
            duplicate_count += 1

    logger.info(
        "%s 完成: 新增 %d 条, 重复/跳过 %d 条",
        channel_name, new_count, duplicate_count,
    )
    return new_count


def crawl_all(channels: Optional[List[Dict[str, str]]] = None) -> int:
    """
    抓取所有（或指定）频道，返回总新增数量。
    每个频道之间加入随机延时，防止被封禁。
    """
    if channels is None:
        channels = RSS_CHANNELS

    total_new = 0
    for i, channel in enumerate(channels):
        # 频道间的随机延时（第一个频道不需要等待）
        if i > 0:
            delay = random.uniform(_DELAY_RANGE[0], _DELAY_RANGE[1])
            logger.info("等待 %.1f 秒后抓取下一个频道...", delay)
            time.sleep(delay)

        new_count = crawl_channel(channel)
        total_new += new_count

    logger.info("=" * 60)
    logger.info("本轮抓取完成，共新增 %d 条新闻", total_new)
    logger.info("=" * 60)
    return total_new


def run_scheduled(interval_minutes: int, channels: Optional[List[Dict[str, str]]] = None):
    """
    定时循环抓取模式。
    每隔 interval_minutes 分钟执行一次全量抓取。

    参数:
        interval_minutes: 循环间隔（分钟）
        channels: 要抓取的频道列表，None 表示全部
    """
    logger.info("定时抓取模式启动，间隔: %d 分钟", interval_minutes)
    logger.info("频道数: %d", len(channels or RSS_CHANNELS))
    logger.info("按 Ctrl+C 停止")

    round_num = 0
    while True:
        try:
            round_num += 1
            logger.info("\n>>> 第 %d 轮抓取开始 (%s) <<<", round_num,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            crawl_all(channels)

            # 轮间休息
            rest = random.uniform(ROUND_REST_MIN, ROUND_REST_MAX)
            logger.info("本轮结束，休息 %.1f 秒...", rest)
            time.sleep(rest)

            # 等待到下一轮
            logger.info("等待 %d 分钟后开始下一轮...", interval_minutes)
            time.sleep(interval_minutes * 60)

        except KeyboardInterrupt:
            logger.info("收到停止信号，爬虫退出")
            break
        except Exception as e:
            logger.error("抓取过程中发生异常: %s", e)
            # 异常后等待一段时间再重试，避免频繁报错
            time.sleep(60)


# -----------------------------------------------------------------------
# CLI 入口 —— 可直接运行
# -----------------------------------------------------------------------
def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="人民网 RSS 新闻爬虫",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python crawler.py --once                       # 单次抓取所有频道
  python crawler.py --interval 30                 # 每30分钟抓取一次
  python crawler.py --once --channels politics,finance  # 只抓取指定频道
  python crawler.py --interval 60 --delay 3,8    # 自定义延时范围(秒)
        """,
    )

    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="单次抓取模式（抓完即退出）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="定时抓取间隔，单位分钟（默认30分钟）",
    )
    parser.add_argument(
        "--channels",
        type=str,
        default=None,
        help="指定频道，逗号分隔，可选: politics,world,finance,society,tech,edu",
    )
    parser.add_argument(
        "--delay",
        type=str,
        default=None,
        help="自定义请求延时范围，格式: 最小,最大（秒），如 2,6",
    )

    return parser.parse_args()


def resolve_channels(channel_names: Optional[str]) -> Optional[List[Dict[str, str]]]:
    """
    将命令行的频道名称映射到 RSS 频道配置。
    支持的名称: politics, world, finance, society, tech, edu
    """
    if channel_names is None:
        return None  # 返回 None 表示抓取全部频道

    name_map = {
        "politics": "人民网-时政",
        "world": "人民网-国际",
        "finance": "人民网-财经",
        "society": "人民网-社会",
        "tech": "人民网-科技",
        "edu": "人民网-教育",
    }

    requested = [n.strip() for n in channel_names.split(",") if n.strip()]
    selected = []
    for name in requested:
        if name in name_map:
            # 查找匹配的频道配置
            for ch in RSS_CHANNELS:
                if ch["name"] == name_map[name]:
                    selected.append(ch)
                    break
        else:
            logger.warning("未知频道名称: %s（可选: %s）", name, ", ".join(name_map.keys()))

    if not selected:
        logger.error("没有匹配到任何有效频道，将抓取所有频道")
        return None

    logger.info("已选择频道: %s", [ch["name"] for ch in selected])
    return selected


if __name__ == "__main__":
    args = parse_args()

    # 解析频道选择
    channels = resolve_channels(args.channels)

    # 解析自定义延时
    if args.delay:
        parts = args.delay.split(",")
        if len(parts) == 2:
            _DELAY_RANGE[0] = float(parts[0])
            _DELAY_RANGE[1] = float(parts[1])
            logger.info("自定义延时: %.1f ~ %.1f 秒", _DELAY_RANGE[0], _DELAY_RANGE[1])

    # 确保数据库表存在
    ensure_table_exists()
    logger.info("数据库就绪: %s", DB_PATH)

    # 执行抓取
    if args.once:
        # 单次模式：抓完即退出
        total = crawl_all(channels)
        logger.info("单次抓取完成，共新增 %d 条新闻。", total)
        # ========== 兼容提示 ==========
        print("\n" + "=" * 60)
        print("提示：爬虫已迁移至模块化架构 (crawler/ 目录)")
        print("推荐使用新版命令：")
        print("  python -m crawler.cli --once                  # 单次抓取所有平台")
        print("  python -m crawler.cli --platform weibo --once  # 指定平台抓取")
        print("  python -m crawler.cli --interval 30           # 定时循环抓取")
        print("=" * 60)
        sys.exit(0)
    else:
        # 定时模式：循环抓取
        run_scheduled(interval_minutes=args.interval, channels=channels)
        # ========== 兼容提示 ==========
        print("\n" + "=" * 60)
        print("提示：爬虫已迁移至模块化架构 (crawler/ 目录)")
        print("推荐使用新版命令：")
        print("  python -m crawler.cli --once                  # 单次抓取所有平台")
        print("  python -m crawler.cli --platform weibo --once  # 指定平台抓取")
        print("  python -m crawler.cli --interval 30           # 定时循环抓取")
        print("=" * 60)
