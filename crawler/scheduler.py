# -*- coding: utf-8 -*-
"""
任务调度层 — 爬虫核心调度器
==========================================================
架构位置: 调度层，位于最上层，负责协调适配器层、清洗层和存储层
职责:
    1. 下发单个/批量抓取任务（dispatch_task / dispatch_user_config）
    2. 执行单个抓取任务（execute_single_task）
    3. 并发控制执行待执行任务（run_pending_tasks）
    4. 定时循环抓取（run_scheduled_loop）
    5. 提供调度器统计信息（get_stats）
    6. 打通前端配置联动，根据用户关注平台和关键词批量创建任务
==========================================================
"""

import asyncio
import logging
import random
import uuid
from datetime import datetime
from typing import List, Optional

from crawler.models import CrawlTask, CrawledItem
from crawler.storage import create_task, update_task, save_crawled_items, get_pending_tasks, get_task_stats
from crawler.cleaners import cross_platform_normalize, validate_public_content
from crawler.adapters import get_adapter, list_supported_platforms
from crawler.config import MIN_DELAY, MAX_DELAY, MAX_CONCURRENT


class CrawlerScheduler:
    """爬虫任务调度器"""

    def __init__(self):
        # 初始化日志记录器
        self.logger = logging.getLogger("crawler.scheduler")
        # 调度器运行状态标志
        self._running = False
        # 当前并发任务集合，用于跟踪正在执行的任务
        self._concurrent_tasks = set()
        # 调度器运行统计: 已下发任务数、已采集条数、错误数
        self._stats = {"total_dispatched": 0, "total_collected": 0, "total_errors": 0}

    async def dispatch_task(self, platform: str, task_type: str, target: str,
                            keywords: list = None, priority: int = 0) -> str:
        """
        下发单个抓取任务。

        创建 CrawlTask 对象并写入 crawl_tasks 表，返回任务 ID。
        调用方可通过 task_id 追踪任务执行状态。

        参数:
            platform:  平台标识 (people_rss/weibo/douyin/zhihu 等)
            task_type: 任务类型 (hotlist/keyword/rss)
            target:    抓取目标（关键词/频道名/URL）
            keywords:  关键词过滤列表（可选）
            priority:  优先级，数值越大越优先执行（默认 0）

        返回:
            任务 ID (UUID 字符串)
        """
        # 构建标准化任务对象
        task = CrawlTask(
            task_id=str(uuid.uuid4()),
            platform=platform,
            task_type=task_type,
            target=target,
            keywords=keywords or [],
            priority=priority,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status="pending",
        )
        # 将任务记录写入数据库
        create_task(task)
        self._stats["total_dispatched"] += 1
        self.logger.info(f"任务已创建: {task.task_id} [{platform}/{task_type}] target={target}")
        return task.task_id

    async def dispatch_user_config(self, focus_platforms: list, focus_keywords: list):
        """
        根据用户配置批量下发抓取任务（打通前端配置联动）。

        执行逻辑:
            1. 为每个已配置的平台创建热榜抓取任务
            2. 为每个关键词在各平台创建关键词搜索任务

        参数:
            focus_platforms: 用户关注的平台名称列表 (如 ["微博", "知乎", "抖音"])
            focus_keywords:  用户关注的关键词列表 (如 ["AI", "高考"])

        返回:
            成功下发的任务 ID 列表
        """
        dispatched = []

        # 第一轮：为每个平台创建热榜抓取任务
        for platform_name in focus_platforms:
            # 将用户可读的平台名映射到系统内部平台标识
            platform_key = self._resolve_platform_key(platform_name)
            if platform_key:
                task_id = await self.dispatch_task(
                    platform=platform_key,
                    task_type="hotlist",
                    target=platform_name,
                    keywords=focus_keywords,
                )
                dispatched.append(task_id)

        # 第二轮：为每个关键词在各平台创建关键词搜索任务
        for keyword in focus_keywords:
            for platform_name in focus_platforms:
                platform_key = self._resolve_platform_key(platform_name)
                if platform_key:
                    task_id = await self.dispatch_task(
                        platform=platform_key,
                        task_type="keyword",
                        target=keyword,
                        keywords=focus_keywords,
                        priority=1,  # 关键词任务优先级略高
                    )
                    dispatched.append(task_id)

        self.logger.info(f"用户配置联动: 共下发 {len(dispatched)} 个任务")
        return dispatched

    def _resolve_platform_key(self, platform_name: str) -> Optional[str]:
        """
        将用户配置的平台名映射到系统平台标识。

        用户在前端配置的是中文名称（如"微博"、"知乎"），
        系统内部使用英文标识（如"weibo"、"zhihu"），
        此方法负责二者之间的映射。

        参数:
            platform_name: 用户可读的平台名称

        返回:
            系统平台标识字符串；若不在映射表中则返回 None
        """
        mapping = {
            "人民网": "people_rss", "微博": "weibo", "抖音": "douyin",
            "知乎": "zhihu", "小红书": "xiaohongshu", "B站": "bilibili",
        }
        return mapping.get(platform_name)

    async def execute_single_task(self, task: CrawlTask) -> int:
        """
        执行单个抓取任务，返回采集条数。

        完整执行流程:
            1. 将任务状态更新为 running
            2. 获取对应平台适配器并执行抓取
            3. 过滤公开内容
            4. 跨平台标准化清洗
            5. 批量入库到 raw_news 表
            6. 更新任务状态为 success 或 failed

        参数:
            task: 待执行的 CrawlTask 任务对象

        返回:
            成功入库的数据条数
        """
        # 标记任务为运行中
        task.status = "running"
        update_task(task.task_id, "running", 0, "")

        try:
            # 获取平台适配器并执行抓取
            adapter = get_adapter(task.platform)
            items = await adapter.execute_task(task)
            # 过滤仅保留公开内容
            items = adapter.filter_public_only(items)
            # 对每条数据进行跨平台标准化清洗
            cleaned_items = []
            for item in items:
                item = cross_platform_normalize(item)
                if validate_public_content(item):
                    cleaned_items.append(item)
            # 批量写入数据库
            count = save_crawled_items(cleaned_items)
            # 更新任务状态为成功
            task.status = "success"
            task.result_count = count
            update_task(task.task_id, "success", count, "")
            self._stats["total_collected"] += count
            self.logger.info(f"任务完成: {task.task_id} [{task.platform}] 入库 {count} 条")
            return count
        except Exception as e:
            # 捕获异常，更新任务状态为失败
            task.status = "failed"
            task.error_message = str(e)
            update_task(task.task_id, "failed", 0, str(e))
            self._stats["total_errors"] += 1
            self.logger.error(f"任务失败: {task.task_id} [{task.platform}] {e}")
            return 0
        finally:
            # 无论成功失败，都从并发集合中移除
            self._concurrent_tasks.discard(task.task_id)

    async def run_pending_tasks(self, max_concurrent: int = MAX_CONCURRENT):
        """
        执行所有待执行任务（并发控制）。

        从 crawl_tasks 表中获取状态为 pending 的任务，
        使用信号量控制并发数，避免同时发起过多请求。

        参数:
            max_concurrent: 最大并发数，默认使用配置中的 MAX_CONCURRENT
        """
        # 获取待执行任务列表（最多 20 个）
        tasks = get_pending_tasks(limit=20)
        if not tasks:
            return

        # 使用信号量限制并发数
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run_with_limit(task):
            """带并发限制的任务执行包装器"""
            async with semaphore:
                # 如果当前并发数已达上限，等待其他任务完成
                while len(self._concurrent_tasks) >= max_concurrent:
                    await asyncio.sleep(1)
                self._concurrent_tasks.add(task["task_id"])
                # 随机延时，模拟人类操作间隔，降低被封风险
                await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                # 将字典重建为 CrawlTask 对象并执行
                crawl_task = CrawlTask(**task)
                await self.execute_single_task(crawl_task)

        # 并发执行所有任务
        await asyncio.gather(*[_run_with_limit(t) for t in tasks])

    async def run_scheduled_loop(self, interval_minutes: int = 30):
        """
        定时循环抓取。

        持续运行调度器，每隔指定分钟数执行一轮待执行任务。
        支持通过 stop() 方法从外部停止。

        参数:
            interval_minutes: 每轮抓取的间隔时间（分钟），默认 30 分钟
        """
        self._running = True
        self.logger.info(f"定时调度启动，间隔 {interval_minutes} 分钟")
        while self._running:
            try:
                # 执行所有待执行任务
                await self.run_pending_tasks()
                self.logger.info(f"本轮完成，等待 {interval_minutes} 分钟...")
                # 等待下一轮
                await asyncio.sleep(interval_minutes * 60)
            except asyncio.CancelledError:
                # 收到取消信号，停止调度
                self._running = False
                break
            except Exception as e:
                # 其他异常：记录日志后等待 60 秒重试，避免异常导致调度器退出
                self.logger.error(f"调度异常: {e}")
                await asyncio.sleep(60)

    def stop(self):
        """
        停止调度。

        将运行标志置为 False，定时循环会在下一轮检测到后退出。
        """
        self._running = False

    def get_stats(self) -> dict:
        """
        获取调度器统计信息。

        合并内存中的实时统计和数据库中的历史统计，
        返回完整的调度运行数据。

        返回:
            包含以下键的字典:
                - total_dispatched: 累计下发任务数
                - total_collected:  累计采集条数
                - total_errors:     累计错误数
                - total_tasks:      今日创建任务总数（来自数据库）
                - success_tasks:    成功任务数
                - failed_tasks:     失败任务数
                - pending_tasks:    待执行任务数
                - running_tasks:    正在执行的任务数
                - total_items:      今日入库数据总数
        """
        db_stats = get_task_stats()
        return {**self._stats, **db_stats}
