# -*- coding: utf-8 -*-
"""数据库配置与连接管理"""
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "sentiment.db"


def get_db_path() -> Path:
    """确保数据目录存在并返回数据库路径"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（启用外键约束和行工厂）"""
    conn = sqlite3.connect(str(get_db_path()))
    try:
        conn.execute("PRAGMA journal_mode=WAL")   # 并发读写更友好
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys=ON")        # 启用外键
    conn.row_factory = sqlite3.Row                # 返回字典风格行
    return conn


def init_db():
    """执行建表SQL初始化数据库"""
    sql_path = PROJECT_ROOT / "sql" / "init_tables.sql"
    conn = get_connection()
    try:
        with open(sql_path, "r", encoding="utf-8") as f:
            sql = f.read()
        # 逐条执行，避免 executescript 在特定环境下的兼容性问题
        for statement in sql.split(';'):
            stmt = statement.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        # 补齐可能缺失的字段（ALTER TABLE，已存在则跳过）
        _alter_columns(conn)
    finally:
        conn.close()


def _alter_columns(conn: sqlite3.Connection):
    """补齐后迭代新增的表字段"""
    try:
        conn.execute("ALTER TABLE raw_news ADD COLUMN event_id INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE event_analysis ADD COLUMN lifecycle TEXT DEFAULT NULL")
    except Exception:
        pass
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_news_event_id ON raw_news(event_id)")
    except Exception:
        pass
    conn.commit()
