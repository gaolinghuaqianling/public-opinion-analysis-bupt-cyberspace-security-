# -*- coding: utf-8 -*-
"""
爬虫 CLI 入口 — 命令行启动脚本
==========================================================
架构位置: 入口层，用户通过命令行直接调用
职责:
    1. 解析命令行参数（单次/定时模式、平台指定、关键词搜索等）
    2. 初始化日志和数据库
    3. 支持新模式（--platform 指定平台）和旧模式（默认抓取所有平台）
    4. 兼容旧版启动命令的参数（--channels、--delay）

使用示例:
    # 单次抓取所有平台热榜
    python -m crawler.cli --once

    # 定时循环抓取（每15分钟一轮）
    python -m crawler.cli --interval 15

    # 仅抓取微博热榜
    python -m crawler.cli --platform weibo --once

    # 抓取指定平台的关键词
    python -m crawler.cli --platform weibo --task-type keyword --keyword "AI"

    # 兼容旧命令
    python -m crawler.cli --channels 时政 --delay "3,7"
==========================================================
"""

import argparse
import asyncio
import sys

from crawler.config import setup_logging
from crawler.storage import ensure_tables_exist
from crawler.scheduler import CrawlerScheduler
from crawler.adapters import list_supported_platforms


def main():
    """CLI 主入口函数"""
    # ---------- 参数解析 ----------
    parser = argparse.ArgumentParser(description="智舆多平台舆情爬虫")

    # 运行模式参数
    parser.add_argument("--once", action="store_true", help="单次抓取模式（执行后退出）")
    parser.add_argument("--interval", type=int, default=30, help="定时抓取间隔(分钟)，默认30分钟")

    # 平台与任务参数
    parser.add_argument("--platform", type=str, default=None,
                        help="指定平台(people_rss/weibo/douyin/zhihu/xiaohongshu/bilibili)")
    parser.add_argument("--task-type", type=str, default="hotlist",
                        help="任务类型(hotlist/keyword)，默认hotlist")
    parser.add_argument("--keyword", type=str, default=None,
                        help="关键词搜索（与 --task-type keyword 配合使用）")

    # 兼容旧版参数（保留但不影响核心逻辑）
    parser.add_argument("--channels", type=str, default=None,
                        help="人民网频道(兼容旧参数，当前版本忽略)")
    parser.add_argument("--delay", type=str, default=None,
                        help="延时范围(兼容旧参数，当前版本忽略)")

    args = parser.parse_args()

    # ---------- 初始化 ----------
    # 配置日志系统
    setup_logging()
    # 确保数据库表结构存在
    ensure_tables_exist()

    # 创建调度器实例
    scheduler = CrawlerScheduler()

    # ---------- 路由到对应的运行模式 ----------
    if args.platform:
        # 新模式：用户指定了具体平台
        asyncio.run(run_platform_task(scheduler, args))
    else:
        # 兼容旧模式：默认抓取所有已注册平台的热榜
        asyncio.run(run_all_platforms(scheduler, args))


async def run_platform_task(scheduler, args):
    """
    新模式：执行指定平台的抓取任务。

    根据 --platform、--task-type、--keyword 参数，
    创建单个任务并立即执行。

    参数:
        scheduler: CrawlerScheduler 调度器实例
        args:      命令行参数命名空间
    """
    # 下发指定平台的任务
    task_id = await scheduler.dispatch_task(
        args.platform,
        args.task_type,
        args.keyword or args.platform,
        keywords=[args.keyword] if args.keyword else [],
    )
    # 立即执行待执行任务
    await scheduler.run_pending_tasks()


async def run_all_platforms(scheduler, args):
    """
    兼容旧模式：抓取所有已注册平台。

    默认为所有平台创建热榜抓取任务。
    如果指定了 --keyword，还会为每个平台创建关键词搜索任务。
    根据 --once 参数决定是单次执行还是定时循环。

    参数:
        scheduler: CrawlerScheduler 调度器实例
        args:      命令行参数命名空间
    """
    # 获取所有已注册的平台列表
    platforms = list_supported_platforms()

    # 为每个平台创建热榜抓取任务
    for p in platforms:
        await scheduler.dispatch_task(p, "hotlist", p)

    # 如果指定了关键词，为每个平台创建关键词搜索任务
    if args.keyword:
        for p in platforms:
            await scheduler.dispatch_task(p, "keyword", args.keyword, keywords=[args.keyword])

    if args.once:
        # 单次抓取模式：执行完即退出
        await scheduler.run_pending_tasks()
        stats = scheduler.get_stats()
        print(f"单次抓取完成，采集 {stats.get('total_collected', 0)} 条")
    else:
        # 定时循环模式：持续运行
        await scheduler.run_scheduled_loop(args.interval)


# 当作为模块直接执行时进入 CLI
if __name__ == "__main__":
    main()
