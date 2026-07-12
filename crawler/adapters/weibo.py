# -*- coding: utf-8 -*-
"""
微博适配器

三层采集架构，优先级从高到低：
  1. API 层  : 微博开放平台官方 API（需要 app_key，预留接口）
  2. 轻量层  : 微博公开 AJAX/JSON 接口，无需鉴权，直接 HTTP 请求
  3. 浏览器层: Playwright 无头浏览器，用于采集需要 JS 渲染的页面

合规约束：
  - 仅采集公开可见内容，不使用任何账号登录凭证
  - 不绕过任何反爬机制（不伪造 cookie、不绕过验证码）
  - 请求间隔 >= 4 秒，并发数 <= 2
  - 浏览器层不滚动加载更多内容，仅采集首屏可见内容
  - 跳过标记为"仅粉丝可见"的内容

公开接口说明：
  - 热搜榜: https://weibo.com/ajax/side/hotSearch
    返回 JSON 数据，包含热搜词条（word）、热度值（num）、标签（label_name）
  - 搜索: https://weibo.com/ajax/search/all
    参数: q=关键词&page=1
    返回 JSON 数据，包含卡片（cards）中的博文信息
  - 博主主页: https://weibo.com/u/{uid}
    需要浏览器渲染，提取页面中的博文卡片
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask


class WeiboAdapter(BaseAdapter):
    """
    微博适配器（三层采集逻辑）

    采集策略：
      - 热榜：优先使用热搜公开接口（轻量层），无需登录
      - 关键词搜索：优先使用搜索公开接口，降级到 Playwright
      - 账号采集：仅使用 Playwright 采集公开博主首页可见博文
    """

    platform_name = "微博"
    platform_key = "weibo"
    supported_task_types = ["hotlist", "keyword", "account"]

    # -------------------------------------------------------------------
    # 请求配置
    # -------------------------------------------------------------------
    # 合规约束：请求间隔 >= 4 秒
    REQUEST_INTERVAL = 4.0  # 请求最小间隔（秒）
    MAX_CONCURRENCY = 2     # 最大并发数

    # HTTP 请求头（模拟浏览器访问，但不伪造 cookie）
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://weibo.com/",
    }

    # -------------------------------------------------------------------
    # 接口 URL 配置
    # -------------------------------------------------------------------

    # 热搜公开接口（轻量层，无需鉴权）
    # 返回 JSON: {"data":{"realtime":[{"word":"词条","num":热度,"label_name":"标签"}]}}
    HOTSEARCH_URL = "https://weibo.com/ajax/side/hotSearch"

    # 搜索公开接口（轻量层）
    # 参数: q=关键词&page=页码
    # 返回 JSON: {"data":{"cards":[...]}}
    SEARCH_URL = "https://weibo.com/ajax/search/all"

    # 搜索页备用 URL（浏览器层降级使用）
    SEARCH_PAGE_URL = "https://s.weibo.com/weibo?q={keyword}"

    # 博主主页 URL（浏览器层）
    # account_id 为微博用户 UID
    USER_PAGE_URL = "https://weibo.com/u/{account_id}"

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行微博抓取任务，根据 task_type 分发到对应方法。

        支持的任务类型：
          - "hotlist" : 抓取微博热搜榜
          - "keyword" : 按关键词搜索公开博文
          - "account" : 按账号采集公开博文

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

        elif task_type == "account":
            if not task.target:
                self.logger.warning("账号任务未指定 target，返回空列表")
                return []
            return await self.crawl_by_account(task.target)

        else:
            self.logger.error(f"不支持的任务类型: {task_type}")
            return []

    async def crawl_hotlist(self) -> List[CrawledItem]:
        """
        爬取微博热搜榜（使用公开接口）。

        实现说明：
          1. 调用热搜公开接口 https://weibo.com/ajax/side/hotSearch
          2. 解析 JSON 数据，提取热搜词条、热度值、标签
          3. 构造 CrawledItem 列表

        接口返回数据格式（JSON）：
          {
            "ok": 1,
            "data": {
              "realtime": [
                {
                  "word": "热搜词条",
                  "num": 1234567,        // 热度值（整数）
                  "label_name": "热",     // 标签（热/新/沸等）
                  "icon_desc": "",        // 图标描述
                  "category": ""          // 分类
                },
                ...
              ]
            }
          }

        返回:
            微博热搜词条列表（每条构造为 CrawledItem）
        """
        self.logger.info("开始抓取微博热搜榜")

        try:
            import aiohttp

            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(self.HOTSEARCH_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.logger.error(f"热搜接口返回状态码: {resp.status}")
                        return []

                    data = await resp.json()
        except ImportError:
            # aiohttp 不可用，降级到同步请求
            self.logger.warning("aiohttp 不可用，使用同步请求获取热搜数据")
            data = await self._fetch_hotsearch_sync()
        except Exception as e:
            self.logger.error(f"获取微博热搜数据失败: {e}")
            return []

        if not data or data.get("ok") != 1:
            self.logger.error(f"热搜接口返回异常数据: {data}")
            return []

        # 解析热搜词条
        realtime = data.get("data", {}).get("realtime", [])
        if not realtime:
            self.logger.warning("热搜接口返回空列表")
            return []

        crawled_items = []
        for item in realtime:
            word = item.get("word", "").strip()
            if not word:
                continue

            heat_value = item.get("num", 0)
            label = item.get("label_name", "")

            # 构造 CrawledItem
            crawled_item = CrawledItem(
                title=word,
                content="",  # 热搜词条无正文内容
                source_platform="微博",
                original_url=f"https://s.weibo.com/weibo?q={word}",
                published_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                is_public=True,  # 热搜为公开信息
                interaction_data={
                    "heat": heat_value,      # 热度值
                    "label": label,          # 标签（热/新/沸）
                    "source": "hotsearch",   # 数据来源标识
                },
            )
            crawled_items.append(crawled_item)

        self.logger.info(f"微博热搜榜获取成功，共 {len(crawled_items)} 条")
        return crawled_items

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索微博公开内容。

        实现策略（优先级从高到低）：
          1. 轻量层：调用微博搜索公开接口
             URL: https://weibo.com/ajax/search/all?q=关键词&page=1
             如果接口不可用（403/需要登录），降级到浏览器层
          2. 浏览器层：使用 Playwright 打开搜索页
             URL: https://s.weibo.com/weibo?q=关键词

        合规约束：
          - 仅采集搜索结果中可见的公开博文
          - 请求间隔 >= 4 秒
          - 不登录、不使用任何凭证

        参数:
            keyword: 搜索关键词

        返回:
            匹配关键词的公开博文列表

        搜索接口返回数据格式（JSON）：
          {
            "data": {
              "cards": [
                {
                  "card_group": [
                    {
                      "mblog": {
                        "text": "博文内容（含HTML）",
                        "created_at": "Mon Jul 08 10:30:00 +0800 2026",
                        "user": {"screen_name": "用户昵称"},
                        "reposts_count": 10,
                        "comments_count": 20,
                        "attitudes_count": 30
                      }
                    }
                  ]
                },
                ...
              ]
            }
          }
        """
        self.logger.info(f"微博关键词搜索: {keyword}")

        # ---------- 第一优先级：轻量层（公开接口）----------
        items = await self._search_by_api(keyword)

        if items:
            self.logger.info(f"微博搜索（API层）命中 {len(items)} 条结果")
            return items

        # ---------- 第二优先级：浏览器层（Playwright 降级）----------
        self.logger.info("API 接口不可用，降级到浏览器层搜索")
        items = await self._search_by_playwright(keyword)

        if items:
            self.logger.info(f"微博搜索（浏览器层）命中 {len(items)} 条结果")
        else:
            self.logger.warning(f"微博关键词搜索无结果: {keyword}")

        return items

    async def crawl_by_account(self, account_id: str) -> List[CrawledItem]:
        """
        按微博账号采集公开博文（使用 Playwright 浏览器层）。

        实现说明：
          1. 使用 Playwright 打开公开博主主页 https://weibo.com/u/{account_id}
          2. 仅采集页面上首屏可见的公开博文（不滚动加载更多）
          3. 跳过"仅粉丝可见"标记的内容

        合规约束：
          - 不登录，仅访问公开可见内容
          - 不滚动加载更多（避免触发反爬和采集非公开内容）
          - 请求间隔 >= 4 秒
          - 并发数 <= 2

        参数:
            account_id: 微博用户 UID

        返回:
            该账号的公开博文列表
        """
        self.logger.info(f"微博账号采集: account_id={account_id}")

        try:
            items = await self._crawl_user_page(account_id)
        except NotImplementedError:
            self.logger.warning("Playwright 未安装或不可用，无法进行浏览器层采集")
            return []
        except Exception as e:
            self.logger.error(f"微博账号采集失败: {e}")
            return []

        # 过滤掉非公开内容
        items = self.filter_public_only(items)

        self.logger.info(f"微博账号 {account_id} 采集到 {len(items)} 条公开博文")
        return items

    # -------------------------------------------------------------------
    # 轻量层：API/公开接口实现
    # -------------------------------------------------------------------

    async def _fetch_hotsearch_sync(self) -> dict:
        """
        同步降级方法：使用 urllib 获取热搜数据（当 aiohttp 不可用时）。

        返回:
            解析后的 JSON 字典，失败时返回空字典
        """
        try:
            from urllib.request import urlopen, Request
            from urllib.error import URLError, HTTPError

            req = Request(self.HOTSEARCH_URL, headers=self.HEADERS)
            response = urlopen(req, timeout=15)
            raw_data = response.read().decode("utf-8")
            return json.loads(raw_data)
        except Exception as e:
            self.logger.error(f"同步获取热搜数据失败: {e}")
            return {}

    async def _search_by_api(self, keyword: str) -> List[CrawledItem]:
        """
        通过微博搜索公开接口搜索关键词。

        接口: https://weibo.com/ajax/search/all?q=keyword&page=1

        返回:
            搜索结果列表，接口不可用时返回空列表
        """
        try:
            import aiohttp

            params = {"q": keyword, "page": "1"}
            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(
                    self.SEARCH_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        self.logger.warning(f"搜索接口返回状态码: {resp.status}，降级到浏览器层")
                        return []

                    data = await resp.json()
        except ImportError:
            self.logger.warning("aiohttp 不可用")
            return []
        except Exception as e:
            self.logger.warning(f"搜索接口请求失败: {e}，降级到浏览器层")
            return []

        # 解析搜索结果
        return self._parse_search_results(data, keyword)

    def _parse_search_results(self, data: dict, keyword: str) -> List[CrawledItem]:
        """
        解析微博搜索接口返回的 JSON 数据。

        数据格式说明：
          data.cards 是一个列表，每个元素可能包含：
            - card_group: 卡片组，每个卡片包含 mblog（博文对象）
            - mblog: 直接包含的博文对象
          mblog 对象包含：
            - text: 博文内容（含 HTML 标签，需清洗）
            - created_at: 发布时间（字符串）
            - mid: 博文 ID
            - user.screen_name: 作者昵称
            - reposts_count: 转发数
            - comments_count: 评论数
            - attitudes_count: 点赞数

        参数:
            data: 搜索接口返回的 JSON 数据
            keyword: 搜索关键词（用于构造 original_url）

        返回:
            CrawledItem 列表
        """
        items = []

        cards = data.get("data", {}).get("cards", [])
        for card in cards:
            # 博文可能直接在 card 下，也可能在 card_group 中
            mblog_list = []

            if "mblog" in card:
                mblog_list.append(card["mblog"])
            elif "card_group" in card:
                for sub_card in card.get("card_group", []):
                    if "mblog" in sub_card:
                        mblog_list.append(sub_card["mblog"])

            for mblog in mblog_list:
                try:
                    raw_text = mblog.get("text", "")
                    created_at = mblog.get("created_at", "")
                    mid = mblog.get("mid", "")
                    user_info = mblog.get("user", {})
                    screen_name = user_info.get("screen_name", "")

                    # 清洗博文内容（去除 HTML 标签）
                    text = self._strip_html_tags(raw_text)
                    if not text.strip():
                        continue

                    # 解析时间
                    published_at = self._parse_weibo_time(created_at)

                    # 构造 CrawledItem
                    crawled_item = CrawledItem(
                        title=f"@{screen_name}的微博",
                        content=text,
                        source_platform="微博",
                        original_url=f"https://weibo.com/{mid}" if mid else "",
                        published_at=published_at,
                        is_public=True,
                        interaction_data={
                            "author": screen_name,
                            "reposts": mblog.get("reposts_count", 0),
                            "comments": mblog.get("comments_count", 0),
                            "likes": mblog.get("attitudes_count", 0),
                            "source": "search_api",
                        },
                    )
                    items.append(crawled_item)

                except Exception as e:
                    self.logger.debug(f"解析搜索结果条目失败: {e}")
                    continue

        return items

    # -------------------------------------------------------------------
    # 浏览器层：Playwright 实现
    # -------------------------------------------------------------------

    async def _search_by_playwright(self, keyword: str) -> List[CrawledItem]:
        """
        使用 Playwright 浏览器进行微博搜索（降级方案）。

        实现说明：
          - 打开搜索页 https://s.weibo.com/weibo?q=关键词
          - 等待页面加载完成
          - 提取首屏可见的搜索结果

        合规约束：
          - 仅采集首屏可见内容，不滚动加载
          - 不登录

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
            self.logger.warning("Playwright 未安装，无法使用浏览器层搜索")
            raise NotImplementedError("Playwright 未安装")

        items = []
        url = self.SEARCH_PAGE_URL.format(keyword=keyword)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                # 合规：设置合理的 viewport，模拟正常浏览器
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # 等待搜索结果加载
                await page.wait_for_selector(".m-wrap", timeout=10000)
                # 合规：等待后不主动滚动，仅采集首屏内容
                await asyncio.sleep(self.REQUEST_INTERVAL)

                # 提取搜索结果卡片
                cards = await page.query_selector_all(".card-wrap")
                for card in cards:
                    try:
                        # 提取博文文本
                        text_el = await card.query_selector(".txt")
                        content = await text_el.inner_text() if text_el else ""
                        if not content.strip():
                            continue

                        # 提取作者
                        author_el = await card.query_selector(".name")
                        author = await author_el.inner_text() if author_el else "匿名"

                        # 提取时间
                        time_el = await card.query_selector(".from")
                        pub_time = await time_el.inner_text() if time_el else ""

                        # 合规：跳过标记为"仅粉丝可见"的内容
                        if await card.query_selector(".txt-cert"):
                            continue

                        crawled_item = CrawledItem(
                            title=f"@{author}的微博",
                            content=self._strip_html_tags(content),
                            source_platform="微博",
                            original_url=url,
                            published_at=self._parse_weibo_time(pub_time),
                            is_public=True,
                            interaction_data={
                                "author": author,
                                "source": "playwright_search",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析搜索卡片失败: {e}")
                        continue

            finally:
                await browser.close()

        return items

    async def _crawl_user_page(self, account_id: str) -> List[CrawledItem]:
        """
        使用 Playwright 采集微博用户公开主页。

        合规约束（严格遵守）：
          - 不登录，仅访问公开主页
          - 仅采集首屏可见内容，不滚动加载更多
          - 跳过"仅粉丝可见"标记的内容
          - 请求间隔 >= 4 秒

        参数:
            account_id: 微博用户 UID

        返回:
            公开博文列表

        异常:
            NotImplementedError: 当 Playwright 未安装时抛出
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright 未安装")
            raise NotImplementedError("Playwright 未安装")

        items = []
        url = self.USER_PAGE_URL.format(account_id=account_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1920, "height": 1080})
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # 合规：等待页面加载，不主动滚动
                await asyncio.sleep(self.REQUEST_INTERVAL)

                # 检测页面是否可访问（可能被重定向到登录页）
                if "passport" in page.url or "login" in page.url:
                    self.logger.warning(f"用户 {account_id} 的主页需要登录才能访问，跳过")
                    return []

                # 提取首屏可见的博文卡片
                # 微博页面结构: .WB_feed_type 为每条微博的容器
                feed_items = await page.query_selector_all(".WB_feed_type, .wbpro-feed-card")

                for feed in feed_items:
                    try:
                        # 提取博文文本
                        text_el = await feed.query_selector(".WB_text, .wbpro-cnt")
                        if not text_el:
                            continue
                        content = await text_el.inner_text()
                        if not content.strip():
                            continue

                        # 合规：跳过标记为"仅粉丝可见"的内容
                        # 微博使用特定 class 标记可见性受限内容
                        if await feed.query_selector(".WB_text .txt-cert, .icon_yh"):
                            self.logger.debug("跳过仅粉丝可见的内容")
                            continue

                        # 提取发布时间
                        time_el = await feed.query_selector(".WB_from, .wbpro-time")
                        pub_time = await time_el.inner_text() if time_el else ""

                        # 提取作者昵称
                        name_el = await feed.query_selector(".W_fb, .wbpro-nick")
                        author = await name_el.inner_text() if name_el else "未知用户"

                        crawled_item = CrawledItem(
                            title=f"@{author}的微博",
                            content=self._strip_html_tags(content),
                            source_platform="微博",
                            original_url=url,
                            published_at=self._parse_weibo_time(pub_time),
                            is_public=True,
                            interaction_data={
                                "author": author,
                                "account_id": account_id,
                                "source": "playwright_user_page",
                            },
                        )
                        items.append(crawled_item)

                    except Exception as e:
                        self.logger.debug(f"解析用户主页博文失败: {e}")
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

        参数:
            text: 可能包含 HTML 标签的文本

        返回:
            清洗后的纯文本
        """
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"<!\-\-.*?\-\->", "", text, flags=re.DOTALL)
        # 去除微博特有标签（如话题 #[话题]# ）
        text = re.sub(r"#.*?#", lambda m: m.group(0).replace("#", ""), text)
        # 去除 @用户 的链接标签
        text = re.sub(r"@\S+", lambda m: m.group(0).split(">")[-1] if ">" in m.group(0) else m.group(0), text)
        return text.strip()

    @staticmethod
    def _parse_weibo_time(time_str: str) -> str:
        """
        解析微博时间字符串为标准格式。

        微博时间格式多样：
          - 绝对时间: "Mon Jul 08 10:30:00 +0800 2026"
          - 相对时间: "5分钟前"、"1小时前"、"昨天 10:30"
          - 日期格式: "07-08"（今年）

        参数:
            time_str: 微博原始时间字符串

        返回:
            标准格式时间 "YYYY-MM-DD HH:MM:SS"
        """
        if not time_str or not time_str.strip():
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        time_str = time_str.strip()

        # 相对时间处理
        now = datetime.now()

        if "分钟前" in time_str:
            try:
                minutes = int(re.search(r"(\d+)分钟前", time_str).group(1))
                dt = now - __import__("datetime").timedelta(minutes=minutes)
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

        if "昨天" in time_str:
            yesterday = now - __import__("datetime").timedelta(days=1)
            # 尝试提取时间部分
            time_match = re.search(r"(\d{1,2}:\d{2})", time_str)
            if time_match:
                return f"{yesterday.strftime('%Y-%m-%d')} {time_match.group(1)}:00"

        # 绝对时间解析尝试
        formats = [
            "%a %b %d %H:%M:%S %z %Y",   # 微博标准格式
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue

        return now.strftime("%Y-%m-%d %H:%M:%S")

    # -------------------------------------------------------------------
    # API 层预留接口
    # -------------------------------------------------------------------

    async def _fetch_by_official_api(self, endpoint: str, params: dict = None) -> dict:
        """
        微博开放平台官方 API 调用（预留接口，需要 app_key）。

        使用说明：
          - 需要在配置中设置 weibo_app_key 和 weibo_app_secret
          - 需要通过 OAuth 2.0 获取 access_token
          - 当前为预留空实现，待接入官方 API 后完善

        参数:
            endpoint: API 端点路径
            params: 请求参数

        返回:
            API 返回的 JSON 数据

        异常:
            NotImplementedError: 当前未实现，调用即抛出
        """
        # TODO: 待接入微博开放平台 API
        # 需要配置:
        #   - WEIBO_APP_KEY: 应用 App Key
        #   - WEIBO_APP_SECRET: 应用 App Secret
        #   - WEIBO_ACCESS_TOKEN: OAuth 访问令牌
        self.logger.warning("微博官方 API 接口暂未实现，请配置 app_key 后启用")
        raise NotImplementedError("微博官方 API 接口待开发，请配置 App Key 后启用")
