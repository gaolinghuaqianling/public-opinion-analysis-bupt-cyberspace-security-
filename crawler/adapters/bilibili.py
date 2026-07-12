# -*- coding: utf-8 -*-
"""
B站（哔哩哔哩）适配器

三层采集架构，优先级从高到低：
  1. API 层  : B站开放平台 API（预留接口，需要开发者账号）
  2. 轻量层  : B站公开 Web API，无需鉴权即可访问部分接口
  3. 浏览器层: Playwright 无头浏览器，采集需要 JS 渲染的页面

合规约束：
  - 仅采集公开可见内容，不使用任何账号登录凭证
  - 不绕过任何反爬机制
  - 请求间隔 >= 3 秒，遵守 B站 API 频率限制
  - 仅采集视频标题、描述等公开信息，不下载视频内容

公开接口说明：
  - 全站热门 API:
    URL: https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all
    无需登录，返回全站热门视频列表
    数据格式: {"data":{"list":[{"title":"标题","desc":"描述","pic":"封面","owner":{"name":"UP主"},...}]}}

  - 搜索 API:
    URL: https://api.bilibili.com/x/web-interface/search/all/v2?keyword=xxx
    参数: keyword=搜索关键词
    数据格式: {"data":{"result":[...]}}
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask


class BilibiliAdapter(BaseAdapter):
    """
    B站适配器（三层采集逻辑）

    采集策略：
      - 热榜：使用 B站全站热门公开 API（轻量层）
      - 关键词搜索：使用 B站搜索公开 API（轻量层），降级到 Playwright
    """

    platform_name = "B站"
    platform_key = "bilibili"
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
        "Referer": "https://www.bilibili.com/",
    }

    # -------------------------------------------------------------------
    # 接口 URL 配置
    # -------------------------------------------------------------------

    # 全站热门 API（轻量层，无需登录）
    # 参数:
    #   rid=0       : 分区 ID（0=全站）
    #   type=all    : 类型（all=全部）
    # 返回全站热门视频排行数据
    RANKING_API_URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all"

    # 搜索 API（轻量层）
    # 参数:
    #   keyword=xxx  : 搜索关键词
    #   page=1       : 页码
    # 返回综合搜索结果
    SEARCH_API_URL = "https://api.bilibili.com/x/web-interface/search/all/v2?keyword={keyword}&page=1"

    # 热门页面 URL（浏览器层备用）
    HOTLIST_PAGE_URL = "https://www.bilibili.com/v/popular/rank/all"

    # 搜索页面 URL（浏览器层备用）
    SEARCH_PAGE_URL = "https://search.bilibili.com/all?keyword={keyword}"

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行 B站抓取任务，根据 task_type 分发到对应方法。

        支持的任务类型：
          - "hotlist" : 抓取 B站全站热门视频
          - "keyword" : 按关键词搜索公开视频

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
        爬取 B站全站热门视频排行榜。

        实现策略：
          1. 轻量层：调用 B站热门排行公开 API
             URL: https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all
             无需登录，直接返回 JSON 数据
          2. 浏览器层：使用 Playwright 打开热门页面（降级）
             URL: https://www.bilibili.com/v/popular/rank/all

        热门 API 返回数据格式（JSON）：
          {
            "code": 0,
            "message": "0",
            "ttl": 1,
            "data": {
              "list": [
                {
                  "aid": 123456789,          // 视频 AV 号
                  "bvid": "BV1xx411c7mD",   // 视频 BV 号
                  "title": "视频标题",
                  "desc": "视频描述",
                  "pic": "https://...",       // 封面图 URL
                  "owner": {
                    "mid": 12345,             // UP主 UID
                    "name": "UP主名称"
                  },
                  "stat": {
                    "view": 1000000,          // 播放量
                    "danmaku": 5000,          // 弹幕数
                    "reply": 1000,            // 评论数
                    "favorite": 2000,         // 收藏数
                    "coin": 800,              // 投币数
                    "share": 300,             // 分享数
                    "like": 5000              // 点赞数
                  },
                  "duration": 300,           // 时长（秒）
                  "pubdate": 1234567890,     // 发布时间（Unix 时间戳）
                  "rid": 0,                  // 分区 ID
                  "tname": "分区名称"        // 分区名称
                },
                ...
              ]
            }
          }

        返回:
            B站热门视频列表
        """
        self.logger.info("开始抓取 B站全站热门视频")

        # ---------- 第一优先级：轻量层（公开 API）----------
        items = await self._fetch_hotlist_by_api()

        if items:
            self.logger.info(f"B站热门（API层）获取成功，共 {len(items)} 条")
            return items

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("API 接口不可用，降级到浏览器层获取热门")
        items = await self._fetch_hotlist_by_playwright()

        if items:
            self.logger.info(f"B站热门（浏览器层）获取成功，共 {len(items)} 条")
        else:
            self.logger.warning("B站热门视频抓取失败，所有层级均不可用")

        return items

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索 B站公开视频。

        实现策略（优先级从高到低）：
          1. 轻量层：调用 B站搜索公开 API
             URL: https://api.bilibili.com/x/web-interface/search/all/v2?keyword=xxx
          2. 浏览器层：使用 Playwright 打开搜索页（降级）
             URL: https://search.bilibili.com/all?keyword=xxx

        合规约束：
          - 仅采集视频标题和描述，不下载视频
          - 请求间隔 >= 3 秒

        参数:
            keyword: 搜索关键词

        返回:
            匹配关键词的公开视频列表

        搜索 API 返回数据格式（JSON）：
          {
            "code": 0,
            "data": {
              "result": [
                {
                  "result_type": "video",
                  "data": {
                    "title": "视频标题（含HTML高亮标签）",
                    "description": "视频描述",
                    "bvid": "BV1xx411c7mD",
                    "author": "UP主名称",
                    "mid": 12345,             // UP主 UID
                    "play": 1000000,          // 播放量
                    "video_review": 1000,     // 评论数
                    "favorites": 2000,         // 收藏数
                    "tag": "标签1,标签2",
                    "review": 5000,           // 弹幕数
                    "pubdate": "2026-07-08 10:30:00",
                    "duration": "5:00",
                    "pic": "https://..."       // 封面 URL
                  }
                },
                ...
              ],
              "numResults": 1000,
              "page": 1
            }
          }
        """
        self.logger.info(f"B站关键词搜索: {keyword}")

        # ---------- 第一优先级：轻量层（搜索 API）----------
        items = await self._search_by_api(keyword)

        if items:
            self.logger.info(f"B站搜索（API层）命中 {len(items)} 条结果")
            return items

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("API 接口不可用，降级到浏览器层搜索")
        items = await self._search_by_playwright(keyword)

        if items:
            self.logger.info(f"B站搜索（浏览器层）命中 {len(items)} 条结果")
        else:
            self.logger.warning(f"B站关键词搜索无结果: {keyword}")

        return items

    # -------------------------------------------------------------------
    # 轻量层：公开 API 实现
    # -------------------------------------------------------------------

    async def _fetch_hotlist_by_api(self) -> List[CrawledItem]:
        """
        通过 B站热门排行公开 API 获取全站热门视频。

        接口: https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all

        无需登录，直接 HTTP GET 请求即可获取数据。

        返回:
            热门视频列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(
                    self.RANKING_API_URL,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"B站热门 API 返回状态码: {resp.status}，降级到浏览器层")
                        return []

                    data = await resp.json()
        except ImportError:
            self.logger.warning("aiohttp 不可用，尝试同步请求")
            data = await self._fetch_hotlist_sync()
            if not data:
                return []
        except Exception as e:
            self.logger.warning(f"B站热门 API 请求失败: {e}，降级到浏览器层")
            return []

        # 检查 API 返回码
        if data.get("code") != 0:
            self.logger.warning(f"B站热门 API 返回错误: code={data.get('code')}, msg={data.get('message')}")
            return []

        # 解析热门视频列表
        video_list = data.get("data", {}).get("list", [])
        if not video_list:
            self.logger.warning("B站热门 API 返回空列表")
            return []

        items = []
        for idx, video in enumerate(video_list):
            try:
                title = video.get("title", "").strip()
                if not title:
                    continue

                desc = video.get("desc", "")
                bvid = video.get("bvid", "")
                owner = video.get("owner", {})
                author = owner.get("name", "未知UP主")
                stat = video.get("stat", {})
                pubdate = video.get("pubdate", 0)

                # 解析发布时间（Unix 时间戳）
                if pubdate:
                    published_at = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # 构造视频链接
                original_url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""

                crawled_item = CrawledItem(
                    title=title,
                    content=desc,
                    source_platform="B站",
                    original_url=original_url,
                    published_at=published_at,
                    is_public=True,
                    interaction_data={
                        "author": author,
                        "author_mid": owner.get("mid", 0),
                        "views": stat.get("view", 0),         # 播放量
                        "danmaku": stat.get("danmaku", 0),     # 弹幕数
                        "comments": stat.get("reply", 0),     # 评论数
                        "favorites": stat.get("favorite", 0),  # 收藏数
                        "coins": stat.get("coin", 0),         # 投币数
                        "shares": stat.get("share", 0),       # 分享数
                        "likes": stat.get("like", 0),         # 点赞数
                        "duration": video.get("duration", 0), # 时长（秒）
                        "rank": idx + 1,                       # 排名
                        "tname": video.get("tname", ""),       # 分区名称
                        "source": "ranking_api",              # 数据来源标识
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析 B站热门视频条目失败: {e}")
                continue

        return items

    async def _fetch_hotlist_sync(self) -> dict:
        """
        同步降级方法：使用 urllib 获取热门排行数据。

        返回:
            解析后的 JSON 字典，失败时返回空字典
        """
        try:
            from urllib.request import urlopen, Request
            from urllib.error import URLError, HTTPError

            req = Request(self.RANKING_API_URL, headers=self.HEADERS)
            response = urlopen(req, timeout=15)
            raw_data = response.read().decode("utf-8")
            return json.loads(raw_data)
        except Exception as e:
            self.logger.error(f"同步获取 B站热门数据失败: {e}")
            return {}

    async def _search_by_api(self, keyword: str) -> List[CrawledItem]:
        """
        通过 B站搜索公开 API 搜索关键词。

        接口: https://api.bilibili.com/x/web-interface/search/all/v2?keyword=xxx

        参数:
            keyword: 搜索关键词

        返回:
            搜索结果列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            url = self.SEARCH_API_URL.format(keyword=keyword)
            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"B站搜索 API 返回状态码: {resp.status}")
                        return []

                    data = await resp.json()
        except ImportError:
            self.logger.warning("aiohttp 不可用")
            return []
        except Exception as e:
            self.logger.warning(f"B站搜索 API 请求失败: {e}")
            return []

        # 检查 API 返回码
        if data.get("code") != 0:
            self.logger.warning(f"B站搜索 API 返回错误: code={data.get('code')}")
            return []

        # 解析搜索结果
        return self._parse_search_results(data)

    def _parse_search_results(self, data: dict) -> List[CrawledItem]:
        """
        解析 B站搜索 API 返回的 JSON 数据。

        数据格式说明：
          data.result 是一个列表，每个元素包含：
            - result_type: 结果类型（"video"=视频, "media_bangumi"=番剧, "media_ft"=影视等）
            - data: 具体数据
              - title: 视频标题（含 HTML 高亮标签 <em class="keyword">关键词</em>）
              - description: 视频描述
              - bvid: 视频 BV 号
              - author: UP主名称
              - play: 播放量
              - video_review: 评论数
              - favorites: 收藏数
              - tag: 标签（逗号分隔）
              - review: 弹幕数
              - pubdate: 发布时间（字符串格式）
              - duration: 时长（如 "5:00"）
              - pic: 封面图 URL

        参数:
            data: 搜索 API 返回的 JSON 数据

        返回:
            CrawledItem 列表
        """
        items = []

        results = data.get("data", {}).get("result", [])
        if not results:
            return items

        for result in results:
            # 仅处理视频类型的结果
            result_type = result.get("result_type", "")
            if result_type != "video":
                continue

            video_data = result.get("data", {})
            if not video_data:
                continue

            try:
                # 提取并清洗标题（去除 HTML 高亮标签）
                raw_title = video_data.get("title", "")
                title = self._strip_html_tags(raw_title).strip()
                if not title:
                    continue

                desc = video_data.get("description", "")
                bvid = video_data.get("bvid", "")
                author = video_data.get("author", "未知UP主")
                tags = video_data.get("tag", "")
                duration = video_data.get("duration", "")
                pubdate_str = video_data.get("pubdate", "")

                # 构造视频链接
                original_url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""

                # 解析时间
                published_at = self._parse_bilibili_time(pubdate_str)

                crawled_item = CrawledItem(
                    title=title,
                    content=desc,
                    source_platform="B站",
                    original_url=original_url,
                    published_at=published_at,
                    is_public=True,
                    interaction_data={
                        "author": author,
                        "views": video_data.get("play", 0),
                        "danmaku": video_data.get("review", 0),
                        "comments": video_data.get("video_review", 0),
                        "favorites": video_data.get("favorites", 0),
                        "duration": duration,
                        "tags": tags,
                        "source": "search_api",
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析 B站搜索结果条目失败: {e}")
                continue

        return items

    # -------------------------------------------------------------------
    # 浏览器层：Playwright 实现（预留）
    # -------------------------------------------------------------------

    async def _fetch_hotlist_by_playwright(self) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器获取 B站热门视频（降级方案）。

        实现说明：
          - 打开热门页面 https://www.bilibili.com/v/popular/rank/all
          - 等待页面渲染完成
          - 从页面 DOM 中提取视频信息

        合规约束：
          - 仅采集公开视频标题和描述
          - 不下载视频内容
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

                # 等待排行榜加载
                await asyncio.sleep(self.REQUEST_INTERVAL + 2)

                # B站排行榜选择器
                # 热门视频条目通常在 .rank-item 或类似结构中
                rank_items = await page.query_selector_all(
                    ".rank-item, .video-card, li[class*='rank']"
                )

                for idx, rank_item in enumerate(rank_items):
                    try:
                        # 提取视频标题
                        title_el = await rank_item.query_selector(
                            ".title, a.title, [class*='title']"
                        )
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        title = title.strip()
                        if not title:
                            continue

                        # 提取播放量等信息
                        info_el = await rank_item.query_selector(
                            ".detail, .info, [class*='detail']"
                        )
                        info_text = await info_el.inner_text() if info_el else ""

                        # 提取链接
                        link_el = await rank_item.query_selector("a[href*='video']")
                        link_href = await link_el.get_attribute("href") if link_el else ""
                        original_url = link_href if link_href.startswith("http") else f"https://www.bilibili.com{link_href}"

                        crawled_item = CrawledItem(
                            title=title,
                            content=info_text.strip()[:500] if info_text else "",
                            source_platform="B站",
                            original_url=original_url,
                            published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            is_public=True,
                            interaction_data={
                                "rank": idx + 1,
                                "source": "playwright_hotlist",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析 B站热门条目失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    async def _search_by_playwright(self, keyword: str) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器进行 B站搜索（降级方案）。

        实现说明：
          - 打开搜索页 https://search.bilibili.com/all?keyword={keyword}
          - 等待搜索结果渲染
          - 提取首屏可见的视频信息

        合规约束：
          - 仅采集视频标题和描述
          - 不下载视频内容
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

                # B站搜索结果选择器
                results = await page.query_selector_all(
                    ".video-item, .search-result, .bili-video-card"
                )

                for result in results:
                    try:
                        # 提取视频标题
                        title_el = await result.query_selector(
                            ".title, a.title, h3, .bili-video-card__title"
                        )
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        title = title.strip()
                        if not title:
                            continue

                        # 提取 UP主 / 描述
                        author_el = await result.query_selector(
                            ".author, .up, .bili-video-card__author"
                        )
                        author = await author_el.inner_text() if author_el else "未知UP主"

                        desc_el = await result.query_selector(
                            ".desc, .bili-video-card__info"
                        )
                        desc = await desc_el.inner_text() if desc_el else ""

                        # 提取链接
                        link_el = await result.query_selector("a[href*='video']")
                        link_href = await link_el.get_attribute("href") if link_el else ""
                        original_url = link_href if link_href.startswith("http") else f"https://www.bilibili.com{link_href}"

                        crawled_item = CrawledItem(
                            title=title,
                            content=self._strip_html_tags(desc).strip(),
                            source_platform="B站",
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
                        self.logger.debug(f"解析 B站搜索结果失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    # -------------------------------------------------------------------
    # 数据处理工具方法
    # -------------------------------------------------------------------

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """
        去除 HTML 标签，只保留纯文本内容。

        B站搜索结果标题中常见的高亮标签格式：
          <em class="keyword">关键词</em>
        清洗后会保留关键词文字。

        参数:
            text: 可能包含 HTML 标签的文本

        返回:
            清洗后的纯文本
        """
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)
        return text.strip()

    @staticmethod
    def _parse_bilibili_time(time_str: str) -> str:
        """
        解析 B站时间字符串为标准格式。

        B站搜索结果中的 pubdate 格式通常为：
          - 绝对时间: "2026-07-08 10:30:00"
          - 相对时间: "5天前"、"3小时前"

        参数:
            time_str: B站原始时间字符串

        返回:
            标准格式时间 "YYYY-MM-DD HH:MM:SS"
        """
        if not time_str or not time_str.strip():
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        time_str = time_str.strip()

        # 相对时间处理
        now = datetime.now()

        if "天前" in time_str:
            try:
                days = int(re.search(r"(\d+)天前", time_str).group(1))
                dt = now - __import__("datetime").timedelta(days=days)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError):
                pass

        if "小时前" in time_str:
            try:
                hours = int(re.search(r"(\d+)小时前", time_str).group(1))
                dt = now - __import__("datetime").timedelta(hours=hours)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError):
                pass

        # 绝对时间格式
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

        return now.strftime("%Y-%m-%d %H:%M:%S")

    # -------------------------------------------------------------------
    # API 层预留接口
    # -------------------------------------------------------------------

    async def _fetch_by_official_api(self, endpoint: str, params: dict = None) -> dict:
        """
        B站开放平台 API 调用（预留接口）。

        使用说明：
          - 需要在配置中设置 B站开放平台凭证
          - 需要通过 OAuth 2.0 获取 access_token
          - 当前为预留空实现

        参数:
            endpoint: API 端点路径
            params: 请求参数

        异常:
            NotImplementedError: 当前未实现
        """
        # TODO: 待接入 B站开放平台 API
        # 需要配置:
        #   - BILIBILI_APP_KEY: 应用 App Key
        #   - BILIBILI_APP_SECRET: 应用 App Secret
        #   - BILIBILI_ACCESS_TOKEN: OAuth 访问令牌
        self.logger.warning("B站官方 API 接口暂未实现")
        raise NotImplementedError("B站官方 API 接口待开发")
