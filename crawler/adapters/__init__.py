# -*- coding: utf-8 -*-
"""
平台适配器层：每个平台独立适配器，继承统一基类

本模块提供统一适配器注册与获取机制，上层调用者只需通过平台标识
（如 "weibo"、"douyin"）即可获取对应的适配器实例，无需关心内部实现细节。

支持的适配器：
  - people_rss : 人民网 RSS 适配器
  - weibo      : 微博适配器
  - douyin     : 抖音适配器
  - zhihu      : 知乎适配器
  - xiaohongshu: 小红书适配器（预留）
  - bilibili   : B站适配器
"""

from crawler.adapters.base import BaseAdapter
from crawler.adapters.people_rss import PeopleRSSAdapter
from crawler.adapters.weibo import WeiboAdapter
from crawler.adapters.douyin import DouyinAdapter
from crawler.adapters.zhihu import ZhihuAdapter
from crawler.adapters.xiaohongshu import XiaohongshuAdapter
from crawler.adapters.bilibili import BilibiliAdapter

# -----------------------------------------------------------------------
# 适配器注册表：平台标识 -> 适配器类
# -----------------------------------------------------------------------
# 新增平台适配器时，只需在此处注册即可，无需修改上层调用代码
ADAPTER_REGISTRY = {
    "people_rss": PeopleRSSAdapter,
    "weibo": WeiboAdapter,
    "douyin": DouyinAdapter,
    "zhihu": ZhihuAdapter,
    "xiaohongshu": XiaohongshuAdapter,
    "bilibili": BilibiliAdapter,
}


def get_adapter(platform: str) -> BaseAdapter:
    """
    根据平台标识获取对应的适配器实例。

    参数:
        platform: 平台标识字符串，如 "weibo"、"douyin" 等

    返回:
        对应平台的适配器实例（已初始化）

    异常:
        ValueError: 当传入不支持的平台标识时抛出
    """
    adapter_cls = ADAPTER_REGISTRY.get(platform)
    if adapter_cls is None:
        raise ValueError(f"不支持的平台: {platform}，支持: {list(ADAPTER_REGISTRY.keys())}")
    return adapter_cls()


def list_supported_platforms() -> list:
    """
    返回所有已注册的平台标识列表。

    返回:
        平台标识字符串列表，如 ["people_rss", "weibo", "douyin", ...]
    """
    return list(ADAPTER_REGISTRY.keys())
