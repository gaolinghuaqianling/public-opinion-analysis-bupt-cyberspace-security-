# -*- coding: utf-8 -*-
"""
人民网 RSS 适配器

复用原有 crawler.py 中的 RSS 抓取逻辑，封装为统一的适配器接口。
本适配器特点：
  - 使用同步的 urllib 进行 RSS 采集（因为 RSS 是简单的 XML，无需异步）
  - 将同步调用包装为 async 接口以符合适配器基类规范
  - 复用原有的 XML 解析和数据清洗逻辑
  - 支持 6 个频道：时政/国际/财经/社会/科技/教育

数据来源：
  人民网 RSS 订阅源（公开接口，无需鉴权）
  - 时政: http://www.people.com.cn/rss/politics.xml
  - 国际: http://www.people.com.cn/rss/world.xml
  - 财经: http://www.people.com.cn/rss/finance.xml
  - 社会: http://www.people.com.cn/rss/society.xml
  - 科技: http://www.people.com.cn/rss/tech.xml
  - 教育: http://www.people.com.cn/rss/edu.xml
"""

import re
import time
import random
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask


class PeopleRSSAdapter(BaseAdapter):
    """
    人民网 RSS 适配器

    通过人民网公开 RSS 订阅源获取新闻数据。
    数据采集使用同步 HTTP 请求（urllib），但对外提供 async 接口。
    """

    platform_name = "人民网"
    platform_key = "people_rss"
    supported_task_types = ["rss", "keyword", "hotlist"]

    # -------------------------------------------------------------------
    # RSS 频道配置 —— 人民网 6 个主要频道
    # -------------------------------------------------------------------
    # name: 频道显示名称，用于 CrawledItem.source_platform
    # url: 频道 RSS 地址
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

    # -------------------------------------------------------------------
    # 反爬配置：请求头与延时
    # -------------------------------------------------------------------
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

    # 每次请求前的最小/最大等待秒数（频道间延时）
    _DELAY_RANGE = (1.5, 4.0)

    # -------------------------------------------------------------------
    # 数据清洗正则（复用原有逻辑）
    # -------------------------------------------------------------------
    # 需要过滤的冗余符号和空白字符
    NOISE_PATTERN = re.compile(
        r"[\xa0\u3000\t"           # 不间断空格、全角空格、制表符
        r"\u200b\u200c\u200d"      # 零宽字符
        r"\r\n|\n|\r"               # 换行
        r"\[.*?\]"                  # [编辑：xxx] 编辑标注
        r"【.*?】"                  # 【xxx】方括号标注
        r"&#\d+;"                   # HTML 数字实体
        r"&[a-zA-Z]+;"              # HTML 命名实体 (如 &nbsp;)
        r"]+"
    )

    # 连续多余空白压缩为一个空格
    MULTI_SPACE = re.compile(r" {2,}")

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行抓取任务，根据 task_type 分发到对应方法。

        支持的任务类型：
          - "rss"     : 抓取所有 RSS 频道的最新新闻
          - "hotlist" : 等同于 rss，抓取所有频道
          - "keyword" : 按 task.keyword 从 RSS 数据中过滤相关新闻

        参数:
            task: 抓取任务对象

        返回:
            标准化后的 CrawledItem 列表
        """
        task_type = task.task_type

        if task_type in ("rss", "hotlist"):
            # 抓取所有频道的热门新闻
            items = await self.crawl_hotlist()
            # 如果任务中指定了关键词，进行二次过滤
            if task.keywords:
                items = self.filter_by_keywords(items, task.keywords)
            return items

        elif task_type == "keyword":
            if not task.target:
                self.logger.warning("关键词任务未指定 target，返回空列表")
                return []
            return await self.crawl_by_keyword(task.target)

        else:
            self.logger.error(f"不支持的任务类型: {task_type}")
            return []

    async def crawl_hotlist(self) -> List[CrawledItem]:
        """
        爬取人民网各频道最新新闻（遍历所有 RSS 频道）。

        实现说明：
          - 同步抓取所有 6 个频道
          - 每个频道之间加入随机延时防止被封
          - 最终返回合并去重后的 CrawledItem 列表

        返回:
            所有频道的最新新闻列表
        """
        self.logger.info("开始抓取人民网全频道 RSS 热榜")
        all_items = []

        for i, channel in enumerate(self.RSS_CHANNELS):
            # 频道间的随机延时（第一个频道不需要等待）
            if i > 0:
                delay = random.uniform(*self._DELAY_RANGE)
                self.logger.debug(f"等待 {delay:.1f}s 后抓取下一个频道...")
                await self._async_sleep(delay)

            items = await self._fetch_channel_async(channel)
            all_items.extend(items)

        # 去重：按 original_url
        seen_urls = set()
        unique_items = []
        for item in all_items:
            if item.original_url and item.original_url in seen_urls:
                continue
            if item.original_url:
                seen_urls.add(item.original_url)
            unique_items.append(item)

        self.logger.info(f"人民网 RSS 热榜抓取完成，共 {len(unique_items)} 条（去重后）")
        return unique_items

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        从 RSS 数据中过滤包含指定关键词的新闻。

        实现说明：
          - 先抓取所有频道数据
          - 在抓取结果中按关键词过滤（标题或正文包含关键词）

        参数:
            keyword: 搜索关键词

        返回:
            包含关键词的新闻列表
        """
        self.logger.info(f"人民网 RSS 关键词搜索: {keyword}")

        # 先获取全部数据
        all_items = await self.crawl_hotlist()

        # 按关键词过滤
        filtered = self.filter_by_keywords(all_items, [keyword])

        self.logger.info(f"关键词 '{keyword}' 匹配到 {len(filtered)} 条新闻")
        return filtered

    # -------------------------------------------------------------------
    # RSS 抓取核心方法
    # -------------------------------------------------------------------

    def _fetch_channel_sync(self, channel: Dict[str, str]) -> List[CrawledItem]:
        """
        同步抓取单个 RSS 频道（内部方法）。

        参数:
            channel: 包含 'name'（频道名）和 'url'（RSS地址）的字典

        返回:
            该频道的 CrawledItem 列表

        RSS XML 数据格式说明（标准 RSS 2.0）：
          <rss>
            <channel>
              <item>
                <title>新闻标题</title>
                <link>新闻链接</link>
                <description>新闻摘要（可能含HTML标签）</description>
                <pubDate>发布时间（RFC 822格式）</pubDate>
              </item>
              ...
            </channel>
          </rss>
        """
        url = channel["url"]
        channel_name = channel["name"]
        self.logger.info(f"正在抓取: {channel_name} ({url})")

        # ---------- 发送 HTTP 请求 ----------
        req = Request(url, headers=self.HEADERS)
        try:
            response = urlopen(req, timeout=15)
        except HTTPError as e:
            self.logger.error(f"HTTP 错误 {channel_name}: {e.code} {url}")
            return []
        except URLError as e:
            self.logger.error(f"网络错误 {channel_name}: {e.reason} {url}")
            return []
        except Exception as e:
            self.logger.error(f"未知错误 {channel_name}: {e} {url}")
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
            self.logger.error(f"XML 解析失败 {channel_name}: {e}")
            return []

        # ---------- 提取新闻条目 ----------
        items = root.findall(".//item") or root.findall(".//{http://purl.org/rss/1.0/}item")

        crawled_items = []
        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            date_el = item.find("pubDate")

            raw_title = title_el.text if title_el is not None and title_el.text else ""
            raw_link = link_el.text if link_el is not None and link_el.text else ""
            raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""
            raw_date = date_el.text if date_el is not None and date_el.text else ""

            # 跳过标题为空的条目
            if not raw_title.strip():
                continue

            # ---------- 数据清洗（复用原有清洗逻辑）----------
            title = self._clean_text(raw_title)
            content = self._clean_text(raw_desc)
            published_at = self._normalize_datetime(raw_date)
            original_url = raw_link.strip() if raw_link else ""

            # 跳过标题过短的条目（通常是广告或无效信息）
            if len(title) < 6:
                continue

            # ---------- 构造标准化的 CrawledItem ----------
            crawled_item = CrawledItem(
                title=title,
                content=content,
                source_platform=f"人民网-{channel_name.split('-')[-1]}" if '-' in channel_name else channel_name,
                original_url=original_url,
                published_at=published_at,
                is_public=True,  # 人民网新闻均为公开内容
                interaction_data={},  # RSS 无互动数据
            )
            crawled_items.append(crawled_item)

        self.logger.info(f"{channel_name}: 获取到 {len(crawled_items)} 条新闻")
        return crawled_items

    async def _fetch_channel_async(self, channel: Dict[str, str]) -> List[CrawledItem]:
        """
        异步包装：将同步的频道抓取方法包装为 async 接口。

        使用 asyncio 事件循环在单独线程中运行同步的 urllib 调用，
        避免阻塞事件循环。

        参数:
            channel: 频道配置字典

        返回:
            该频道的 CrawledItem 列表
        """
        import asyncio
        loop = asyncio.get_event_loop()

        # 在线程池中执行同步的 RSS 抓取
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(
                pool,
                self._fetch_channel_sync,
                channel,
            )
        return result

    # -------------------------------------------------------------------
    # 数据清洗工具方法（复用 crawler.py 中的清洗逻辑）
    # -------------------------------------------------------------------

    def _strip_html_tags(self, text: str) -> str:
        """
        去除 HTML / XML 标签，只保留纯文本内容。
        例如: '<p>这是<b>重要</b>新闻</p>' -> '这是重要新闻'
        """
        text = re.sub(r"<[^>]+>", "", text)       # 移除所有 <xxx> 标签
        text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)  # 移除 HTML 注释
        return text.strip()

    def _clean_noise_symbols(self, text: str) -> str:
        """
        过滤停用符号和冗余标记（不间断空格、零宽字符、HTML实体等）。
        """
        text = self.NOISE_PATTERN.sub(" ", text)
        text = self.MULTI_SPACE.sub(" ", text)
        return text.strip()

    def _clean_text(self, text: str) -> str:
        """
        完整的文本清洗流程：去HTML标签 -> 过滤停用符号 -> 去空白
        """
        if not text:
            return ""
        text = self._strip_html_tags(text)
        text = self._clean_noise_symbols(text)
        return text.strip()

    def _normalize_datetime(self, raw_time: str) -> str:
        """
        将各种来源的时间格式统一转换为标准格式: YYYY-MM-DD HH:MM:SS。

        支持的人民网 RSS 时间格式：
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
                    dt = dt.astimezone()
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

        # 所有格式都解析失败，返回当前时间
        self.logger.debug(f"时间格式解析失败，使用当前时间: raw='{raw_time}'")
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # -------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------

    @staticmethod
    async def _async_sleep(seconds: float):
        """异步等待指定秒数"""
        import asyncio
        await asyncio.sleep(seconds)
