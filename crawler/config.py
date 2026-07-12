# -*- coding: utf-8 -*-
"""
全局配置模块 — 爬虫基础设施
==========================================================
架构位置: 基础设施层，被所有子模块引用
职责:
    1. 定义项目路径、数据库、日志等核心路径
    2. 管理反爬参数（请求延时、并发数、UA池）
    3. 配置日志系统（按天滚动、文件+控制台双输出）
    4. 支持环境变量覆盖任意配置项
==========================================================
"""

import os
import sys
import logging
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from typing import List

# -----------------------------------------------------------------------
# 路径配置
# -----------------------------------------------------------------------
# 爬虫包根目录（crawler/）
CRAWLER_DIR: Path = Path(__file__).resolve().parent

# 项目根目录（sentiment_analysis/）
PROJECT_ROOT: Path = CRAWLER_DIR.parent

# 数据库路径 — 与 FastAPI 共用同一个 SQLite 文件
DB_PATH: Path = PROJECT_ROOT / "data" / "sentiment.db"

# 日志输出目录
LOG_DIR: Path = PROJECT_ROOT / "data" / "logs"

# -----------------------------------------------------------------------
# 反爬配置 — 请求延时与并发
# -----------------------------------------------------------------------
# 每次请求前的最小/最大等待秒数，防止高频请求被封锁
MIN_DELAY: float = float(os.environ.get("CRAWLER_MIN_DELAY", "3"))
MAX_DELAY: float = float(os.environ.get("CRAWLER_MAX_DELAY", "7"))

# 单IP最大并发请求数，避免同时发出过多请求
MAX_CONCURRENT: int = int(os.environ.get("CRAWLER_MAX_CONCURRENT", "2"))

# -----------------------------------------------------------------------
# robots.txt 校验开关
# -----------------------------------------------------------------------
# 设为 True 时，适配器在抓取前会先检查目标站点的 robots.txt
ROBOTS_CHECK_ENABLED: bool = os.environ.get(
    "CRAWLER_ROBOTS_CHECK", "True"
).lower() in ("true", "1", "yes")

# -----------------------------------------------------------------------
# User-Agent 随机池
# -----------------------------------------------------------------------
# 包含 10+ 个真实 Chrome User-Agent，每次请求随机选取
_USER_AGENT_POOL: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
]

# 对外暴露为不可变元组，防止意外修改
USER_AGENT_POOL: tuple = tuple(_USER_AGENT_POOL)

# -----------------------------------------------------------------------
# 存储后端配置
# -----------------------------------------------------------------------
# 当前支持: "sqlite"（默认）
# 预留扩展: "mysql" / "elasticsearch"
STORAGE_BACKEND: str = os.environ.get("CRAWLER_STORAGE_BACKEND", "sqlite")

# -----------------------------------------------------------------------
# 日志配置
# -----------------------------------------------------------------------
def setup_logging(
    level: int = logging.INFO,
    log_dir: Path = None,
) -> logging.Logger:
    """
    初始化日志系统。

    特性:
        - 同时输出到控制台（stderr）和文件
        - 文件日志按天滚动（midnight），保留最近 30 天
        - 格式统一: 时间 [级别] 消息

    参数:
        level:   日志级别，默认 INFO
        log_dir: 日志目录，默认使用全局 LOG_DIR

    返回:
        配置好的 logger 实例
    """
    if log_dir is None:
        log_dir = LOG_DIR

    # 确保日志目录存在
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 获取/创建爬虫专用 logger
    logger = logging.getLogger("crawler")
    logger.setLevel(level)

    # 避免重复添加 handler（模块被多次 import 时）
    if logger.handlers:
        return logger

    # ---------- 控制台 Handler ----------
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # ---------- 按天滚动文件 Handler ----------
    log_file = log_dir / "crawler.log"
    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",          # 每天午夜滚动
        interval=1,                # 每天一个文件
        backupCount=30,            # 保留最近 30 天
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    # 文件名后缀格式: crawler.log.2026-07-09
    file_handler.suffix = "%Y-%m-%d"
    logger.addHandler(file_handler)

    return logger


# 模块加载时自动初始化默认 logger
logger: logging.Logger = setup_logging()
