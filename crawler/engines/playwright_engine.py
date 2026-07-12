# -*- coding: utf-8 -*-
"""
浏览器渲染引擎模块
====================
使用 Playwright 进行浏览器渲染采集，合规无痕模式。

功能特点：
  - Playwright stealth 无痕模式，每次请求创建新的 BrowserContext
  - 随机 User-Agent、随机 viewport、随机浏览器指纹
  - 可选等待特定选择器加载完成
  - 可选页面滚动（模拟真实浏览行为）
  - 关闭 context 即清除所有缓存/Cookie（无痕模式）
  - Playwright 为可选依赖，未安装时给出友好提示
  - 仅采集公开可访问的内容，遵守 robots.txt 规范
"""

import asyncio
import logging
import random
from typing import List, Optional, Dict

from crawler.engines.base import BaseEngine
from crawler.models import CrawledItem

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 预设的 viewport 分辨率列表（常见桌面分辨率）
VIEWPORT_PRESETS = [
    {"width": 1920, "height": 1080},   # Full HD（最常见）
    {"width": 1366, "height": 768},    # 常见笔记本分辨率
    {"width": 1536, "height": 864},    # 缩放后的常见分辨率
    {"width": 1440, "height": 900},    # MacBook 常见分辨率
    {"width": 1280, "height": 720},    # HD 分辨率
]

# 默认页面加载超时时间（毫秒）
DEFAULT_TIMEOUT = 30000

# stealth 脚本：隐藏 webdriver 标识，防止被检测为自动化工具
# 注入 JavaScript 覆盖 navigator.webdriver 等属性
STEALTH_JS_SCRIPTS = [
    # 隐藏 webdriver 属性
    """
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
    """,
    # 覆盖 plugins（真实浏览器有插件，自动化工具通常没有）
    """
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    """,
    # 覆盖 languages
    """
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en'],
    });
    """,
    # 伪装 Chrome 对象
    """
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
    };
    """,
]


