# -*- coding: utf-8 -*-
"""
存储层 — 数据持久化与任务管理
==========================================================
架构位置: 存储层，被引擎层调用完成数据入库和任务管理
职责:
    1. 管理 SQLite 连接（WAL模式、Row工厂）
    2. 确保 raw_news / crawl_tasks / crawl_logs 表存在
    3. 提供 CrawledItem 的单条/批量入库（三重去重：URL+标题+发布时间）
    4. 提供 CrawlTask 的 CRUD 操作
    5. 提供采集统计查询接口
    6. 预留 MySQL / Elasticsearch 扩展接口
==========================================================
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from .config import DB_PATH, logger
from .models import CrawledItem, CrawlTask


# -----------------------------------------------------------------------
# 数据库连接管理
# -----------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    """
    获取 SQLite 数据库连接。

    配置:
        - WAL 日志模式，支持并发读写
        - 启用外键约束
        - 使用 Row 工厂，查询结果可用字典风格访问

    返回:
        sqlite3.Connection 实例，调用方负责关闭
    """
    # 确保数据目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# -----------------------------------------------------------------------
# 表结构初始化
# -----------------------------------------------------------------------
def ensure_tables_exist() -> None:
    """
    确保爬虫所需的全部表已创建。

    创建/检查的表:
        - raw_news:      原始新闻数据（与 FastAPI 共用）
        - crawl_tasks:   爬虫任务队列表
        - crawl_logs:    爬虫运行日志表
    """
    conn = get_connection()
    try:
        # ---------- raw_news 表（兼容现有 FastAPI 结构）----------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_news (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT    NOT NULL,
                content         TEXT    NOT NULL DEFAULT '',
                source_platform TEXT    NOT NULL,
                published_at    TEXT,
                original_url    TEXT    UNIQUE,
                crawled_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                status          TEXT    NOT NULL DEFAULT 'pending'
            )
        """)

        # ---------- crawl_tasks 表 — 任务队列表 ----------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_tasks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         TEXT    NOT NULL UNIQUE,
                platform        TEXT    NOT NULL,
                task_type       TEXT    NOT NULL,
                target          TEXT    NOT NULL,
                keywords        TEXT    NOT NULL DEFAULT '[]',
                priority        INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                status          TEXT    NOT NULL DEFAULT 'pending',
                result_count    INTEGER NOT NULL DEFAULT 0,
                error_message   TEXT    NOT NULL DEFAULT '',
                updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)

        # ---------- crawl_logs 表 — 运行日志 ----------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id         TEXT,
                platform        TEXT,
                level           TEXT    NOT NULL DEFAULT 'INFO',
                message         TEXT    NOT NULL,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)

        # ---------- 索引 ----------
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_news_url "
            "ON raw_news(original_url)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_news_platform "
            "ON raw_news(source_platform)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_raw_news_time "
            "ON raw_news(published_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status "
            "ON crawl_tasks(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawl_tasks_priority "
            "ON crawl_tasks(priority DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawl_logs_task "
            "ON crawl_logs(task_id)"
        )

        # 确保 raw_news 表有 event_id 字段
        try:
            conn.execute("ALTER TABLE raw_news ADD COLUMN event_id INTEGER DEFAULT NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_news_event_id ON raw_news(event_id)")
        except Exception:
            pass  # 字段已存在则跳过
        # 确保 event_analysis 表有 lifecycle 字段
        try:
            conn.execute("ALTER TABLE event_analysis ADD COLUMN lifecycle TEXT DEFAULT NULL")
        except Exception:
            pass  # 字段已存在则跳过
        conn.commit()
        logger.debug("数据库表检查完成: raw_news / crawl_tasks / crawl_logs")
    except Exception as e:
        logger.error("数据库表初始化失败: %s", e)
        raise
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 去重查询
# -----------------------------------------------------------------------
def is_url_exists(url: str) -> bool:
    """
    检查 URL 是否已存在于 raw_news 表中。

    参数:
        url: 原文链接

    返回:
        True 表示已存在（应跳过），False 表示不存在（可入库）

    # MySQL 扩展: SELECT 1 FROM raw_news WHERE original_url = %s LIMIT 1
    # ES 扩展:   client.exists(index="raw_news", id=hash(url))
    """
    if not url:
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM raw_news WHERE original_url = ?", (url,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_title_exists(title: str) -> bool:
    """
    通过标题精确匹配辅助去重。

    有些新闻 URL 可能略有差异（如末尾参数不同），但标题完全相同，
    需要通过标题二次校验避免重复入库。

    参数:
        title: 新闻标题（已清洗后的纯文本）

    返回:
        True 表示标题已存在

    # MySQL 扩展: SELECT 1 FROM raw_news WHERE title = %s LIMIT 1
    """
    if not title or not title.strip():
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM raw_news WHERE title = ?", (title.strip(),)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def _is_duplicate(item: CrawledItem) -> bool:
    """
    内部方法：执行三重去重检查（URL + 标题 + 发布时间）。

    参数:
        item: 待检查的采集数据

    返回:
        True 表示该条数据已存在，应跳过
    """
    # 第一重：URL 去重
    if item.original_url and is_url_exists(item.original_url):
        return True

    # 第二重：标题去重
    if item.title and is_title_exists(item.title):
        return True

    # 第三重：同标题+同发布时间联合去重（防止标题相同但内容不同的极端情况）
    if item.title and item.published_at:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM raw_news WHERE title = ? AND published_at = ?",
                (item.title, item.published_at),
            ).fetchone()
            if row is not None:
                return True
        finally:
            conn.close()

    return False


