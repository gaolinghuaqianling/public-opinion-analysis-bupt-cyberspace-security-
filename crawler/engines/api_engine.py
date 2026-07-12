# -*- coding: utf-8 -*-
"""
官方 API 采集引擎模块
====================
通过调用各平台开放平台 API 进行数据采集。

功能特点：
  - 支持多种鉴权方式（api_key / oauth2 / bearer_token）
  - 鉴权信息仅内存保存，不持久化 Cookie
  - 自动附加鉴权 header 到每次请求
  - 内置请求重试机制（最多 3 次，指数退避）
  - 预留自动 token 刷新逻辑
  - 通用 JSON API 响应解析（子类可覆盖实现平台特定解析）
"""

import asyncio
import logging
import time
from typing import List, Optional, Dict

import httpx

from crawler.engines.base import BaseEngine
from crawler.models import CrawledItem

# 模块级日志记录器
logger = logging.getLogger(__name__)

# 默认请求超时时间（秒）
DEFAULT_TIMEOUT = 30

# 最大重试次数
MAX_RETRIES = 3

# 指数退避的初始等待时间（秒）
RETRY_BACKOFF_BASE = 2


class APIEngine(BaseEngine):
    """
    官方 API 采集引擎，用于调用各平台开放平台 API。

    该引擎支持常见的 API 鉴权方式，并提供了通用的 JSON 响应解析能力。
    子类可以覆盖 parse() 方法实现平台特定的数据提取逻辑。

    鉴权方式:
        - api_key: 通过 query 参数或 header 传递 API Key
        - oauth2: 使用 OAuth2 Bearer Token
        - bearer_token: 直接使用 Bearer Token

    安全说明:
        鉴权信息仅保存在内存中，不会写入磁盘或持久化 Cookie。

    使用示例:
        engine = APIEngine(api_base_url="https://api.example.com")
        engine.configure_auth(auth_type="api_key", api_key="your_key")
        items = await engine.crawl("/v1/news")
    """

    engine_type = "api"

    def __init__(self, api_base_url: str, auth_config: dict = None):
        """
        初始化 API 采集引擎。

        参数:
            api_base_url (str): API 基础 URL，例如 "https://api.example.com"
            auth_config (dict, optional): 鉴权配置字典，格式取决于鉴权方式。
                如果提供，将自动调用 configure_auth() 进行配置。
                格式示例:
                    {"auth_type": "api_key", "api_key": "xxx", "api_secret": "yyy"}
                    {"auth_type": "oauth2", "access_token": "xxx"}
                    {"auth_type": "bearer_token", "access_token": "xxx"}
        """
        super().__init__()
        # API 基础 URL，用于拼接完整的请求地址
        self._api_base_url = api_base_url.rstrip("/")

        # 鉴权配置（仅内存保存）
        self._auth_type: Optional[str] = None          # 鉴权类型
        self._api_key: Optional[str] = None             # API Key
        self._api_secret: Optional[str] = None         # API Secret（部分平台需要）
        self._access_token: Optional[str] = None       # OAuth2 / Bearer Token

        # HTTP 客户端（异步）
        self._client: Optional[httpx.AsyncClient] = None

        # 如果初始化时直接传入了鉴权配置，自动配置
        if auth_config:
            self.configure_auth(**auth_config)

    # ------------------------------------------------------------------
    # 鉴权配置
    # ------------------------------------------------------------------

    def configure_auth(
        self,
        auth_type: str,
        api_key: str = None,
        api_secret: str = None,
        access_token: str = None,
    ):
        """
        配置鉴权方式。

        支持的鉴权类型:
            - "api_key": 使用 API Key 鉴权（通过 header 传递）
            - "oauth2": 使用 OAuth2 Bearer Token 鉴权
            - "bearer_token": 直接使用 Bearer Token 鉴权

        参数:
            auth_type (str): 鉴权类型，可选值: "api_key", "oauth2", "bearer_token"
            api_key (str, optional): API Key（api_key 模式必需）
            api_secret (str, optional): API Secret（部分平台需要，与 api_key 配合使用）
            access_token (str, optional): 访问令牌（oauth2 / bearer_token 模式必需）

        异常:
            ValueError: 当鉴权类型不支持或缺少必需参数时抛出
        """
        supported_types = {"api_key", "oauth2", "bearer_token"}
        if auth_type not in supported_types:
            raise ValueError(
                f"不支持的鉴权类型: {auth_type}，支持的类型: {supported_types}"
            )

        self._auth_type = auth_type
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token

        # 参数校验
        if auth_type == "api_key" and not api_key:
            raise ValueError("api_key 鉴权模式必须提供 api_key 参数")
        if auth_type in ("oauth2", "bearer_token") and not access_token:
            raise ValueError(f"{auth_type} 鉴权模式必须提供 access_token 参数")

        logger.info("已配置 API 鉴权: 类型=%s", auth_type)

    # ------------------------------------------------------------------
    # Token 刷新（预留）
    # ------------------------------------------------------------------

    async def _refresh_token(self):
        """
        自动刷新 access_token 的预留接口。

        当 OAuth2 token 过期时，子类可以覆盖此方法实现自动刷新逻辑。
        默认实现仅记录警告日志。

        典型的刷新流程：
            1. 使用 refresh_token 向授权服务器请求新的 access_token
            2. 更新 self._access_token
            3. 日志记录刷新结果
        """
        logger.warning(
            "API Engine: Token 可能已过期，但当前未配置自动刷新逻辑。"
            "请在子类中覆盖 _refresh_token() 方法实现 token 刷新。"
        )

    # ------------------------------------------------------------------
    # 内部方法：构建请求 Header
    # ------------------------------------------------------------------

    def _build_auth_headers(self) -> Dict[str, str]:
        """
        根据当前鉴权配置构建 HTTP 请求 Header。

        返回:
            Dict[str, str]: 包含鉴权信息的 header 字典
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self._auth_type == "api_key":
            # API Key 模式：通过 X-API-Key header 传递
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            if self._api_secret:
                headers["X-API-Secret"] = self._api_secret

        elif self._auth_type in ("oauth2", "bearer_token"):
            # Bearer Token 模式：通过 Authorization header 传递
            if self._access_token:
                headers["Authorization"] = f"Bearer {self._access_token}"

        return headers

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
            # 创建新的异步客户端，设置默认超时
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT),
                headers=self._build_auth_headers(),
            )
        return self._client

    # ------------------------------------------------------------------
    # 抽象方法实现：fetch
    # ------------------------------------------------------------------

    async def fetch(
        self,
        url: str,
        params: dict = None,
        method: str = "GET",
        **kwargs,
    ) -> Optional[dict]:
        """
        构建 HTTP 请求并调用 API，返回原始响应数据。

        自动附加鉴权 header，支持 GET / POST / PUT / DELETE 方法。
        内置重试机制：遇到网络错误或 5xx 服务器错误时自动重试（最多 3 次）。

        参数:
            url (str): API 端点路径（如果以 / 开头则拼接到 api_base_url 后）
            params (dict, optional): 查询参数
            method (str): HTTP 方法，默认 "GET"
            **kwargs: 传递给 httpx 的额外参数（如 json, data 等）

        返回:
            Optional[dict]: 成功时返回解析后的 JSON 字典，失败时返回 None
        """
        # 如果 url 是相对路径，拼接到基础 URL
        if url.startswith("/"):
            full_url = f"{self._api_base_url}{url}"
        else:
            full_url = url

        client = await self._get_client()

        # 重试逻辑：最多 MAX_RETRIES 次，指数退避
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method=method.upper(),
                    url=full_url,
                    params=params,
                    **kwargs,
                )

                # 检查 HTTP 状态码
                if response.status_code == 200:
                    # 尝试解析 JSON 响应
                    try:
                        return response.json()
                    except Exception as e:
                        logger.error(
                            "API 响应 JSON 解析失败（状态码 200）: %s，错误: %s",
                            full_url, e,
                        )
                        return {"_raw_text": response.text, "_status_code": 200}

                elif response.status_code == 401:
                    # Token 过期，尝试刷新
                    logger.warning(
                        "API 鉴权失败（401），尝试刷新 Token（第 %d 次尝试）",
                        attempt,
                    )
                    await self._refresh_token()

                    # 刷新 token 后更新客户端 header
                    if self._client:
                        self._client.headers.update(self._build_auth_headers())

                    # 如果是最后一次尝试，不再重试
                    if attempt == MAX_RETRIES:
                        logger.error("Token 刷新后仍鉴权失败: %s", full_url)
                        return None
                    continue

                elif response.status_code >= 500:
                    # 服务器错误，重试
                    logger.warning(
                        "API 服务器错误（%d），第 %d/%d 次重试: %s",
                        response.status_code, attempt, MAX_RETRIES, full_url,
                    )
                    if attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF_BASE ** attempt
                        logger.debug("等待 %.1f 秒后重试...", wait)
                        await asyncio.sleep(wait)
                        continue
                    return None

                elif response.status_code == 429:
                    # 请求频率超限，等待更长时间后重试
                    logger.warning(
                        "API 请求频率超限（429），第 %d/%d 次重试: %s",
                        attempt, MAX_RETRIES, full_url,
                    )
                    if attempt < MAX_RETRIES:
                        # 429 通常需要更长的等待时间
                        wait = RETRY_BACKOFF_BASE ** attempt * 2
                        logger.debug("频率限制，等待 %.1f 秒后重试...", wait)
                        await asyncio.sleep(wait)
                        continue
                    return None

                else:
                    # 其他 HTTP 错误（4xx）
                    logger.warning(
                        "API 请求失败（%d）: %s", response.status_code, full_url,
                    )
                    return {
                        "_status_code": response.status_code,
                        "_error": response.text[:500],
                    }

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    "API 请求超时，第 %d/%d 次重试: %s，错误: %s",
                    attempt, MAX_RETRIES, full_url, e,
                )
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    await asyncio.sleep(wait)

            except httpx.ConnectError as e:
                last_error = e
                logger.error(
                    "API 连接失败: %s，错误: %s", full_url, e,
                )
                # 连接错误不重试（通常是网络或 DNS 问题）
                return None

            except Exception as e:
                last_error = e
                logger.error(
                    "API 请求异常，第 %d/%d 次重试: %s，错误: %s",
                    attempt, MAX_RETRIES, full_url, e,
                )
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    await asyncio.sleep(wait)

        logger.error(
            "API 请求最终失败（已重试 %d 次）: %s，最后错误: %s",
            MAX_RETRIES, full_url, last_error,
        )
        return None

    # ------------------------------------------------------------------
    # 抽象方法实现：parse
    # ------------------------------------------------------------------

    async def parse(self, raw_data: dict) -> List[CrawledItem]:
        """
        通用 JSON API 响应解析。

        从 API 响应中提取数据列表，支持常见的 API 响应格式：
          - {"data": [...]} — 数据在 data 字段中
          - {"items": [...]} — 数据在 items 字段中
          - {"results": [...]} — 数据在 results 字段中
          - 直接返回列表格式 [...]
          - {"_raw_text": "...", "_status_code": 200} — 非标准响应

        子类应覆盖此方法实现平台特定的数据提取逻辑。

        参数:
            raw_data (dict): fetch() 返回的原始响应数据

        返回:
            List[CrawledItem]: 解析后的标准化数据项列表
        """
        if not raw_data:
            return []

        # 处理非标准响应（如 JSON 解析失败时的回退格式）
        if "_raw_text" in raw_data:
            logger.debug("收到非标准 API 响应，跳过解析")
            return []

        # 处理错误响应
        if "_error" in raw_data:
            logger.warning("API 返回错误: %s", raw_data.get("_error"))
            return []

        # 尝试从常见字段中提取数据列表
        data_list = None

        for key in ("data", "items", "results", "list", "records"):
            if key in raw_data:
                value = raw_data[key]
                if isinstance(value, list):
                    data_list = value
                    break
                # 有些 API 将列表嵌套在 data 字段的对象中
                elif isinstance(value, dict):
                    for sub_key in ("list", "items", "records", "data"):
                        if sub_key in value and isinstance(value[sub_key], list):
                            data_list = value[sub_key]
                            break

        # 如果上述字段都没有，检查原始数据是否本身就是列表
        if data_list is None and isinstance(raw_data, list):
            data_list = raw_data

        if data_list is None:
            logger.debug("API 响应中未找到可解析的数据列表")
            return []

        # 将每条数据包装为 CrawledItem
        items = []
        for item in data_list:
            if isinstance(item, dict):
                items.append(CrawledItem(raw_data=item))
            elif isinstance(item, (str, int, float)):
                # 简单类型的值直接包装
                items.append(CrawledItem(raw_data={"value": item}))

        logger.debug("API 解析: 原始 %d 条，有效 %d 条", len(data_list), len(items))
        return items

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
            logger.debug("API Engine: HTTP 客户端已关闭")

    async def __aenter__(self):
        """支持 async with 上下文管理器。"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时自动关闭客户端。"""
        await self.close()
        return False