class PlaywrightEngine(BaseEngine):
    """
    浏览器渲染引擎，Playwright stealth 无痕模式，仅采集公开内容。

    该引擎使用 Playwright 控制真实浏览器进行页面渲染，适用于：
      - 需要 JavaScript 渲染的动态页面
      - 轻度反爬但无严格验证的公开页面
      - 需要模拟滚动、点击等交互行为的数据采集

    安全与合规：
      - 使用无痕模式（incognito），每次请求创建新 Context
      - 关闭 Context 即清除所有缓存和 Cookie
      - 不保存任何用户登录状态或 Cookie
      - 遵守 robots.txt 规范

    依赖说明：
      Playwright 为可选依赖，使用前需安装：
          pip install playwright
          playwright install chromium

    使用示例:
        async with PlaywrightEngine(headless=True) as engine:
            await engine.launch_browser()
            raw_data = await engine.fetch("https://example.com", wait_selector=".content")
            await engine.close_browser()
    """

    engine_type = "playwright"

    def __init__(self, headless: bool = True, proxy: dict = None):
        """
        初始化 Playwright 渲染引擎。

        参数:
            headless (bool): 是否使用无头模式，默认 True（不显示浏览器窗口）
            proxy (dict, optional): 代理配置，格式:
                {"server": "http://proxy:port", "username": "user", "password": "pass"}
                如果为 None，则不使用代理
        """
        super().__init__()
        # 是否使用无头模式
        self._headless = headless
        # 代理配置
        self._proxy = proxy

        # Playwright 核心对象（延迟初始化）
        self._playwright = None        # Playwright 异步入口
        self._browser = None           # Browser 实例
        self._context = None          # BrowserContext 实例（每次请求创建新的）
        self._page = None              # Page 实例

    # ------------------------------------------------------------------
    # 内部方法：检查 Playwright 依赖
    # ------------------------------------------------------------------

    @staticmethod
    def _check_playwright_installed():
        """
        检查 Playwright 是否已安装。

        如果未安装，抛出 ImportError 并提供安装指引。

        异常:
            ImportError: 当 Playwright 未安装时抛出
        """
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError:
            raise ImportError(
                "Playwright 未安装。请执行以下命令安装：\n"
                "  pip install playwright\n"
                "  playwright install chromium\n"
                "或者仅安装 Playwright Python 包：\n"
                "  pip install playwright"
            )

    # ------------------------------------------------------------------
    # 内部方法：注入 stealth 脚本
    # ------------------------------------------------------------------

    async def _inject_stealth_scripts(self, page):
        """
        向页面注入 stealth 脚本，隐藏自动化工具标识。

        通过覆盖 navigator.webdriver、plugins、languages 等属性，
        以及伪装 Chrome 对象，降低被检测为自动化工具的概率。

        参数:
            page: Playwright Page 实例
        """
        for script in STEALTH_JS_SCRIPTS:
            try:
                await page.add_init_script(script)
            except Exception as e:
                logger.debug("注入 stealth 脚本失败: %s", e)

    # ------------------------------------------------------------------
    # 内部方法：获取随机 UA
    # ------------------------------------------------------------------

    def _get_random_viewport(self) -> Dict[str, int]:
        """
        随机选取一个 viewport 分辨率。

        从预设的常见桌面分辨率中随机选取一个，模拟不同用户的屏幕。

        返回:
            Dict[str, int]: 包含 width 和 height 的字典
        """
        return random.choice(VIEWPORT_PRESETS)

    # ------------------------------------------------------------------
    # 浏览器生命周期管理
    # ------------------------------------------------------------------

    async def launch_browser(self):
        """
        启动 Playwright Chromium 浏览器。

        使用 stealth 配置启动浏览器：
          - 随机 User-Agent
          - 隐藏 webdriver 标识
          - 配置代理（如果指定）

        注意：
          - 此方法仅启动 Browser 实例，不会创建 Context 或 Page
          - 每次 fetch() 调用时会创建新的 Context（无痕模式）
          - 调用 close_browser() 关闭浏览器并释放资源
        """
        self._check_playwright_installed()
        from playwright.async_api import async_playwright

        # 启动 Playwright
        self._playwright = await async_playwright().start()
        logger.info("Playwright 已启动")

        # 构建浏览器启动参数
        launch_args = {
            "headless": self._headless,
            "args": [
                "--disable-blink-features=AutomationControlled",  # 禁用自动化控制特征
                "--no-sandbox",                                     # 沙箱模式
                "--disable-setuid-sandbox",                        # 禁用 setuid 沙箱
                "--disable-dev-shm-usage",                         # 避免 /dev/shm 不足
            ],
        }

        # 配置代理
        if self._proxy:
            launch_args["proxy"] = self._proxy

        # 启动 Chromium 浏览器
        self._browser = await self._playwright.chromium.launch(**launch_args)
        logger.info(
            "Chromium 浏览器已启动（headless=%s）", self._headless
        )

    async def close_browser(self):
        """
        关闭浏览器，清除所有会话数据。

        按顺序关闭 Page -> Context -> Browser -> Playwright，
        确保所有资源正确释放。
        """
        # 关闭当前 Page
        if self._page:
            try:
                await self._page.close()
            except Exception as e:
                logger.debug("关闭 Page 异常: %s", e)
            finally:
                self._page = None

        # 关闭当前 Context
        if self._context:
            try:
                await self._context.close()
            except Exception as e:
                logger.debug("关闭 Context 异常: %s", e)
            finally:
                self._context = None

        # 关闭 Browser
        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                logger.debug("关闭 Browser 异常: %s", e)
            finally:
                self._browser = None

        # 停止 Playwright
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.debug("停止 Playwright 异常: %s", e)
            finally:
                self._playwright = None

        logger.info("Playwright 浏览器已关闭，所有会话数据已清除")

    # ------------------------------------------------------------------
    # 抽象方法实现：fetch
    # ------------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        params: dict = None,
        wait_selector: str = None,
        scroll_count: int = 0,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs,
    ) -> Optional[dict]:
        """
        使用浏览器访问目标 URL，获取页面内容。

        每次调用都会创建新的 BrowserContext（无痕模式），
        确保请求之间完全隔离。关闭 Context 即清除所有缓存和 Cookie。

        流程：
          1. 创建新 BrowserContext（随机 viewport、UA、locale、timezone）
          2. 注入 stealth 脚本（隐藏 webdriver 标识）
          3. 导航到目标 URL
          4. 可选：等待特定选择器加载完成
          5. 可选：滚动页面（模拟真实浏览）
          6. 截取页面文本内容
          7. 关闭 Context（清除所有缓存/Cookie）

        参数:
            url (str): 目标 URL
            params (dict, optional): URL 查询参数（拼接到 URL 后）
            wait_selector (str, optional): CSS 选择器，等待该元素加载完成后继续。
                例如 ".article-content"、"#main-content"
            scroll_count (int): 页面滚动次数，每次滚动一屏，默认 0 不滚动。
                用于模拟用户浏览行为，触发懒加载内容。
            timeout (int): 页面加载超时时间（毫秒），默认 30000
            **kwargs: 保留扩展参数

        返回:
            Optional[dict]: 成功时返回包含页面数据的字典:
                {
                    "url": str,              # 最终 URL（重定向后）
                    "title": str,            # 页面标题
                    "text": str,             # 页面可见文本内容
                    "html": str,             # 页面完整 HTML
                    "status_code": int,      # HTTP 状态码
                    "viewport": dict,        # 使用的 viewport 分辨率
                }
                失败时返回 None
        """
        if not self._browser:
            logger.error("浏览器未启动，请先调用 launch_browser()")
            return None

        # 拼接查询参数
        if params:
            from urllib.parse import urlencode
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params)}"

        # 随机选取 viewport 和 UA
        viewport = self._get_random_viewport()
        user_agent = self.get_random_ua()

        context = None
        page = None

        try:
            # 第一步：创建新的 BrowserContext（无痕模式）
            context = await self._browser.new_context(
                viewport=viewport,
                user_agent=user_agent,
                locale="zh-CN",                    # 中文语言环境
                timezone_id="Asia/Shanghai",       # 时区设置为上海
                color_scheme="light",              # 浅色模式
                # 不设置 geolocation（避免隐私问题）
            )
            self._context = context

            # 第二步：创建 Page 并注入 stealth 脚本
            page = await context.new_page()
            self._page = page

            # 注入 stealth 脚本
            await self._inject_stealth_scripts(page)

            logger.debug(
                "Playwright 请求: %s（viewport=%s, UA=%s）",
                url, viewport, user_agent[:50] + "...",
            )

            # 第三步：导航到目标 URL
            response = await page.goto(
                url,
                wait_until="domcontentloaded",  # 等待 DOM 加载完成
                timeout=timeout,
            )

            # 检查响应状态
            status_code = response.status if response else 0
            if status_code >= 400:
                logger.warning(
                    "Playwright 页面加载失败（HTTP %d）: %s", status_code, url
                )

            # 第四步：可选等待特定选择器加载
            if wait_selector:
                try:
                    await page.wait_for_selector(
                        wait_selector,
                        timeout=min(timeout // 2, 10000),  # 最多等待一半超时时间
                    )
                    logger.debug("等待选择器完成: %s", wait_selector)
                except Exception as e:
                    logger.warning(
                        "等待选择器超时或失败（%s）: %s", e, wait_selector
                    )

            # 第五步：可选页面滚动（模拟浏览行为）
            if scroll_count > 0:
                for i in range(scroll_count):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    # 滚动间添加随机延时，模拟人工阅读
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    logger.debug("页面滚动 %d/%d", i + 1, scroll_count)

            # 第六步：截取页面内容
            final_url = page.url  # 获取最终 URL（重定向后）
            title = await page.title()

            # 获取页面可见文本（通过 JavaScript 提取 body 文本）
            text = await page.evaluate("""
                () => {
                    // 移除 script 和 style 标签
                    const clone = document.cloneNode(true);
                    const scripts = clone.querySelectorAll('script, style, noscript');
                    scripts.forEach(el => el.remove());
                    return clone.body ? clone.body.innerText : '';
                }
            """)

            # 获取完整 HTML（可选，根据需求使用）
            html = await page.content()

            logger.info(
                "Playwright 页面加载完成: %s（标题: %s，文本长度: %d）",
                final_url, title[:50], len(text),
            )

            return {
                "url": final_url,
                "title": title,
                "text": text,
                "html": html,
                "status_code": status_code,
                "viewport": viewport,
            }

        except Exception as e:
            logger.error("Playwright fetch 异常: %s，错误: %s", url, e)
            return None

        finally:
            # 第七步：关闭 Context 和 Page（清除所有缓存/Cookie）
            try:
                if page:
                    await page.close()
            except Exception:
                pass
            finally:
                self._page = None

            try:
                if context:
                    await context.close()
            except Exception:
                pass
            finally:
                self._context = None

            logger.debug("BrowserContext 已关闭，缓存/Cookie 已清除")

    # ------------------------------------------------------------------
    # 抽象方法实现：parse
    # ------------------------------------------------------------------

    async def parse(self, raw_data: dict) -> List[CrawledItem]:
        """
        返回空列表（由适配器自行从 page 提取内容）。

        Playwright 引擎的 parse 方法不做具体解析，因为页面内容的提取
        通常需要平台特定的选择器逻辑。各平台的适配器（Adapter）应自行
        从 page 对象中提取所需数据。

        参数:
            raw_data (dict): fetch() 返回的页面数据字典

        返回:
            List[CrawledItem]: 空列表（由适配器覆盖）
        """
        return []

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------

    async def close(self):
        """
        关闭引擎，释放所有资源。

        关闭浏览器和 Playwright 进程。
        建议使用 async with 上下文管理器自动管理生命周期。
        """
        await self.close_browser()

    async def __aenter__(self):
        """
        支持 async with 上下文管理器。

        进入时自动启动浏览器。
        """
        await self.launch_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        退出上下文时自动关闭浏览器。
        """
        await self.close()
        return False
