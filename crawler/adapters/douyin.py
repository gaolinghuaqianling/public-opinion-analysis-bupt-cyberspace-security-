# -*- coding: utf-8 -*-
"""
抖音适配器

三层采集架构，优先级从高到低：
  1. API 层  : 抖音创作者开放平台 API（预留接口，需要开发者账号和 app_key）
  2. 轻量层  : apihz.cn 免费公开接口，通过 HTTP GET 获取抖音热搜数据
  3. 浏览器层: Playwright 无头浏览器，采集需要 JS 渲染的搜索结果页（降级方案）

合规约束：
  - 仅采集公开可见内容，不使用任何账号登录凭证
  - 不绕过任何反爬机制（不伪造 signature、不绕过验证码）
  - 请求间隔 >= 3 秒，遵守 robots.txt
  - 仅采集作品标题和描述等公开信息

apihz.cn 接口说明：
  - 热搜榜:
    URL: https://cn.apihz.cn/api/xinwen/douyin.php?id=88888888&key=88888888
    方法: GET
    返回 JSON:
    {
      "code": 200,
      "time": 时间戳,
      "time2": "时间字符串",
      "data": [
        {
          "title": "词条",
          "event_time": 时间戳,
          "hot_value": 热度,
          "label": 标签,
          "video_count": 视频数,
          "word_type": 类型
        }
      ]
    }
    注意: 该接口为免费公开接口，id 和 key 参数使用默认值 88888888
  - 关键词搜索:
    apihz 不支持关键词搜索，关键词任务通过获取热搜后 filter_by_keywords 实现

浏览器层备用说明：
  - 热搜页面: https://www.douyin.com/hot
  - 搜索页面: https://www.douyin.com/search/{keyword}
"""

import asyncio
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask


