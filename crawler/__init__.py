# -*- coding: utf-8 -*-
"""
智舆 — 多平台舆情爬虫模块
分层架构：调度层 → 适配器层 → 引擎层 → 清洗层 → 存储层

模块结构:
    config.py    — 全局配置（路径、延时、UA池、日志等）
    models.py    — 标准化数据模型（CrawledItem / CrawlTask）
    cleaners.py  — 数据清洗层（去HTML、去噪、时间标准化）
    storage.py   — 存储层（SQLite CRUD、去重、任务管理）
    scheduler.py — 任务调度层（任务下发、并发控制、定时循环）
    adapters/    — 适配器层（各平台独立适配器）
    cli.py       — CLI 入口（命令行启动脚本）
"""

# 对外导出核心类和函数，方便外部模块直接引用
from crawler.scheduler import CrawlerScheduler
from crawler.adapters import get_adapter, ADAPTER_REGISTRY