# -----------------------------------------------------------------------
# 数据入库
# -----------------------------------------------------------------------
def save_crawled_item(item: CrawledItem) -> bool:
    """
    入库单条采集数据。

    流程:
        1. 执行三重去重检查
        2. 通过 CrawledItem.to_storage_row() 转为表兼容格式
        3. INSERT OR IGNORE 写入 raw_news 表

    参数:
        item: 标准化采集数据

    返回:
        True 表示成功写入，False 表示已重复或写入失败

    # MySQL 扩展: INSERT IGNORE INTO raw_news (...) VALUES (...)
    # ES 扩展:   client.index(index="raw_news", id=doc_id, body=doc)
    """
    # 数据校验：标题不能为空
    if not item.title or not item.title.strip():
        logger.debug("跳过空标题数据")
        return False

    # 三重去重
    if _is_duplicate(item):
        logger.debug("重复数据跳过: %s", item.title[:50])
        return False

    row = item.to_storage_row()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO raw_news "
            "(title, content, source_platform, published_at, original_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                row["title"],
                row["content"],
                row["source_platform"],
                row["published_at"],
                row["original_url"],
            ),
        )
        conn.commit()
        # 通过 total_changes 判断是否真正插入了新行
        inserted = conn.total_changes > 0
        if inserted:
            logger.info("[入库] %s", item.title[:60])
        return inserted
    except Exception as e:
        logger.warning("入库异常: %s — %s", e, item.title[:50])
        return False
    finally:
        conn.close()


def save_crawled_items(items: List[CrawledItem]) -> int:
    """
    批量入库采集数据。

    使用单次连接 + 事务，提升批量写入性能。
    每条数据依然执行三重去重检查。

    参数:
        items: CrawledItem 列表

    返回:
        成功入库的数量

    # MySQL 扩展: executemany + INSERT IGNORE
    # ES 扩展:   helpers.bulk(client, actions)
    """
    if not items:
        return 0

    conn = get_connection()
    success_count = 0
    try:
        for item in items:
            # 数据校验
            if not item.title or not item.title.strip():
                continue

            # 三重去重
            if _is_duplicate(item):
                continue

            row = item.to_storage_row()
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO raw_news "
                    "(title, content, source_platform, published_at, original_url) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        row["title"],
                        row["content"],
                        row["source_platform"],
                        row["published_at"],
                        row["original_url"],
                    ),
                )
                success_count += 1
            except Exception as e:
                logger.warning("批量入库异常: %s — %s", e, item.title[:50])

        conn.commit()
        logger.info("批量入库完成: 总计 %d 条, 成功 %d 条", len(items), success_count)
    except Exception as e:
        logger.error("批量入库事务失败: %s", e)
        conn.rollback()
    finally:
        conn.close()

    return success_count


