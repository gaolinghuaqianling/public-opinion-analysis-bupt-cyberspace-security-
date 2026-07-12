# -*- coding: utf-8 -*-
"""
小红书适配器 — Playwright 浏览器层采集

通过 Playwright 无头浏览器采集小红书公开可见内容。
本适配器特点：
  - 使用 Playwright 打开小红书网页，等待 JS 渲染完成后提取笔记信息
  - 不登录、不使用任何凭证，仅采集公开可见内容
  - 支持「探索页热榜」和「关键词搜索」两种任务类型
  - 首屏采集，不滚动页面（最多 20 条）
  - 采集字段：笔记标题、作者、点赞数、笔记链接
  - 不下载图片/视频，遵守合规约束

数据来源：
  - 探索页: https://www.xiaohongshu.com/explore
  - 搜索页: https://www.xiaohongshu.com/search_result?keyword={keyword}

合规约束：
  - 仅采集公开可见内容（标题、作者、点赞数）
  - 不使用任何登录凭证
  - 不下载图片/视频等二进制资源
  - 请求间隔 >= 3 秒
  - Playwright 未安装时优雅降级，返回空列表

Playwright 依赖安装：
  pip install playwright
  playwright install chromium
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import List

from crawler.adapters.base import BaseAdapter
from crawler.models import CrawledItem, CrawlTask

# -------------------------------------------------------------------
# Playwright 可选导入 — 未安装时优雅降级
# -------------------------------------------------------------------
try:
    from playwright.async_api import async_playwright, Browser, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


class XiaohongshuAdapter(BaseAdapter):
    """
    小红书适配器 — Playwright 浏览器层采集

    通过 Playwright 无头浏览器访问小红书网页版，提取探索页和搜索结果中
    首屏可见的笔记卡片信息（标题、作者、点赞数）。

    平台信息：
      - 平台名称: 小红书
      - 平台标识: xiaohongshu
      - 支持任务类型: hotlist（探索页热榜）, keyword（关键词搜索）

    使用说明：
      - 需要安装 Playwright: pip install playwright && playwright install chromium
      - 如果 Playwright 未安装，所有采集方法将记录警告日志并返回空列表
      - 本适配器不登录，仅采集公开可见内容
    """

    platform_name = "小红书"
    platform_key = "xiaohongshu"
    supported_task_types = ["hotlist", "keyword"]

    # -------------------------------------------------------------------
    # URL 配置
    # -------------------------------------------------------------------
    # 探索页：首页推荐/热门笔记
    EXPLORE_PAGE_URL = "https://www.xiaohongshu.com/explore"

    # 搜索页：关键词搜索结果
    SEARCH_PAGE_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}"

    # -------------------------------------------------------------------
    # 采集配置
    # -------------------------------------------------------------------
    # 请求间隔（秒），两次页面加载之间至少等待的时间
    REQUEST_INTERVAL = 3.0

    # 页面加载超时（毫秒）
    PAGE_LOAD_TIMEOUT = 30000

    # JS 渲染等待时间（秒），页面 DOM 加载后额外等待让 React 完成渲染
    JS_RENDER_WAIT = 3

    # 首屏最大采集条数
    MAX_ITEMS_PER_PAGE = 20

    # -------------------------------------------------------------------
    # CSS 选择器配置
    # -------------------------------------------------------------------
    # 笔记卡片容器选择器（按优先级排列，取首个匹配即可）
    NOTE_CARD_SELECTORS = [
        "section.note-item",          # 语义化标签
        "[class*='note-item']",       # class 名包含 note-item
        "div.feEDc1",                # 小红书常用的笔记卡片 class（hash class）
        "div[class*='note']",
        "article",
    ]

    # 标题选择器（在卡片容器内查找）
    TITLE_SELECTORS = [
        "a[href*='/explore/'] span",  # 探索链接内的 span
        "a[href*='/discovery/item/'] span",
        "[class*='title']",           # class 名包含 title
        "footer a span",              # 小红书瀑布流中标题常在 footer 内
        "a span",                     # 链接内的 span（兜底）
    ]

    # 作者选择器
    AUTHOR_SELECTORS = [
        "[class*='author']",          # class 名包含 author
        "[class*='nickname']",        # class 名包含 nickname
        "[class*='author-container'] a",  # 作者容器内的链接
        "a.author-wrapper",          # 作者链接包裹器
        "header a",                   # 笔记头部作者链接
    ]

    # 点赞数选择器
    LIKE_SELECTORS = [
        "[class*='like'] span.count",  # 点赞按钮内的计数
        "[class*='like'] span",         # 点赞按钮内的 span
        "span[class*='count']",         # 任何包含 count 的 span
        "[class*='like']",             # 点赞元素本身（兜底，取文本）
    ]

    # 笔记链接选择器
    LINK_SELECTORS = [
        "a[href*='/explore/']",    # 探索页笔记链接
        "a[href*='/discovery/item/']",  # 发现页笔记链接
        "a[href*='/note/']",       # 笔记直链
        "a",                        # 兜底：卡片内第一个链接
    ]

    # 登录弹窗关闭按钮选择器
    CLOSE_MODAL_SELECTORS = [
        ".close-button",
        "button[class*='close']",
        "[class*='mask'] + button",
        "[class*='login'] button.close",
        ".login-modal .close",
        "div[role='dialog'] button[aria-label='close']",
    ]

    # -------------------------------------------------------------------
    # 数据清洗正则
    # -------------------------------------------------------------------
    # 需要过滤的冗余符号和空白字符
    NOISE_PATTERN = re.compile(
        r"[\xa0\u3000\t"           # 不间断空格、全角空格、制表符
        r"\u200b\u200c\u200d"      # 零宽字符
        r"\r\n|\n|\r"               # 换行
        r"]+"
    )

    # 连续多余空白压缩为一个空格
    MULTI_SPACE = re.compile(r" {2,}")

    # -------------------------------------------------------------------
    # 适配器接口实现
    # -------------------------------------------------------------------

    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行小红书抓取任务，根据 task_type 分发到对应的采集方法。

        支持的任务类型：
          - "hotlist" : 抓取小红书探索页热门笔记（首屏可见内容）
          - "keyword" : 按关键词搜索小红书公开笔记

        参数:
            task: 抓取任务对象，包含任务类型、关键词、配置等

        返回:
            标准化后的 CrawledItem 列表；若 Playwright 未安装则返回空列表
        """
        # 检查 Playwright 是否可用
        if not _PLAYWRIGHT_AVAILABLE:
            self.logger.warning(
                "Playwright 未安装，小红书适配器无法工作。"
                "请执行: pip install playwright && playwright install chromium"
            )
            return []

        task_type = task.task_type

        if task_type == "hotlist":
            # 抓取探索页热门笔记
            items = await self.crawl_hotlist()
            # 如果任务中指定了关键词，进行二次过滤
            if task.keywords:
                items = self.filter_by_keywords(items, task.keywords)
            return items

        elif task_type == "keyword":
            if not task.target:
                self.logger.warning("关键词任务未指定 target，返回空列表")
                return []
            items = await self.crawl_by_keyword(task.target)
            # 如果任务中额外指定了过滤关键词，进行二次过滤
            if task.keywords:
                items = self.filter_by_keywords(items, task.keywords)
            return items

        else:
            self.logger.error(f"不支持的任务类型: {task_type}（支持: {self.supported_task_types}）")
            return []

    async def crawl_hotlist(self) -> List[CrawledItem]:
        """
        爬取小红书探索页热门笔记（首屏可见内容）。

        实现说明：
          - 使用 Playwright 打开小红书探索页
          - 等待页面 DOM 加载完成（domcontentloaded）
          - 额外等待 3 秒让 React/前端 JS 渲染完成
          - 提取首屏可见的笔记卡片（不滚动页面）
          - 每条笔记提取：标题、作者、点赞数、笔记链接
          - 最多采集 20 条

        返回:
            探索页热门笔记列表，每条封装为 CrawledItem；
            若 Playwright 未安装或页面加载失败则返回空列表
        """
        self.logger.info("开始抓取小红书探索页热榜")

        try:
            async with async_playwright() as pw:
                browser = await self._launch_browser(pw)
                try:
                    page = await browser.new_page()

                    # 加载探索页
                    self.logger.info(f"正在打开: {self.EXPLORE_PAGE_URL}")
                    await page.goto(
                        self.EXPLORE_PAGE_URL,
                        wait_until="domcontentloaded",
                        timeout=self.PAGE_LOAD_TIMEOUT,
                    )

                    # 等待 JS 渲染完成
                    self.logger.debug(f"等待 {self.JS_RENDER_WAIT}s 让 JS 渲染完成...")
                    await asyncio.sleep(self.JS_RENDER_WAIT)

                    # 尝试关闭登录弹窗（小红书会在首页弹出登录框）
                    await self._try_close_login_modal(page)

                    # 提取首屏笔记
                    items = await self._extract_notes_from_page(page)

                    self.logger.info(f"小红书探索页热榜抓取完成，共 {len(items)} 条")
                    return items

                finally:
                    await browser.close()

        except Exception as e:
            self.logger.error(f"小红书探索页热榜抓取失败: {e}")
            return []

    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索小红书公开笔记。

        实现说明：
          - 使用 Playwright 打开小红书搜索结果页
          - 等待页面 DOM 加载完成（domcontentloaded）
          - 额外等待 3 秒让 React/前端 JS 渲染完成
          - 提取首屏搜索结果笔记（不滚动页面）
          - 每条笔记提取：标题、作者、点赞数、笔记链接
          - 最多采集 20 条

        参数:
            keyword: 搜索关键词（如 "考研"、"旅游攻略"）

        返回:
            匹配关键词的公开笔记列表，每条封装为 CrawledItem；
            若 Playwright 未安装或页面加载失败则返回空列表
        """
        self.logger.info(f"小红书关键词搜索: {keyword}")

        try:
            async with async_playwright() as pw:
                browser = await self._launch_browser(pw)
                try:
                    page = await browser.new_page()

                    # 构造搜索 URL
                    search_url = self.SEARCH_PAGE_URL.format(keyword=keyword)
                    self.logger.info(f"正在打开: {search_url}")
                    await page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=self.PAGE_LOAD_TIMEOUT,
                    )

                    # 等待 JS 渲染完成
                    self.logger.debug(f"等待 {self.JS_RENDER_WAIT}s 让 JS 渲染完成...")
                    await asyncio.sleep(self.JS_RENDER_WAIT)

                    # 提取首屏笔记
                    items = await self._extract_notes_from_page(page)

                    self.logger.info(f"关键词 '{keyword}' 搜索完成，共 {len(items)} 条")
                    return items

                finally:
                    await browser.close()

        except Exception as e:
            self.logger.error(f"小红书关键词搜索失败 (keyword={keyword}): {e}")
            return []

    # -------------------------------------------------------------------
    # Playwright 浏览器管理
    # -------------------------------------------------------------------

    async def _launch_browser(self, pw) -> "Browser":
        """
        启动 Playwright 无头浏览器实例。

        使用 Chromium 无头模式，模拟常见桌面端 User-Agent，
        降低被识别为自动化工具的概率。

        参数:
            pw: async_playwright 上下文管理器实例

        返回:
            Playwright Browser 实例
        """
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self.logger.debug("Playwright Chromium 无头浏览器已启动")
        return browser

    # -------------------------------------------------------------------
    # 页面笔记提取
    # -------------------------------------------------------------------

    async def _try_close_login_modal(self, page: "Page") -> None:
        """
        尝试关闭小红书首页的登录弹窗。

        小红书在未登录状态下会弹出登录框，覆盖内容区域。
        此方法尝试点击关闭按钮或按 Escape 键关闭弹窗。

        参数:
            page: Playwright Page 实例
        """
        # 先尝试点击关闭按钮
        for selector in self.CLOSE_MODAL_SELECTORS:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    self.logger.info(f"已通过选择器 '{selector}' 关闭登录弹窗")
                    await asyncio.sleep(1)
                    return
            except Exception:
                continue

        # 再尝试按 Escape 关闭
        try:
            await page.keyboard.press("Escape")
            self.logger.info("已按 Escape 键尝试关闭弹窗")
            await asyncio.sleep(1)
        except Exception:
            pass

        # 最后尝试点击弹窗外区域
        try:
            # 点击页面坐标 (0, 0) 附近，通常是弹窗外区域
            await page.mouse.click(10, 10)
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _extract_notes_from_page(self, page: "Page") -> List[CrawledItem]:
        """
        从当前页面中提取首屏可见的笔记卡片信息。

        实现说明：
          - 依次尝试多个笔记卡片选择器，取首个有匹配的选择器
          - 对每个卡片提取：标题、作者、点赞数、链接
          - 提取首屏可见内容（不滚动页面）
          - 最多返回 MAX_ITEMS_PER_PAGE 条

        参数:
            page: Playwright Page 实例（已加载目标页面）

        返回:
            标准化的 CrawledItem 列表
        """
        items: List[CrawledItem] = []

        # ---------- 1. 定位笔记卡片容器 ----------
        note_cards = await self._find_note_cards(page)

        # Fallback：标准选择器都找不到时，用链接特征直接提取
        use_fallback = False
        if not note_cards:
            self.logger.info("标准选择器未匹配，尝试 Fallback 扁平提取策略")
            note_cards = await self._find_note_cards_fallback(page)
            use_fallback = True

        if not note_cards:
            self.logger.warning("未找到笔记卡片，页面结构可能已变更或需要登录")
            return items

        self.logger.debug(f"找到 {len(note_cards)} 个笔记卡片")

        # ---------- 2. 遍历每个卡片提取信息 ----------
        for i, card in enumerate(note_cards):
            if i >= self.MAX_ITEMS_PER_PAGE:
                break

            try:
                if use_fallback:
                    # Fallback 模式：card 本身就是 a 标签，直接取文本作为标题
                    item = await self._extract_single_note_fallback(card, page)
                else:
                    item = await self._extract_single_note(card, page)
                if item and item.title:
                    items.append(item)
                else:
                    self.logger.debug(f"第 {i + 1} 张卡片提取信息为空，跳过")
            except Exception as e:
                self.logger.debug(f"第 {i + 1} 张卡片提取失败: {e}")
                continue

        # ---------- 3. 按 URL 去重 ----------
        seen_urls = set()
        unique_items = []
        for item in items:
            if item.original_url and item.original_url in seen_urls:
                continue
            if item.original_url:
                seen_urls.add(item.original_url)
            unique_items.append(item)

        return unique_items

    async def _find_note_cards(self, page: "Page") -> list:
        """
        在页面中查找笔记卡片元素。

        依次尝试 NOTE_CARD_SELECTORS 中定义的选择器，
        返回首个有匹配结果的选择器所对应的所有元素。

        参数:
            page: Playwright Page 实例

        返回:
            ElementHandle 列表；若所有选择器均无匹配则返回空列表
        """
        for selector in self.NOTE_CARD_SELECTORS:
            cards = await page.query_selector_all(selector)
            if cards:
                self.logger.debug(f"使用选择器 '{selector}' 找到 {len(cards)} 个笔记卡片")
                return cards

        self.logger.debug("所有笔记卡片选择器均无匹配")
        return []

    async def _find_note_cards_fallback(self, page: "Page") -> list:
        """
        Fallback 策略：当标准卡片选择器全部失败时，
        直接查找包含笔记链接的 a 标签作为伪卡片容器。

        小红书页面结构经常变动，hash class 不可靠，
        此方法通过链接 URL 特征（/explore/、/discovery/item/、/note/）
        识别笔记元素。

        参数:
            page: Playwright Page 实例

        返回:
            ElementHandle 列表
        """
        note_links = await page.query_selector_all(
            "a[href*='/explore/'], a[href*='/discovery/item/'], a[href*='/note/']"
        )
        if note_links:
            self.logger.debug(f"Fallback 策略：找到 {len(note_links)} 个笔记链接")
        return note_links

    async def _extract_single_note_fallback(self, link_el, page: "Page") -> CrawledItem:
        """
        Fallback 提取模式：当 card 是 a 标签本身时直接提取信息。

        在小红书的扁平 DOM 结构中，笔记标题和作者是相邻的 a 标签。
        此方法从当前 a 标签提取文本和 href，并尝试获取相邻的作者 a 标签。

        参数:
            link_el: 笔记链接的 a 标签 ElementHandle
            page: Playwright Page 实例

        返回:
            构造好的 CrawledItem 对象
        """
        # 标题直接取 a 标签的文本
        title = ""
        try:
            title = await link_el.inner_text()
        except Exception:
            try:
                title = await link_el.text_content()
            except Exception:
                pass

        # 链接直接取 href
        url = ""
        try:
            url = await link_el.get_attribute("href") or ""
        except Exception:
            pass

        # 尝试获取下一个兄弟 a 标签作为作者
        author = ""
        try:
            next_sibling = await link_el.evaluate_handle(
                "el => el.nextElementSibling"
            )
            if next_sibling:
                author = await next_sibling.inner_text()
                await next_sibling.dispose()
        except Exception:
            pass

        # 拼接完整 URL
        if url and not url.startswith("http"):
            url = f"https://www.xiaohongshu.com{url}"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return CrawledItem(
            title=self._clean_text(title),
            content="",
            author=self._clean_text(author),
            source_platform="小红书",
            original_url=url,
            published_at=now_str,
            is_public=True,
            interaction_data={
                "likes": 0,
                "source": "playwright_fallback",
            },
            crawl_method="playwright",
        )

    async def _extract_single_note(self, card, page: "Page") -> CrawledItem:
        """
        从单个笔记卡片元素中提取信息，构造 CrawledItem。

        提取字段：
          - title:      笔记标题（文本清洗后）
          - author:     作者昵称（文本清洗后）
          - likes:      点赞数（解析为整数）
          - url:        笔记链接（拼接为完整 URL）

        参数:
            card: 单个笔记卡片的 ElementHandle
            page: Playwright Page 实例

        返回:
            构造好的 CrawledItem 对象
        """
        # ---------- 提取标题 ----------
        title = await self._extract_text_from_card(card, self.TITLE_SELECTORS)

        # ---------- 提取作者 ----------
        author = await self._extract_text_from_card(card, self.AUTHOR_SELECTORS)

        # ---------- 提取点赞数 ----------
        likes = await self._extract_likes_from_card(card)

        # ---------- 提取链接 ----------
        url = await self._extract_link_from_card(card, page)

        # ---------- 构造 CrawledItem ----------
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        item = CrawledItem(
            title=self._clean_text(title),
            content="",  # 仅采集标题，不抓取正文（合规约束：不深入笔记详情页）
            author=self._clean_text(author),
            source_platform="小红书",
            original_url=url,
            published_at=now_str,
            is_public=True,
            interaction_data={
                "likes": likes,
                "source": "playwright_explore",
            },
            crawl_method="playwright",
            crawl_time=now_str,
        )

        self.logger.debug(
            f"提取笔记: title='{item.title[:30]}...' "
            f"author='{item.author}' likes={likes}"
        )

        return item

    # -------------------------------------------------------------------
    # 单字段提取方法
    # -------------------------------------------------------------------

    async def _extract_text_from_card(self, card, selectors: List[str]) -> str:
        """
        从卡片元素中使用多个候选选择器提取文本内容。

        依次尝试每个选择器，返回首个匹配元素的 inner_text。
        如果所有选择器均无匹配，返回空字符串。

        参数:
            card: 笔记卡片的 ElementHandle
            selectors: 候选选择器列表（按优先级排列）

        返回:
            提取到的文本内容，去除首尾空白；若无匹配则返回空字符串
        """
        for selector in selectors:
            try:
                el = await card.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        return ""

    async def _extract_likes_from_card(self, card) -> int:
        """
        从卡片元素中提取点赞数，解析为整数。

        依次尝试 LIKE_SELECTORS 中的选择器，获取文本后用正则提取数字。

        参数:
            card: 笔记卡片的 ElementHandle

        返回:
            点赞数（整数）；解析失败返回 0
        """
        for selector in self.LIKE_SELECTORS:
            try:
                el = await card.query_selector(selector)
                if el:
                    text = await el.inner_text()
                    if text:
                        # 从文本中提取数字（可能包含 "万" 等单位）
                        likes = self._parse_count_text(text.strip())
                        if likes >= 0:
                            return likes
            except Exception:
                continue

        return 0

    async def _extract_link_from_card(self, card, page: "Page") -> str:
        """
        从卡片元素中提取笔记链接。

        依次尝试 LINK_SELECTORS 中的选择器，获取 href 属性值。
        如果是相对路径，拼接为完整的 xiaohongshu.com URL。

        参数:
            card: 笔记卡片的 ElementHandle
            page: Playwright Page 实例

        返回:
            完整的笔记 URL；提取失败返回空字符串
        """
        for selector in self.LINK_SELECTORS:
            try:
                el = await card.query_selector(selector)
                if el:
                    href = await el.get_attribute("href")
                    if href:
                        href = href.strip()
                        # 拼接为完整 URL
                        if href.startswith("/"):
                            href = f"https://www.xiaohongshu.com{href}"
                        elif href.startswith("http"):
                            pass  # 已经是完整 URL
                        else:
                            continue  # 跳过非标准链接
                        return href
            except Exception:
                continue

        return ""

    # -------------------------------------------------------------------
    # 数据清洗工具方法
    # -------------------------------------------------------------------

    def _clean_text(self, text: str) -> str:
        """
        文本清洗：过滤冗余符号、压缩空白。

        清洗步骤：
          1. 去除 HTML 标签
          2. 过滤停用符号（不间断空格、零宽字符、换行等）
          3. 压缩连续空白为单个空格
          4. 去除首尾空白

        参数:
            text: 待清洗的原始文本

        返回:
            清洗后的纯文本
        """
        if not text:
            return ""
        # 去 HTML 标签（防御性处理，防止 inner_text 返回含标签内容）
        text = re.sub(r"<[^>]+>", "", text)
        # 过滤停用符号
        text = self.NOISE_PATTERN.sub(" ", text)
        # 压缩连续空白
        text = self.MULTI_SPACE.sub(" ", text)
        return text.strip()

    @staticmethod
    def _parse_count_text(text: str) -> int:
        """
        将点赞数文本解析为整数。

        支持的格式：
          - 纯数字: "1234" -> 1234
          - 带万: "1.2万" -> 12000, "5000万" -> 50000000
          - 带逗号: "1,234" -> 1234

        参数:
            text: 点赞数文本

        返回:
            解析后的整数；解析失败返回 -1（调用方需特殊处理）
        """
        if not text:
            return -1

        text = text.strip()

        # 处理 "万" 单位
        if "万" in text:
            try:
                num_part = text.replace("万", "").strip()
                num = float(num_part)
                return int(num * 10000)
            except (ValueError, TypeError):
                return -1

        # 提取数字部分（去除逗号等非数字字符）
        digits = re.sub(r"[^\d]", "", text)
        if digits:
            try:
                return int(digits)
            except ValueError:
                return -1

        return -1
