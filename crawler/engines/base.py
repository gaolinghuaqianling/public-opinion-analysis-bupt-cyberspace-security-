# -*- coding: utf-8 -*-
"""
采集引擎抽象基类模块
====================
定义所有采集引擎的统一接口和通用行为，包括：
  - 请求延时控制（随机延时，防止被封禁）
  - 随机 User-Agent 轮换
  - robots.txt 合规检查
  - 完整的 crawl 流程编排（fetch → parse，含异常处理）
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

from crawler.models import CrawledItem

# 模块级日志记录器
logger = logging.getLogger(__name__)


class BaseEngine(ABC):
    """
    采集引擎抽象基类，定义统一接口。

    所有具体的采集引擎（API引擎、轻量接口引擎、浏览器渲染引擎）
    都必须继承此类，并实现 fetch() 和 parse() 两个抽象方法。

    属性:
        engine_type (str): 引擎类型标识，子类应覆盖此属性
        _last_request_time (float): 上次请求的时间戳（用于延时控制）
        _request_count (int): 累计请求次数（用于统计和限速）
    """

    # 引擎类型标识，子类必须覆盖
    engine_type: str = "base"

    def __init__(self):
        """初始化引擎，设置请求计数和最后请求时间。"""
        self._last_request_time = 0
        self._request_count = 0

    # ------------------------------------------------------------------
    # 抽象方法：子类必须实现
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch(self, url: str, params: dict = None, **kwargs) -> Optional[dict]:
        """
        发起请求，返回原始响应数据。

        参数:
            url (str): 请求的目标 URL
            params (dict, optional): 请求参数（查询字符串或请求体）
            **kwargs: 其他请求选项（如 headers, method, timeout 等）

        返回:
            Optional[dict]: 成功时返回包含原始响应数据的字典，失败时返回 None
        """
        pass

    @abstractmethod
    async def parse(self, raw_data: dict) -> List[CrawledItem]:
        """
        解析原始数据，返回标准化 CrawledItem 列表。

        参数:
            raw_data (dict): fetch() 返回的原始响应数据

        返回:
            List[CrawledItem]: 解析后的标准化数据项列表
        """
        pass

    # ------------------------------------------------------------------
    # 通用方法：完整的采集流程
    # ------------------------------------------------------------------

    async def crawl(self, url: str, params: dict = None, **kwargs) -> List[CrawledItem]:
        """
        完整的 crawl 流程：robots 检查 → 延时控制 → fetch → parse。

        该方法串联了整个采集流程，包括：
          1. 检查 robots.txt 是否允许访问目标 URL
          2. 强制请求间随机延时（防止高频请求被封禁）
          3. 调用 fetch() 获取原始数据
          4. 调用 parse() 解析原始数据
          5. 异常处理和日志记录

        参数:
            url (str): 请求的目标 URL
            params (dict, optional): 请求参数
            **kwargs: 其他请求选项

        返回:
            List[CrawledItem]: 解析后的标准化数据项列表，失败时返回空列表
        """
        # 第一步：检查 robots.txt 是否允许访问
        parsed_url = urlparse(url)
        path = parsed_url.path or "/"
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        if not self.check_robots_txt(base_url, path):
            logger.warning(
                "robots.txt 禁止访问，跳过: %s（路径: %s）", url, path
            )
            return []

        # 第二步：强制请求间延时
        self.enforce_delay()

        # 第三步：发起请求并解析
        try:
            raw_data = await self.fetch(url, params=params, **kwargs)
            if raw_data is None:
                logger.warning("请求未返回有效数据: %s", url)
                return []

            self._request_count += 1
            self._last_request_time = time.time()

            items = await self.parse(raw_data)
            logger.info(
                "采集完成 [%s]: %s，获取 %d 条数据",
                self.engine_type, url, len(items),
            )
            return items

        except asyncio.CancelledError:
            logger.info("采集任务被取消: %s", url)
            raise
        except Exception as e:
            logger.error("采集异常 [%s]: %s，错误: %s", self.engine_type, url, e)
            return []

    # ------------------------------------------------------------------
    # 通用工具方法
    # ------------------------------------------------------------------

    def enforce_delay(self, min_delay: float = 3.0, max_delay: float = 7.0):
        """
        强制请求间延时，使用随机延时防止被封禁。

        计算从上次请求到当前的间隔时间，如果不足最小延时则等待。
        在满足最小延时的基础上，额外随机等待一段时间（最大不超过 max_delay）。

        参数:
            min_delay (float): 最小延时秒数，默认 3.0 秒
            max_delay (float): 最大延时秒数，默认 7.0 秒
        """
        # 计算自上次请求以来已经过的时间
        elapsed = time.time() - self._last_request_time
        # 在最小和最大延时之间随机选取一个目标延时
        target_delay = random.uniform(min_delay, max_delay)

        if elapsed < target_delay:
            wait_seconds = target_delay - elapsed
            logger.debug("请求延时等待 %.2f 秒（已过 %.2f 秒）", wait_seconds, elapsed)
            time.sleep(wait_seconds)
        else:
            # 已经过了足够的间隔，但在高并发场景下仍添加少量随机延时
            extra = random.uniform(0, 1.0)
            if extra > 0.5:
                time.sleep(extra)
                logger.debug("额外延时 %.2f 秒", extra)

    def get_random_ua(self) -> str:
        """
        从 UA（User-Agent）池中获取随机 User-Agent 字符串。

        用于伪装浏览器指纹，降低被识别为爬虫的概率。

        返回:
            str: 随机选取的 User-Agent 字符串
        """
        try:
            from crawler.config import USER_AGENT_POOL
        except ImportError:
            # 如果 config 模块尚未创建，使用内置的备用 UA 池
            USER_AGENT_POOL = self._default_ua_pool()

        if not USER_AGENT_POOL:
            return self._default_ua_pool()[0]

        return random.choice(USER_AGENT_POOL)

    @staticmethod
    def _default_ua_pool() -> List[str]:
        """
        内置的备用 User-Agent 池。

        包含常见浏览器的最新版本 User-Agent 字符串，
        当 crawler.config 不可用时作为降级方案。

        返回:
            List[str]: User-Agent 字符串列表
        """
        return [
            # Chrome 120+ (Windows)
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # Chrome 119 (Windows)
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            # Chrome 120 (macOS)
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # Firefox 121 (Windows)
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0",
            # Edge 120 (Windows)
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
            # Safari 17 (macOS)
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        ]

    def check_robots_txt(self, base_url: str, path: str) -> bool:
        """
        检查目标站点的 robots.txt 是否允许爬取指定路径。

        下载并解析目标站点的 robots.txt 文件，使用通配符 User-Agent (*)
        检查是否允许访问给定的路径。

        参数:
            base_url (str): 站点基础 URL，例如 "https://example.com"
            path (str): 要检查的访问路径，例如 "/api/v1/news"

        返回:
            bool: 如果允许访问返回 True，不允许或检查失败返回 False

        注意:
            - 如果 robots.txt 下载失败或解析失败，默认返回 True（放行），
              因为部分站点未配置 robots.txt
            - 使用通配符 User-Agent (*) 进行检查
        """
        try:
            robots_url = urljoin(base_url.rstrip("/") + "/", "robots.txt")
            rp = RobotFileParser()
            rp.set_url(robots_url)

            # 同步读取 robots.txt（在 crawl 流程中调用，不使用 async）
            try:
                import urllib.request
                request = urllib.request.Request(
                    robots_url,
                    headers={"User-Agent": self.get_random_ua()},
                    timeout=10,
                )
                response = urllib.request.urlopen(request, timeout=10)
                rp.parse(response.read().decode("utf-8", errors="ignore").splitlines())
            except Exception as e:
                # robots.txt 获取失败，默认放行（很多站点没有 robots.txt）
                logger.debug("robots.txt 获取失败（%s），默认允许访问: %s", e, base_url)
                return True

            # 使用通配符 User-Agent 检查路径是否允许
            can_fetch = rp.can_fetch("*", path)

            if not can_fetch:
                logger.warning(
                    "robots.txt 禁止访问: %s（路径: %s）", base_url, path
                )

            return can_fetch

        except Exception as e:
            logger.debug("robots.txt 检查异常（%s），默认允许访问: %s", e, base_url)
            return True