class DouyinAdapter(BaseAdapter):
    """
    抖音适配器（三层采集逻辑）

    采集策略：
      - 热榜：优先尝试 apihz.cn 免费接口（轻量层），降级到 Playwright
      - 关键词搜索：通过 apihz.cn 获取热搜后 filter_by_keywords 过滤，
        若无匹配则降级到 Playwright
      - 账号采集：当前不支持（抖音无公开用户主页 API）
    """

    platform_name = "抖音"
    platform_key = "douyin"
    supported_task_types = ["hotlist", "keyword"]

    # -------------------------------------------------------------------
    # 请求配置
    # -------------------------------------------------------------------
    # 合规约束：请求间隔 >= 3 秒
    REQUEST_INTERVAL = 3.0  # 请求最小间隔（秒）

    # 同步请求使用的线程池（用于将 urllib 同步调用包装为 async）
    _executor = ThreadPoolExecutor(max_workers=4)

    # HTTP 请求头（模拟浏览器访问）
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.apihz.cn/",
    }

    # -------------------------------------------------------------------
    # 接口 URL 配置
    # -------------------------------------------------------------------

    # apihz.cn 免费抖音热搜接口（轻量层，主要数据源）
    # 返回 JSON: {"code":200, "time":时间戳, "time2":"时间字符串", "data":[...]}
    APIHZ_HOTSEARCH_URL = (
        "https://cn.apihz.cn/api/xinwen/douyin.php"
        "?id=10018966&key=a88e54a2b2a21bddcf2688e10953fdb6"
    )

    # 热搜页面 URL（浏览器层备用）
    HOTSEARCH_PAGE_URL = "https://www.douyin.com/hot"

    # 搜索页面 URL（浏览器层备用）
    SEARCH_PAGE_URL = "https://www.douyin.com/search/{keyword}"

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行抖音抓取任务，根据 task_type 分发到对应方法。

        支持的任务类型：
          - "hotlist" : 抓取抖音热搜榜（通过 apihz.cn 接口）
          - "keyword" : 按关键词过滤热搜（apihz 不支持关键词搜索，
                        因此先获取热搜再过滤）

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
        爬取抖音热搜榜。

        实现策略（优先级从高到低）：
          1. 轻量层：调用 apihz.cn 免费接口
             URL: https://cn.apihz.cn/api/xinwen/douyin.php?id=88888888&key=88888888
             使用 urllib 同步请求 + ThreadPoolExecutor 包装为 async
             接口返回 JSON: {"code":200, "time":时间戳, "time2":"时间字符串",
                             "data":[{"title":"词条","event_time":时间戳,
                             "hot_value":热度,"label":标签,
                             "video_count":视频数,"word_type":类型}]}
          2. 浏览器层：使用 Playwright 打开热搜页面（降级）
             URL: https://www.douyin.com/hot
             从页面 HTML 中提取热搜词条和热度值

        返回:
            抖音热搜词条列表
        """
        self.logger.info("开始抓取抖音热搜榜")

        # ---------- 第一优先级：轻量层（apihz.cn 接口）----------
        items = await self._fetch_hotlist_by_apihz()

        if items:
            self.logger.info(f"抖音热搜（apihz接口）获取成功，共 {len(items)} 条")
            return items

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("apihz 接口不可用，降级到浏览器层获取热搜")
        items = await self._fetch_hotlist_by_playwright()

        if items:
            self.logger.info(f"抖音热搜（浏览器层）获取成功，共 {len(items)} 条")
        else:
            self.logger.warning("抖音热搜榜抓取失败，所有层级均不可用")

        return items

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索抖音公开内容。

        实现策略：
          - apihz.cn 接口不支持关键词搜索
          - 先调用 apihz.cn 获取完整热搜榜，再通过 filter_by_keywords 过滤
          - 若过滤后无结果，降级到 Playwright 搜索页

        合规约束：
          - 仅采集公开作品标题和描述
          - 不下载视频内容
          - 请求间隔 >= 3 秒

        参数:
            keyword: 搜索关键词

        返回:
            匹配关键词的公开内容列表
        """
        self.logger.info(f"抖音关键词搜索: {keyword}")

        # ---------- 第一优先级：轻量层（apihz 接口 + 关键词过滤）----------
        # apihz 不支持关键词搜索，先获取热搜再过滤
        hotlist_items = await self._fetch_hotlist_by_apihz()

        if hotlist_items:
            filtered = self.filter_by_keywords(hotlist_items, [keyword])
            if filtered:
                self.logger.info(
                    f"抖音搜索（apihz接口+过滤）命中 {len(filtered)} 条结果"
                )
                return filtered
            self.logger.info(
                f"apihz 热搜中未找到与 '{keyword}' 匹配的词条，降级到浏览器层"
            )

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("降级到浏览器层搜索")
        items = await self._search_by_playwright(keyword)

        if items:
            self.logger.info(f"抖音搜索（浏览器层）命中 {len(items)} 条结果")
        else:
            self.logger.warning(f"抖音关键词搜索无结果: {keyword}")

        return items

    # -------------------------------------------------------------------
    # 轻量层：apihz.cn 接口实现
    # -------------------------------------------------------------------

    def _fetch_hotlist_by_apihz_sync(self) -> List[CrawledItem]:
        """
        同步调用 apihz.cn 接口获取抖音热搜数据。

        使用 urllib 发送 GET 请求，解析 JSON 返回结果，
        将每条热搜数据映射为 CrawledItem。

        接口: https://cn.apihz.cn/api/xinwen/douyin.php?id=88888888&key=88888888

        返回:
            热搜词条列表，接口不可用时返回空列表
        """
        try:
            # 公共测试 key 有频率限制，请求前等待
            import time
            time.sleep(2)

            req = Request(self.APIHZ_HOTSEARCH_URL, headers=self.HEADERS)
            with urlopen(req, timeout=15) as resp:
                raw = resp.read()
                # 尝试多种编码解码（优先 utf-8）
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("gbk", errors="replace")

                data = json.loads(text)

        except URLError as e:
            self.logger.warning(
                f"apihz 接口网络请求失败: {e}，降级到浏览器层"
            )
            return []
        except json.JSONDecodeError as e:
            self.logger.warning(
                f"apihz 接口返回非 JSON 数据: {e}，降级到浏览器层"
            )
            return []
        except Exception as e:
            self.logger.warning(
                f"apihz 接口请求异常: {e}，降级到浏览器层"
            )
            return []

        # 校验接口返回状态码
        code = data.get("code")
        if code != 200:
            self.logger.warning(
                f"apihz 接口返回非 200 状态码: {code}，"
                f"msg={data.get('msg', '')}，降级到浏览器层"
            )
            return []

        # 提取 data 数组
        data_list = data.get("data", [])
        if not data_list:
            self.logger.warning("apihz 接口返回空 data 列表")
            return []

        # 尝试获取接口返回的时间字符串作为参考
        time2_str = data.get("time2", "")

        items = []
        for entry in data_list:
            try:
                title = entry.get("title", "").strip()
                if not title:
                    continue

                # 解析时间：优先使用 event_time 时间戳，其次用接口 time2
                event_time = entry.get("event_time", 0)
                if event_time:
                    published_at = datetime.fromtimestamp(
                        event_time
                    ).strftime("%Y-%m-%d %H:%M:%S")
                elif time2_str:
                    published_at = time2_str
                else:
                    published_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                hot_value = entry.get("hot_value", 0)
                label = entry.get("label", "")
                video_count = entry.get("video_count", 0)
                word_type = entry.get("word_type", "")

                crawled_item = CrawledItem(
                    title=title,
                    content="",  # 热搜词条无正文内容
                    source_platform="抖音",
                    original_url=f"https://www.douyin.com/search/{title}",
                    published_at=published_at,
                    is_public=True,
                    interaction_data={
                        "heat": hot_value,
                        "label": label,
                        "video_count": video_count,
                        "word_type": word_type,
                        "source": "apihz_api",
                    },
                )
                items.append(crawled_item)

            except Exception as e:
                self.logger.debug(f"解析 apihz 热搜条目失败: {e}")
                continue

        return items

    async def _fetch_hotlist_by_apihz(self) -> List[CrawledItem]:
        """
        异步包装：在线程池中执行同步的 apihz.cn 请求。

        使用 ThreadPoolExecutor 将 urllib 同步请求包装为协程，
        与人民网 RSS 适配器的异步模式保持一致。

        返回:
            热搜词条列表，接口不可用时返回空列表
        """
        loop = asyncio.get_running_loop()
        try:
            items = await loop.run_in_executor(
                self._executor,
                self._fetch_hotlist_by_apihz_sync,
            )
        except Exception as e:
            self.logger.warning(f"apihz 线程池执行异常: {e}")
            items = []
        return items

    # -------------------------------------------------------------------
    # 浏览器层：Playwright 实现（降级方案）
    # -------------------------------------------------------------------

    async def _fetch_hotlist_by_playwright(self) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器获取抖音热搜榜（降级方案）。

        实现说明：
          - 打开热搜页面 https://www.douyin.com/hot
          - 等待页面 JS 渲染完成
          - 从页面 DOM 中提取热搜词条和热度值

        合规约束：
          - 仅采集公开热搜信息
          - 不登录、不使用任何凭证
          - 请求间隔 >= 3 秒

        返回:
            热搜词条列表

        异常:
            NotImplementedError: 当 Playwright 未安装时抛出
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright 未安装，无法降级到浏览器层")
            raise NotImplementedError("Playwright 未安装")

        items = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(
                    self.HOTSEARCH_PAGE_URL,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                # 等待热搜列表加载（抖音页面 JS 渲染需要时间）
                await asyncio.sleep(self.REQUEST_INTERVAL + 2)

                # 抖音热搜页面 DOM 结构可能变化，以下为通用选择器
                hot_items = await page.query_selector_all(
                    "[class*='hotList'] li, [class*='hot-list'] li, "
                    "[data-e2e='search-common-virtual-list'] > div"
                )

                for hot_item in hot_items:
                    try:
                        title_el = await hot_item.query_selector(
                            "a, [class*='title'], h3"
                        )
                        if not title_el:
                            continue
                        title = await title_el.inner_text()
                        title = title.strip()
                        if not title:
                            continue

                        # 尝试提取热度值
                        heat_el = await hot_item.query_selector(
                            "[class*='heat'], [class*='hot-value'], span"
                        )
                        heat_text = (
                            await heat_el.inner_text() if heat_el else "0"
                        )
                        heat_match = re.search(r"(\d+)", heat_text)
                        heat_value = (
                            int(heat_match.group(1)) if heat_match else 0
                        )

                        crawled_item = CrawledItem(
                            title=title,
                            content="",
                            source_platform="抖音",
                            original_url=f"https://www.douyin.com/search/{title}",
                            published_at=datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            is_public=True,
                            interaction_data={
                                "heat": heat_value,
                                "source": "playwright_hotlist",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析热搜条目失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    async def _search_by_playwright(self, keyword: str) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器进行抖音搜索（降级方案）。

        实现说明：
          - 打开搜索页 https://www.douyin.com/search/{keyword}
          - 等待搜索结果渲染
          - 提取首屏可见的作品标题和描述

        合规约束：
          - 仅采集公开作品标题和描述，不下载视频
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
            self.logger.warning("Playwright 未安装，无法降级到浏览器层")
            raise NotImplementedError("Playwright 未安装")

        items = []
        url = self.SEARCH_PAGE_URL.format(keyword=keyword)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=30000
                )

                # 等待搜索结果 JS 渲染
                await asyncio.sleep(self.REQUEST_INTERVAL + 3)

                # 抖音搜索结果通常是视频卡片
                cards = await page.query_selector_all(
                    "[class*='video-card'], [class*='search-result-card'], li"
                )

                for card in cards:
                    try:
                        title_el = await card.query_selector(
                            "[class*='title'], p, [class*='desc']"
                        )
                        if not title_el:
                            continue
                        content = await title_el.inner_text()
                        if not content.strip():
                            continue

                        # 提取作者
                        author_el = await card.query_selector(
                            "[class*='author'], [class*='nickname']"
                        )
                        author = (
                            await author_el.inner_text()
                            if author_el
                            else "匿名用户"
                        )

                        crawled_item = CrawledItem(
                            title=(
                                content[:100]
                                if len(content) > 100
                                else content
                            ),
                            content=content,
                            source_platform="抖音",
                            original_url=url,
                            published_at=datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            is_public=True,
                            interaction_data={
                                "author": author,
                                "source": "playwright_search",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析搜索结果卡片失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    # -------------------------------------------------------------------
    # API 层预留接口
    # -------------------------------------------------------------------

    async def _fetch_by_official_api(self, endpoint: str, params: dict = None) -> dict:
        """
        抖音创作者开放平台 API 调用（预留接口）。

        使用说明：
          - 需要在配置中设置抖音开放平台凭证
          - 需要通过 OAuth 2.0 获取 access_token
          - 当前为预留空实现

        参数:
            endpoint: API 端点路径
            params: 请求参数

        异常:
            NotImplementedError: 当前未实现
        """
        # TODO: 待接入抖音创作者开放平台 API
        # 需要配置:
        #   - DOUYIN_APP_KEY: 应用 App Key
        #   - DOUYIN_APP_SECRET: 应用 App Secret
        #   - DOUYIN_ACCESS_TOKEN: OAuth 访问令牌
        self.logger.warning("抖音官方 API 接口暂未实现")
        raise NotImplementedError("抖音官方 API 接口待开发")