# -----------------------------------------------------------------------
# 任务管理
# -----------------------------------------------------------------------
def create_task(task: CrawlTask) -> str:
    """
    创建一条爬虫任务记录。

    参数:
        task: CrawlTask 实例

    返回:
        任务 ID (task_id)

    # MySQL 扩展: INSERT INTO crawl_tasks (...) VALUES (...)
    # ES 扩展:   client.index(index="crawl_tasks", id=task_id, body=doc)
    """
    import json

    # 自动填充创建时间和默认 task_id
    if not task.task_id:
        import uuid
        task.task_id = str(uuid.uuid4())
    if not task.created_at:
        task.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO crawl_tasks "
            "(task_id, platform, task_type, target, keywords, priority, "
            " created_at, status, result_count, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.task_id,
                task.platform,
                task.task_type,
                task.target,
                json.dumps(task.keywords, ensure_ascii=False),
                task.priority,
                task.created_at,
                task.status,
                task.result_count,
                task.error_message,
            ),
        )
        conn.commit()
        logger.info(
            "任务已创建: [%s] %s - %s",
            task.task_id[:8], task.platform, task.target[:30],
        )
    except Exception as e:
        logger.error("创建任务失败: %s", e)
    finally:
        conn.close()

    return task.task_id


def update_task(
    task_id: str,
    status: str = None,
    result_count: int = None,
    error_message: str = None,
) -> bool:
    """
    更新任务状态。

    仅更新传入的非 None 字段，其余保持不变。

    参数:
        task_id:       任务 ID
        status:        新状态 (pending/running/success/failed)
        result_count:  采集结果数
        error_message: 错误信息

    返回:
        True 表示更新成功

    # MySQL 扩展: UPDATE crawl_tasks SET ... WHERE task_id = %s
    """
    if not task_id:
        return False

    # 动态构建 SET 子句
    set_parts = []
    params = []

    if status is not None:
        set_parts.append("status = ?")
        params.append(status)
    if result_count is not None:
        set_parts.append("result_count = ?")
        params.append(result_count)
    if error_message is not None:
        set_parts.append("error_message = ?")
        params.append(error_message)

    if not set_parts:
        return False  # 没有需要更新的字段

    # 自动更新 updated_at 时间戳
    set_parts.append("updated_at = datetime('now','localtime')")

    params.append(task_id)
    sql = f"UPDATE crawl_tasks SET {', '.join(set_parts)} WHERE task_id = ?"

    conn = get_connection()
    try:
        cursor = conn.execute(sql, params)
        conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            logger.debug("任务更新: [%s] %s", task_id[:8], status or "")
        return updated
    except Exception as e:
        logger.error("更新任务失败: %s — %s", task_id, e)
        return False
    finally:
        conn.close()


def get_pending_tasks(limit: int = 10) -> List[Dict]:
    """
    获取待执行的爬虫任务列表。

    按 priority DESC（优先级高的先执行）排序，
    限制返回数量避免一次性消费过多任务。

    参数:
        limit: 最多返回的任务数

    返回:
        任务字典列表，每个字典包含 crawl_tasks 表的全部列

    # MySQL 扩展: SELECT * FROM crawl_tasks WHERE status='pending' ORDER BY priority DESC LIMIT %s
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM crawl_tasks "
            "WHERE status = 'pending' "
            "ORDER BY priority DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 统计查询
# -----------------------------------------------------------------------
def get_task_stats() -> Dict:
    """
    获取今日采集统计概览。

    返回:
        包含以下键的字典:
            - total_tasks:    今日创建任务总数
            - success_tasks:  成功任务数
            - failed_tasks:   失败任务数
            - pending_tasks:  待执行任务数
            - running_tasks:  正在执行的任务数
            - total_items:    今日入库数据总数

    # MySQL 扩展: 使用 DATE(created_at) = CURDATE() 过滤
    """
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        stats = {}

        # 今日任务统计
        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total_tasks, "
            "  SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_tasks, "
            "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_tasks, "
            "  SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_tasks, "
            "  SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_tasks "
            "FROM crawl_tasks "
            "WHERE created_at LIKE ? || '%'",
            (today,),
        ).fetchone()

        if row:
            stats = dict(row)

        # 今日入库数据总数
        item_row = conn.execute(
            "SELECT COUNT(*) AS total_items FROM raw_news "
            "WHERE crawled_at LIKE ? || '%'",
            (today,),
        ).fetchone()
        stats["total_items"] = item_row["total_items"] if item_row else 0

        return stats
    finally:
        conn.close()
