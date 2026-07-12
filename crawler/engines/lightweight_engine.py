# -*- coding: utf-8 -*-
"""
轻量接口爬虫引擎模块
====================
用于无鉴权公开接口的数据采集（热榜、XHR 接口等）。

功能特点：
  - 基于 httpx.AsyncClient 的轻量 HTTP 请求
  - 自动注入随机 User-Agent 和 Referer 伪装浏览器请求
  - 支持自定义 headers 覆盖
  - 自动处理编码检测（UTF-8 / GBK / GB2312）
  - 超时设置 15 秒
  - 内置请求重试机制（最多 3 次，指数退避）
  - 基础 JSON 解析（返回空列表，由适配器覆盖实现平台特定解析）
"""

import asyncio
import logging
from typing import List, Optional, Dict
from urllib.parse import urlparse

import httpx

from crawler.engines.base import BaseEngine
from crawler.models import CrawledItem

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 默认请求超时时间（秒）
DEFAULT_TIMEOUT = 15

# 最大重试次数
MAX_RETRIES = 3

# 指数退避的初始等待时间（秒）
RETRY_BACKOFF_BASE = 2

# 支持的编码列表（按优先级排序）
SUPPORTED_ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "big5"]


class LightweightEngine(BaseEngine):
    """
    轻量接口爬虫引擎，用于无鉴权公开接口（热榜、XHR 接口）。

    该引擎专注于轻量级 HTTP 请求，适用于：
      - 各平台热搜/热榜数据接口
      - 公开的 XHR / AJAX 数据接口
      - 无需登录或鉴权的公开 API

    安全说明:
        不涉及任何用户认证信息，仅采集公开可访问的数据。

    使用示例:
        async with LightweightEngine() as engine:
            data = await engine.fetch("https://example.com/api/hotlist")
    """

    engine_type = "lightweight"

    def __init__(self):
        """
        初始化轻量接口引擎。

        创建 httpx.AsyncClient 实例，设置默认超时和随机 User-Agent。
        """
        super().__init__()
        # HTTP 客户端（异步）
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # 内部方法：构建默认请求 Header
    # ------------------------------------------------------------------

    def _build_default_headers(self) -> Dict[str, str]:
        """
        构建默认的 HTTP 请求 Header。

        自动注入随机 User-Agent，并设置常见的浏览器 Header。

        返回:
            Dict[str, str]: 默认请求 header 字典
        """
        return {
            "User-Agent": self.get_random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

    # ------------------------------------------------------------------
    # 内部方法：自动生成 Referer
    # ------------------------------------------------------------------

    def _build_referer(self, url: str) -> str:
        """
        根据目标 URL 自动生成合理的 Referer 头。

        从目标 URL 中提取域名，构造一个同域的 Referer，
        使请求看起来像是从该站点的页面发起的 AJAX 请求。

        参数:
            url (str): 目标 URL

        返回:
            str: 生成的 Referer 头值
        """
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}/"
        except Exception:
            return url

    # ------------------------------------------------------------------
    # 内部方法：获取或创建 HTTP 客户端
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """
        获取或创建 httpx.AsyncClient 实例。

        采用惰性创建方式，首次调用时创建客户端，
        后续调用复用同一实例（提升连接池效率）。

        返回:
            httpx.AsyncClient: 配置好的异步 HTTP 客户端
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                headers=self._build_default_headers(),
                follow_redirects=True,  # 自动跟随重定向
            )
        return self._client

    # ------------------------------------------------------------------
    # 内部方法：编码检测与文本解码
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_and_decode(raw_bytes: bytes) -> str:
        """
        自动检测编码并解码响应内容。

        按优先级尝试 UTF-8、GBK、GB2312、GB18030、Big5 编码，
        第一个成功解码的编码即为最终结果。

        参数:
            raw_bytes (bytes): 原始响应字节

        返回:
            str: 解码后的文本内容
        """
        # 优先使用 httpx 自动检测的编码（如果有 Content-Type 声明）
        for encoding in SUPPORTED_ENCODINGS:
            try:
                text = raw_bytes.decode(encoding)
                # 简单校验：如果解码后包含替换字符，可能是错误编码
                if "\ufffd" not in text:
                    return text
            except (UnicodeDecodeError, LookupError):
                continue

        # 所有编码都失败，使用 UTF-8 并忽略错误
        return raw_bytes.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # 抽象方法实现：fetch
    # ------------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        params: dict = None,
        headers: dict = None,
        method: str = "GET",
        **kwargs,
    ) -> Optional[dict]:
        """
        发起 HTTP 请求，返回原始响应数据。

        自动注入随机 UA 和 Referer，支持自定义 headers 覆盖。
        自动检测响应编码（UTF-8 / GBK / GB2312 等）。
        内置重试机制：遇到网络错误或 5xx 错误时自动重试（最多 3 次）。

        参数:
            url (str): 请求的目标 URL
            params (dict, optional): 查询参数
            headers (dict, optional): 自定义请求头（会与默认头合并，自定义优先）
            method (str): HTTP 方法，默认 "GET"
            **kwargs: 传递给 httpx 的额外参数

        返回:
            Optional[dict]: 成功时返回包含响应数据的字典:
                {
                    "status_code": int,       # HTTP 状态码
                    "url": str,               # 最终 URL（重定向后）
                    "text": str,              # 解码后的响应文本
                    "json": dict or list,     # 尝试 JSON 解析的结果（可能为 None）
                    "headers": dict,           # 响应头
                }
                失败时返回 None
        """
        client = await self._get_client()

        # 合并默认 header 和自定义 header（自定义优先）
        merged_headers = self._build_default_headers()
        # 自动注入 Referer
        merged_headers["Referer"] = self._build_referer(url)
        # 自定义 header 覆盖默认值
        if headers:
            merged_headers.update(headers)

        # 重试逻辑
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    headers=merged_headers,
                    **kwargs,
                )

                # 成功响应
                if response.status_code == 200:
                    # 获取原始字节并自动检测编码
                    raw_bytes = response.content
                    text = self._detect_and_decode(raw_bytes)

                    # 尝试 JSON 解析
                    json_data = None
                    if "application/json" in response.headers.get("content-type", ""):
                        try:
                            json_data = response.json()
                        except Exception:
                            pass

                    return {
                        "status_code": response.status_code,
                        "url": str(response.url),
                        "text": text,
                        "json": json_data,
                        "headers": dict(response.headers),
                    }

                elif response.status_code == 403:
                    # 禁止访问
                    logger.warning(
                        "轻量引擎请求被禁止（403）: %s", url,
                    )
                    return None

                elif response.status_code == 429:
                    # 频率限制
                    logger.warning(
                        "轻量引擎请求频率超限（429），第 %d/%d 次重试: %s",
                        attempt, MAX_RETRIES, url,
                    )
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF_BASE ** attempt * 2
                        await asyncio.sleep(wait)
                        continue
                    return None

                elif response.status_code >= 500:
                    # 服务器错误
                    logger.warning(
                        "轻量引擎服务器错误（%d），第 %d/%d 次重试: %s",
                        response.status_code, attempt, MAX_RETRIES, url,
                    )
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF_BASE ** attempt
                        await asyncio.sleep(wait)
                        continue
                    return None

                else:
                    # 其他 HTTP 错误
                    logger.warning(
                        "轻量引擎请求失败（%d）: %s",
                        response.status_code, url,
                    )
                    return None

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "轻量引擎请求超时，第 %d/%d 次重试: %s，错误: %s",
                    attempt, MAX_RETRIES, url, e,
                )
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    await asyncio.sleep(wait)

            except httpx.ConnectError as e:
                last_error = e
                logger.error(
                    "轻量引擎连接失败: %s，错误: %s", url, e,
                )
                # 连接错误通常不重试（DNS 或网络问题）
                return None

            except Exception as e:
                last_error = e
                logger.error(
                    "轻量引擎请求异常，第 %d/%d 次重试: %s，错误: %s",
                    attempt, MAX_RETRIES, url, e,
                )
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    await asyncio.sleep(wait)

        logger.error(
            "轻量引擎请求最终失败（已重试 %d 次）: %s，最后错误: %s",
            MAX_RETRIES, url, last_error,
        )
        return None

    # ------------------------------------------------------------------
    # 抽象方法实现：parse
    # ------------------------------------------------------------------

    async def parse(self, raw_data: dict) -> List[CrawledItem]:
        """
        基础 JSON 解析（返回空列表）。

        轻量引擎的 parse 方法不做具体解析，由各平台的适配器（Adapter）
        覆盖此方法实现平台特定的数据提取逻辑。

        如果 raw_data 中包含 "json" 字段且为列表类型，
        则尝试将其中的每一项包装为 CrawledItem。

        参数:
            raw_data (dict): fetch() 返回的原始响应数据

        返回:
            List[CrawledItem]: 解析后的标准化数据项列表（通常为空）
        """
        if not raw_data:
            return []

        # 如果有 JSON 数据且为列表，尝试基础包装
        json_data = raw_data.get("json")
        if isinstance(json_data, list):
            items = []
            for item in json_data:
                if isinstance(item, dict):
                    items.append(CrawledItem(raw_data=item))
            return items

        # 默认返回空列表，由适配器覆盖
        return []

    # ------------------------------------------------------------------
    # 资源管理
    # ------------------------------------------------------------------

    async def close(self):
        """
        关闭 HTTP 客户端连接。

        在引擎不再使用时调用，释放网络资源。
        建议使用 async with 上下文管理器自动管理生命周期。
        """
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("Lightweight Engine: HTTP 客户端已关闭")

    async def __aenter__(self):
        """支持 async with 上下文管理器。"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时自动关闭客户端。"""
        await self.close()
        return False
