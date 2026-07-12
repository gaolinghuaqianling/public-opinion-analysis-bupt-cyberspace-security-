# -*- coding: utf-8 -*-
"""
平台适配器抽象基类

所有平台适配器都必须继承 BaseAdapter，并实现其定义的抽象方法。
本基类提供：
  1. 统一的接口规范（execute_task / crawl_hotlist / crawl_by_keyword）
  2. 通用的过滤工具方法（filter_by_keywords / filter_public_only）
  3. 统一的日志管理（每个适配器使用独立命名的 logger）

子类只需关注平台特定的采集逻辑，无需重复实现通用功能。
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from crawler.models import CrawledItem, CrawlTask


class BaseAdapter(ABC):
    """
    平台适配器抽象基类

    属性:
        platform_name: 平台显示名称（如 "微博"、"抖音"），用于日志和前端展示
        platform_key: 平台标识符（如 "weibo"、"douyin"），用于注册和路由
        supported_task_types: 本适配器支持的任务类型列表，如 ["hotlist", "keyword"]
    """

    platform_name: str = ""          # 平台显示名（如 "微博"）
    platform_key: str = ""           # 平台标识（如 "weibo"）
    supported_task_types: list = []  # 支持的任务类型（如 ["hotlist", "keyword", "account"]）

    def __init__(self):
        """初始化适配器，创建专属 logger"""
        self.logger = logging.getLogger(f"crawler.adapter.{self.platform_key}")

    # -------------------------------------------------------------------
    # 必须实现的抽象方法（子类必须覆盖）
    # -------------------------------------------------------------------

    @abstractmethod
    async def execute_task(self, task: CrawlTask) -> List[CrawledItem]:
        """
        执行抓取任务，返回标准化的 CrawledItem 列表。

        这是适配器的核心入口方法，根据 CrawlTask 中的 task_type 字段
        分发到对应的采集方法（hotlist / keyword / account 等）。

        参数:
            task: 抓取任务对象，包含任务类型、关键词、配置等

        返回:
            标准化后的 CrawledItem 列表
        """
        pass

    @abstractmethod
    async def crawl_hotlist(self) -> List[CrawledItem]:
        """
        爬取平台热榜（所有适配器必须实现的基础能力）。

        每个平台的热榜数据来源不同，子类需自行实现：
        - 人民网：遍历所有 RSS 频道
        - 微博：调用热搜公开接口
        - 抖音：调用热搜 XHR 接口
        - 知乎：调用热榜 API

        返回:
            热榜内容列表，每条封装为 CrawledItem
        """
        pass

    @abstractmethod
    async def crawl_by_keyword(self, keyword: str) -> List[CrawledItem]:
        """
        按关键词搜索公开内容。

        参数:
            keyword: 搜索关键词

        返回:
            匹配关键词的公开内容列表，每条封装为 CrawledItem
        """
        pass

    # -------------------------------------------------------------------
    # 可选覆盖的方法（提供默认实现，子类按需覆盖）
    # -------------------------------------------------------------------

    async def crawl_by_account(self, account_id: str) -> List[CrawledItem]:
        """
        按账号采集公开内容（默认不支持，子类按需覆盖）。

        默认实现直接返回空列表并记录警告日志。
        需要支持账号采集的子类（如微博适配器）应覆盖此方法。

        参数:
            account_id: 平台上的用户/账号标识（如微博 UID）

        返回:
            该账号的公开内容列表，默认返回空列表
        """
        self.logger.warning(f"{self.platform_name} 暂不支持按账号采集")
        return []

    # -------------------------------------------------------------------
    # 通用工具方法（所有子类共享）
    # -------------------------------------------------------------------

    def filter_by_keywords(self, items: List[CrawledItem], keywords: list) -> List[CrawledItem]:
        """
        根据关键词过滤采集结果（标题或正文包含关键词即命中）。

        使用大小写不敏感匹配，关键词列表中任一关键词命中即保留。

        参数:
            items: 待过滤的 CrawledItem 列表
            keywords: 关键词列表，如 ["经济", "政策"]

        返回:
            过滤后的 CrawledItem 列表
        """
        if not keywords:
            return items

        result = []
        for item in items:
            # 将标题和正文拼接后统一进行关键词匹配
            text = (item.title + " " + item.content).lower()
            if any(kw.lower() in text for kw in keywords):
                result.append(item)
        return result

    def filter_public_only(self, items: List[CrawledItem]) -> List[CrawledItem]:
        """
        仅保留公开内容，过滤掉非公开（私密/仅粉丝可见）的条目。

        参数:
            items: 待过滤的 CrawledItem 列表

        返回:
            is_public=True 的 CrawledItem 列表
        """
        return [item for item in items if item.is_public]
