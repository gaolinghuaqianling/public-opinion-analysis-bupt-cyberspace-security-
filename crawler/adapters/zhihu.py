# -*- coding: utf-8 -*-
"""
知乎适配器

三层采集架构，优先级从高到低：
  1. API 层  : 知乎开放平台 API（预留接口，需要 OAuth 鉴权）
  2. 轻量层  : 知乎公开 JSON API，部分接口无需登录即可访问
  3. 浏览器层: Playwright 无头浏览器，采集需要完整渲染的问答页面

合规约束：
  - 仅采集公开可见内容，不使用任何账号登录凭证
  - 不绕过任何反爬机制（不伪造 Cookie、不绕过频率限制）
  - 请求间隔 >= 3 秒，遵守知乎 API 频率限制
  - 仅采集公开问答的标题和摘要，不采集完整回答（避免过度采集）

公开接口说明：
  - 热榜 API: https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50
    无需登录，返回知乎全站热榜
    数据格式: {"data":[{"target":{"title":"问题标题","excerpt":"摘要","id":"问题ID"},...}]}
  - 搜索 API: https://www.zhihu.com/api/v4/search_v3?t=general&q=关键词&correction=1
    无需登录，返回搜索结果
    数据格式: {"data":[{...},...]}
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask


class ZhihuAdapter(BaseAdapter):
    """
    知乎适配器（三层采集逻辑）

    采集策略：
      - 热榜：优先使用知乎热榜公开 API（轻量层），降级到 Playwright
      - 关键词搜索：优先使用搜索 API，降级到 Playwright
      - 账号采集：当前不支持（知乎无公开用户 API）
    """

    platform_name = "知乎"
    platform_key = "zhihu"
    supported_task_types = ["hotlist", "keyword"]

    # -------------------------------------------------------------------
    # 请求配置
    # -------------------------------------------------------------------
    # 合规约束：请求间隔 >= 3 秒
    REQUEST_INTERVAL = 3.0  # 请求最小间隔（秒）

    # HTTP 请求头
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.zhihu.com/",
        # 知乎 API 需要设置 X-Requested-With 头
        "X-Requested-With": "XMLHttpRequest",
    }

    # -------------------------------------------------------------------
    # 接口 URL 配置
    # -------------------------------------------------------------------

    # 热榜公开 API（轻量层，无需登录）
    # 参数: limit=50（条目数量）
    # 返回知乎全站热榜数据
    # 注意：该接口自 2025 年起需要登录鉴权，返回 401，已不可用
    # 备用方案：使用 top_search 接口（见 TOP_SEARCH_API_URL）
    HOTLIST_API_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit={limit}"

    # 热搜词条 API（轻量层备用方案，无需登录）
    # 返回知乎热搜词条列表（约 10 条），数据结构: {"top_search":{"words":[{"query":"词条","display_query":"展示词"}]}}
    # 该接口稳定可用，可作为热榜 API 不可用时的降级数据源
    TOP_SEARCH_API_URL = "https://www.zhihu.com/api/v4/search/top_search?limit=50"

    # 搜索公开 API（轻量层，无需登录）
    # 参数:
    #   t=general     : 搜索类型（综合）
    #   q=关键词      : 搜索关键词
    #   correction=1  : 启用纠错
    #   offset=0      : 分页偏移
    #   limit=20      : 每页数量
    SEARCH_API_URL = (
        "https://www.zhihu.com/api/v4/search_v3?"
        "t=general&q={keyword}&correction=1&offset={offset}&limit={limit}"
    )

    # 热榜页面 URL（浏览器层备用）
    HOTLIST_PAGE_URL = "https://www.zhihu.com/hot"

    # 搜索页面 URL（浏览器层备用）
    SEARCH_PAGE_URL = "https://www.zhihu.com/search?type=content&q={keyword}"

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行知乎抓取任务，根据 task_type 分发到对应方法。

        支持的任务类型：
          - "hotlist" : 抓取知乎热榜
          - "keyword" : 按关键词搜索公开问答

        参数:
            task: 抓取任务对象

        返回:
            标准化后的 CrawledItem 列表
        """
        task_type = task.task_type

        if task_type == "hotlist":
            items = await self.crawl_hotlist()
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
        爬取知乎热榜（使用公开 API）。

        实现策略：
          1. 轻量层：调用知乎热榜公开 API
             URL: https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50
             无需登录，直接返回 JSON 数据
          2. 浏览器层：使用 Playwright 打开热榜页面
             URL: https://www.zhihu.com/hot

        热榜 API 返回数据格式（JSON）：
          {
            "data": [
              {
                "target": {
                  "id": "问题ID",
                  "title": "问题标题",
                  "excerpt": "问题摘要（前几十字）",
                  "type": "answer"
                },
                "detail_text": "热榜描述",
                "children": [...]
              },
              ...
            ],
            "paging": {
              "total": 50,
              "is_end": true
            }
          }

        返回:
            知乎热榜问题列表
        """
        self.logger.info("开始抓取知乎热榜")

        # ---------- 第一优先级：轻量层（公开 API）----------
        items = await self._fetch_hotlist_by_api()

        if items:
            self.logger.info(f"知乎热榜（API层）获取成功，共 {len(items)} 条")
            return items

        # ---------- 第二优先级：轻量层备用（top_search 接口）----------
        # 热榜 API 需要 401 鉴权后，降级到 top_search 接口获取热搜词条
        items = await self._fetch_hotlist_by_top_search()

        if items:
            self.logger.info(f"知乎热榜（top_search备用接口）获取成功，共 {len(items)} 条")
            return items

        # ---------- 第三优先级：浏览器层（Playwright 降级）----------
        self.logger.info("API 接口不可用，降级到浏览器层获取热榜")
        items = await self._fetch_hotlist_by_playwright()

        if items:
            self.logger.info(f"知乎热榜（浏览器层）获取成功，共 {len(items)} 条")
        else:
            self.logger.warning("知乎热榜抓取失败，所有层级均不可用")

        return items

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索知乎公开内容。

        实现策略（优先级从高到低）：
          1. 轻量层：调用知乎搜索公开 API
             URL: https://www.zhihu.com/api/v4/search_v3?t=general&q=关键词
          2. 浏览器层：使用 Playwright 打开搜索页
             URL: https://www.zhihu.com/search?type=content&q=关键词

        合规约束：
          - 仅采集公开问答的标题和摘要
          - 不采集完整回答内容（避免过度采集）
          - 请求间隔 >= 3 秒

        参数:
            keyword: 搜索关键词

        返回:
            匹配关键词的公开问答列表

        搜索 API 返回数据格式（JSON）：
          {
            "data": [
              {
                "type": "search_result",
                "object": {
                  "type": "answer",
                  "question": {
                    "title": "问题标题",
                    "id": "问题ID"
                  },
                  "excerpt": "回答摘要",
                  "created_time": 1234567890,
                  "author": {"name": "作者名"},
                  "voteup_count": 100
                },
                "highlight": {
                  "title": "高亮标题",
                  "content": "高亮内容"
                }
              },
              ...
            ],
            "paging": {
              "total": 100,
              "is_end": false
            }
          }
        """
        self.logger.info(f"知乎关键词搜索: {keyword}")

        # ---------- 第一优先级：轻量层（搜索 API）----------
        items = await self._search_by_api(keyword)

        if items:
            self.logger.info(f"知乎搜索（API层）命中 {len(items)} 条结果")
            return items

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("API 接口不可用，降级到浏览器层搜索")
        items = await self._search_by_playwright(keyword)

        if items:
            self.logger.info(f"知乎搜索（浏览器层）命中 {len(items)} 条结果")
        else:
            self.logger.warning(f"知乎关键词搜索无结果: {keyword}")

        return items

    # -------------------------------------------------------------------
    # 轻量层：公开 API 实现
    # -------------------------------------------------------------------

    async def _fetch_hotlist_by_api(self) -> List[CrawledItem]:
        """
        通过知乎热榜公开 API 获取热榜数据。

        接口: https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50

        无需登录，直接 HTTP GET 请求即可获取数据。

        返回:
            热榜问题列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            url = self.HOTLIST_API_URL.format(limit=50)
            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"知乎热榜 API 返回状态码: {resp.status}，降级到浏览器层")
                        return []

                    data = await resp.json()
        except ImportError:
            self.logger.warning("aiohttp 不可用")
            return []
        except Exception as e:
            self.logger.warning(f"知乎热榜 API 请求失败: {e}，降级到浏览器层")
            return []

        # 解析热榜数据
        hot_list = data.get("data", [])
        if not hot_list:
            self.logger.warning("知乎热榜 API 返回空列表")
            return []

        items = []
        for idx, entry in enumerate(hot_list):
            try:
                target = entry.get("target", {})
                title = target.get("title", "").strip()
                if not title:
                    continue

                # 问题摘要（excerpt 可能为空）
                excerpt = target.get("excerpt", "")
                question_id = target.get("id", "")

                # 热榜排名（从索引推导）
                rank = idx + 1

                crawled_item = CrawledItem(
                    title=title,
                    content=excerpt if excerpt else "",  # 摘要作为正文
                    source_platform="知乎",
                    original_url=f"https://www.zhihu.com/question/{question_id}" if question_id else "",
                    published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    is_public=True,
                    interaction_data={
                        "rank": rank,                 # 热榜排名
                        "question_id": question_id,   # 问题 ID
                        "detail_text": entry.get("detail_text", ""),
                        "source": "hotlist_api",      # 数据来源标识
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析知乎热榜条目失败: {e}")
                continue

        return items

    async def _fetch_hotlist_by_top_search(self) -> List[CrawledItem]:
        """
        通过知乎 top_search 备用接口获取热搜词条。

        接口: https://www.zhihu.com/api/v4/search/top_search?limit=50

        该接口返回知乎热搜词条（约 10 条），数据结构:
          {"top_search":{"words":[{"query":"词条","display_query":"展示词","uuid":"xxx"}]}}

        与热榜 API 不同，该接口仅返回词条文本，无热度值和问题详情。
        当热榜 API 返回 401 时作为降级方案使用。

        返回:
            热搜词条列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(
                    self.TOP_SEARCH_API_URL,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"知乎 top_search 接口返回状态码: {resp.status}")
                        return []

                    data = await resp.json()
        except ImportError:
            self.logger.warning("aiohttp 不可用")
            return []
        except Exception as e:
            self.logger.warning(f"知乎 top_search 接口请求失败: {e}")
            return []

        # 解析热搜词条
        words = data.get("top_search", {}).get("words", [])
        if not words:
            self.logger.warning("知乎 top_search 接口返回空列表")
            return []

        items = []
        for idx, word_info in enumerate(words):
            try:
                display_query = word_info.get("display_query", "").strip()
                if not display_query:
                    continue

                query = word_info.get("query", display_query)

                crawled_item = CrawledItem(
                    title=display_query,
                    content="",  # 热搜词条无正文
                    source_platform="知乎",
                    original_url=f"https://www.zhihu.com/search?type=content&q={query}",
                    published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    is_public=True,
                    interaction_data={
                        "rank": idx + 1,
                        "query": query,
                        "uuid": word_info.get("uuid", ""),
                        "source": "top_search_api",  # 数据来源标识
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析知乎 top_search 条目失败: {e}")
                continue

        return items

    async def _search_by_api(self, keyword: str) -> List[CrawledItem]:
        """
        通过知乎搜索公开 API 搜索关键词。

        接口: https://www.zhihu.com/api/v4/search_v3?t=general&q=关键词

        参数:
            keyword: 搜索关键词

        返回:
            搜索结果列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            url = self.SEARCH_API_URL.format(
                keyword=keyword,
                offset=0,
                limit=20,
            )
            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"知乎搜索 API 返回状态码: {resp.status}")
                        return []

                    data = await resp.json()
        except ImportError:
            return []
        except Exception as e:
            self.logger.warning(f"知乎搜索 API 请求失败: {e}")
            return []

        # 解析搜索结果
        return self._parse_search_results(data)

    def _parse_search_results(self, data: dict) -> List[CrawledItem]:
        """
        解析知乎搜索 API 返回的 JSON 数据。

        数据格式说明：
          data 是一个列表，每个元素包含：
            - type: 类型标识（如 "search_result"）
            - object: 搜索对象
              - type: 对象类型（"answer"=回答, "question"=问题, "article"=文章）
              - question.title: 问题标题（当 type="answer" 时）
              - question.id: 问题 ID
              - excerpt: 摘要文本
              - created_time: 创建时间（Unix 时间戳，毫秒）
              - author.name: 作者名称
              - voteup_count: 赞同数
            - highlight: 高亮信息（关键词高亮标记）

        参数:
            data: 搜索 API 返回的 JSON 数据

        返回:
            CrawledItem 列表
        """
        items = []

        search_data = data.get("data", [])
        if not search_data:
            return items

        for entry in search_data:
            obj = entry.get("object", {})
            if not obj:
                continue

            try:
                obj_type = obj.get("type", "")

                # 根据对象类型提取信息
                if obj_type == "answer":
                    # 回答类型：提取问题标题 + 回答摘要
                    question = obj.get("question", {})
                    title = question.get("title", "未知问题")
                    question_id = question.get("id", "")
                    excerpt = obj.get("excerpt", "")
                    author = obj.get("author", {}).get("name", "匿名用户")
                    votes = obj.get("voteup_count", 0)
                    original_url = f"https://www.zhihu.com/question/{question_id}" if question_id else ""

                elif obj_type == "question":
                    # 问题类型：提取问题标题和描述
                    title = obj.get("title", "未知问题")
                    question_id = obj.get("id", "")
                    excerpt = obj.get("excerpt", "")
                    author = ""
                    votes = obj.get("voteup_count", 0)
                    original_url = f"https://www.zhihu.com/question/{question_id}" if question_id else ""

                elif obj_type == "article":
                    # 文章类型：提取文章标题和摘要
                    title = obj.get("title", "未知文章")
                    article_id = obj.get("id", "")
                    excerpt = obj.get("excerpt", "")
                    author = obj.get("author", {}).get("name", "匿名用户")
                    votes = obj.get("voteup_count", 0)
                    original_url = f"https://zhuanlan.zhihu.com/p/{article_id}" if article_id else ""

                else:
                    # 其他类型，跳过
                    continue

                if not title.strip():
                    continue

                # 解析时间（知乎时间戳为毫秒）
                created_time = obj.get("created_time", 0)
                if created_time:
                    # 知乎时间戳可能是毫秒或秒
                    if created_time > 1e12:
                        created_time = created_time / 1000  # 毫秒转秒
                    published_at = datetime.fromtimestamp(created_time).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 清洗摘要文本
                excerpt_clean = self._clean_excerpt(excerpt)

                crawled_item = CrawledItem(
                    title=title,
                    content=excerpt_clean,
                    source_platform="知乎",
                    original_url=original_url,
                    published_at=published_at,
                    is_public=True,
                    interaction_data={
                        "author": author,
                        "votes": votes,
                        "type": obj_type,
                        "source": "search_api",
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析知乎搜索结果条目失败: {e}")
                continue

        return items

    # -------------------------------------------------------------------
    # 浏览器层：Playwright 实现
    # -------------------------------------------------------------------

    async def _fetch_hotlist_by_playwright(self) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器获取知乎热榜（降级方案）。

        实现说明：
          - 打开热榜页面 https://www.zhihu.com/hot
          - 等待页面 JS 渲染完成
          - 从页面 DOM 中提取热榜问题标题和热度

        合规约束：
          - 仅采集公开热榜信息
          - 不登录
          - 请求间隔 >= 3 秒

        异常:
            NotImplementedError: 当 Playwright 未安装时抛出
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright 未安装")
            raise NotImplementedError("Playwright 未安装")

        items = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(self.HOTLIST_PAGE_URL, wait_until="domcontentloaded", timeout=30000)

                # 等待热榜列表加载
                await asyncio.sleep(self.REQUEST_INTERVAL + 2)

                # 知乎热榜页面选择器
                # 热榜条目通常是 <div class="HotItem"> 或类似结构
                hot_items = await page.query_selector_all(".HotItem, [class*='hot-item'], .HotList-item")

                for idx, hot_item in enumerate(hot_items):
                    try:
                        # 提取问题标题
                        title_el = await hot_item.query_selector(".HotItem-title, h2, a[class*='title']")
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        title = title.strip()
                        if not title:
                            continue

                        # 提取热度描述（如 "1234 万热度"）
                        heat_el = await hot_item.query_selector(".HotItem-metrics, [class*='hot-metrics'], .HotItem-excerpt")
                        heat_text = await heat_el.inner_text() if heat_el else "0"
                        heat_match = re.search(r"([\d.]+)\s*万?", heat_text)
                        if heat_match:
                            heat_num = float(heat_match.group(1))
                            if "万" in heat_text:
                                heat_num *= 10000
                            heat_value = int(heat_num)
                        else:
                            heat_value = 0

                        # 尝试提取链接
                        link_el = await hot_item.query_selector("a[href*='question']")
                        link_href = await link_el.get_attribute("href") if link_el else ""
                        original_url = link_href if link_href.startswith("http") else f"https://www.zhihu.com{link_href}"

                        crawled_item = CrawledItem(
                            title=title,
                            content="",  # 热榜列表仅展示标题
                            source_platform="知乎",
                            original_url=original_url,
                            published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            is_public=True,
                            interaction_data={
                                "rank": idx + 1,
                                "heat": heat_value,
                                "source": "playwright_hotlist",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析知乎热榜条目失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    async def _search_by_playwright(self, keyword: str) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器进行知乎搜索（降级方案）。

        实现说明：
          - 打开搜索页 https://www.zhihu.com/search?type=content&q={keyword}
          - 等待搜索结果渲染
          - 提取问题标题和回答摘要

        合规约束：
          - 仅采集标题和摘要，不采集完整回答
          - 不滚动加载更多
          - 请求间隔 >= 3 秒

        参数:
            keyword: 搜索关键词

        返回:
            搜索结果列表

        异常:
            NotImplementedError: 当 Playwright 未安装时抛出
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright 未安装")
            raise NotImplementedError("Playwright 未安装")

        items = []
        url = self.SEARCH_PAGE_URL.format(keyword=keyword)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # 等待搜索结果加载
                await asyncio.sleep(self.REQUEST_INTERVAL + 3)

                # 知乎搜索结果选择器
                results = await page.query_selector_all(
                    ".SearchResult-Card, .ContentItem, [class*='search-result'], .List-item"
                )

                for result in results:
                    try:
                        # 提取问题标题
                        title_el = await result.query_selector(
                            ".ContentItem-title, h2, [class*='title'] a"
                        )
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        title = title.strip()
                        if not title:
                            continue

                        # 提取摘要/片段
                        excerpt_el = await result.query_selector(
                            ".content, .RichContent-inner, [class*='excerpt'], .Highlight"
                        )
                        excerpt = await excerpt_el.inner_text() if excerpt_el else ""
                        excerpt = excerpt.strip()[:500]  # 限制摘要长度

                        # 提取链接
                        link_el = await result.query_selector("a[href]")
                        link_href = await link_el.get_attribute("href") if link_el else ""
                        original_url = link_href if link_href.startswith("http") else f"https://www.zhihu.com{link_href}"

                        # 提取作者
                        author_el = await result.query_selector(".AuthorInfo-name, [class*='author']")
                        author = await author_el.inner_text() if author_el else "匿名用户"

                        crawled_item = CrawledItem(
                            title=title,
                            content=self._clean_excerpt(excerpt),
                            source_platform="知乎",
                            original_url=original_url,
                            published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            is_public=True,
                            interaction_data={
                                "author": author,
                                "source": "playwright_search",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析知乎搜索结果失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    # -------------------------------------------------------------------
    # 数据处理工具方法
    # -------------------------------------------------------------------

    @staticmethod
    def _clean_excerpt(text: str) -> str:
        """
        清洗知乎摘要文本。

        处理内容：
          - 去除 HTML 标签
          - 去除知乎特有的 "查看全部"、"展开阅读" 等提示文字
          - 去除多余空白

        参数:
            text: 原始摘要文本

        返回:
            清洗后的纯文本
        """
        if not text:
            return ""

        # 去除 HTML 标签
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)

        # 去除知乎特有的提示文字
        noise_patterns = [
            r"查看全部",
            r"展开阅读",
            r"收起",
            r"显示全部",
            r"​",              # 零宽字符
            r"\s{3,}",         # 连续3个以上空白
        ]
        for pattern in noise_patterns:
            text = re.sub(pattern, "", text)

        return text.strip()

    # -------------------------------------------------------------------
    # API 层预留接口
    # -------------------------------------------------------------------

    async def _fetch_by_official_api(self, endpoint: str, params: dict = None) -> dict:
        """
        知乎开放平台 API 调用（预留接口）。

        使用说明：
          - 需要在配置中设置知乎开放平台凭证
          - 需要通过 OAuth 2.0 获取 access_token
          - 当前为预留空实现

        参数:
            endpoint: API 端点路径
            params: 请求参数

        异常:
            NotImplementedError: 当前未实现
        """
        # TODO: 待接入知乎开放平台 API
        # 需要配置:
        #   - ZHIHU_APP_KEY: 应用 App Key
        #   - ZHIHU_APP_SECRET: 应用 App Secret
        #   - ZHIHU_ACCESS_TOKEN: OAuth 访问令牌
        self.logger.warning("知乎官方 API 接口暂未实现")
        raise NotImplementedError("知乎官方 API 接口待开发")
