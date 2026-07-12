# -*- coding: utf-8 -*-
"""
标准化数据模型 — 爬虫核心数据结构
==========================================================
架构位置: 数据模型层，被引擎层、清洗层、存储层共同引用
职责:
    1. 定义 CrawledItem — 标准化采集数据结构（所有平台统一格式）
    2. 定义 CrawlTask  — 标准化抓取任务结构
    3. 提供与 dict / storage row 的转换方法，屏蔽各平台差异
==========================================================
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class CrawledItem:
    """
    标准化采集数据结构。

    所有平台适配器（人民网RSS、微博、抖音、知乎等）抓取到的原始数据，
    最终都应映射为 CrawledItem 实例，再交由清洗层处理和存储层入库。

    属性:
        title:            标题（必填）
        content:          正文/摘要（必填）
        author:           作者/发布者
        source_platform:  来源平台名（如 "人民网-时政"、"微博"）
        published_at:     发布时间，格式 YYYY-MM-DD HH:MM:SS
        original_url:     原文链接
        interaction_data: 互动数据 {likes, comments, shares, views}
        sentiment_text:   情感分析用的原始文本（可选，通常等于 content）
        crawl_method:     采集方式标识 (rss/api/lightweight/playwright)
        crawl_time:       采集时间，格式 YYYY-MM-DD HH:MM:SS
        is_public:        是否公开内容（True 表示可被分析）
        extra:            扩展字段，各平台特有数据存放于此
    """

    # ----- 必填字段 -----
    title: str = ""
    content: str = ""

    # ----- 可选字段 -----
    author: str = ""
    source_platform: str = ""
    published_at: str = ""
    original_url: str = ""
    interaction_data: Dict = field(default_factory=dict)
    sentiment_text: str = ""
    crawl_method: str = ""
    crawl_time: str = ""
    is_public: bool = True
    extra: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """
        转换为普通字典。

        返回:
            包含所有字段（含 interaction_data 和 extra）的字典
        """
        return asdict(self)

    def to_storage_row(self) -> dict:
        """
        转换为 raw_news 表兼容的入库字典。

        仅提取 raw_news 表中存在的列:
            - title
            - content
            - source_platform
            - published_at
            - original_url
        crawled_at 和 status 由存储层自动填充。

        interaction_data 和 extra 等扩展字段会被序列化为 JSON
        追加到 content 末尾（以换行分隔），避免丢失数据。

        返回:
            可直接用于 INSERT 语句的字典
        """
        row = {
            "title": self.title,
            "content": self.content,
            "source_platform": self.source_platform,
            "published_at": self.published_at,
            "original_url": self.original_url,
        }

        # 如果有扩展数据，追加到 content 末尾，防止信息丢失
        extras = {}
        if self.interaction_data:
            extras["interaction_data"] = self.interaction_data
        if self.author:
            extras["author"] = self.author
        if self.extra:
            extras.update(self.extra)
        if self.crawl_method:
            extras["crawl_method"] = self.crawl_method

        if extras:
            extra_json = json.dumps(extras, ensure_ascii=False)
            row["content"] = f"{self.content}\n<!-- EXTRA:{extra_json} -->" if self.content else extra_json

        return row


@dataclass
class CrawlTask:
    """
    标准化抓取任务结构。

    调度层创建任务后写入 crawl_tasks 表，引擎层消费并执行，
    执行完成后更新状态和结果数。

    属性:
        task_id:       任务唯一标识（UUID）
        platform:      平台标识 (people_rss/weibo/douyin/zhihu/xiaohongshu/bilibili)
        task_type:     任务类型 (keyword/account/hotlist/rss)
        target:        抓取目标（关键词/账号ID/RSS URL）
        keywords:      关键词过滤列表
        priority:      优先级（数值越大越优先）
        created_at:    创建时间
        status:        状态: pending / running / success / failed
        result_count:  采集结果数
        error_message: 错误信息（失败时记录原因）
    """

    task_id: str = ""
    platform: str = ""
    task_type: str = ""
    target: str = ""
    keywords: List = field(default_factory=list)
    priority: int = 0
    created_at: str = ""
    status: str = "pending"
    result_count: int = 0
    error_message: str = ""

    def to_dict(self) -> dict:
        """
        转换为普通字典。

        返回:
            包含所有字段的字典（keywords 列表也会被包含）
        """
        return asdict(self)
