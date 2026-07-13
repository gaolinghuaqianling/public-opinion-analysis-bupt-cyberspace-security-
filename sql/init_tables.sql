-- ============================================================
-- 网络舆情智能分析系统 - 数据库建表SQL (SQLite)
-- ============================================================

-- 1. 用户表
CREATE TABLE IF NOT EXISTS user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,          -- bcrypt 加密后的密码
    focus_platforms TEXT  NOT NULL DEFAULT '[]',  -- JSON数组，如 ["微博","抖音","知乎"]
    focus_keywords  TEXT  NOT NULL DEFAULT '[]',  -- JSON数组，如 ["人工智能","芯片"]
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 2. 爬虫原始新闻表
CREATE TABLE IF NOT EXISTS raw_news (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    content       TEXT    NOT NULL DEFAULT '',
    source_platform TEXT  NOT NULL,          -- 来源平台: 微博/抖音/知乎/微信公众号等
    published_at  TEXT,                      -- 原文发布时间
    original_url  TEXT    UNIQUE,            -- 原文链接
    crawled_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    status        TEXT    NOT NULL DEFAULT 'pending'  -- pending/analyzed/ignored
);

-- 3. 热点事件主表
CREATE TABLE IF NOT EXISTS hot_event (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    heat_score    REAL    NOT NULL DEFAULT 0.0,       -- 热度分数 (0~100)
    risk_level    TEXT    NOT NULL DEFAULT 'low',      -- low/medium/high/critical
    summary       TEXT    NOT NULL DEFAULT '',         -- 事件概述
    lifecycle     TEXT    NOT NULL DEFAULT 'latent',   -- latent/growth/peak/decline
    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 4. 事件分析详情表
CREATE TABLE IF NOT EXISTS event_analysis (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          INTEGER NOT NULL,
    positive_ratio    REAL    NOT NULL DEFAULT 0.0,    -- 正面情感占比
    negative_ratio    REAL    NOT NULL DEFAULT 0.0,    -- 负面情感占比
    neutral_ratio     REAL    NOT NULL DEFAULT 0.0,    -- 中性情感占比
    high_freq_keywords TEXT  NOT NULL DEFAULT '[]',   -- JSON数组，高频关键词TOP20
    platform_coverage TEXT   NOT NULL DEFAULT '{}',   -- JSON对象，各平台报道占比
    credibility_score  REAL    NOT NULL DEFAULT 0.0,    -- 文本可信度分数 (0~1)，越高越可信
    fake_flags         TEXT    NOT NULL DEFAULT '[]',   -- JSON数组，虚假特征标记列表
    analyzed_at       TEXT   NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (event_id) REFERENCES hot_event(id) ON DELETE CASCADE
);

-- 5. 传播溯源表
CREATE TABLE IF NOT EXISTS spread_info (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         INTEGER NOT NULL,
    origin_platform  TEXT    NOT NULL,           -- 首发平台
    origin_url       TEXT,                       -- 首发链接
    spread_nodes     TEXT    NOT NULL DEFAULT '[]',  -- JSON数组，传播节点列表
    spread_depth     INTEGER NOT NULL DEFAULT 0,     -- 传播深度
    total_reposts    INTEGER NOT NULL DEFAULT 0,     -- 转发总量
    total_reads       INTEGER NOT NULL DEFAULT 0,     -- 阅读总量
    graph_data        TEXT    NOT NULL DEFAULT '{}',   -- JSON对象，ECharts关系图节点/边数据
    traced_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (event_id) REFERENCES hot_event(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_raw_news_platform ON raw_news(source_platform);
CREATE INDEX IF NOT EXISTS idx_raw_news_time    ON raw_news(published_at);
CREATE INDEX IF NOT EXISTS idx_hot_event_heat    ON hot_event(heat_score DESC);
CREATE INDEX IF NOT EXISTS idx_hot_event_risk    ON hot_event(risk_level);
CREATE INDEX IF NOT EXISTS idx_event_analysis_ev ON event_analysis(event_id);
CREATE INDEX IF NOT EXISTS idx_spread_info_ev    ON spread_info(event_id);

-- 6. 传播参与用户表（舆情参与用户画像洞察）
CREATE TABLE IF NOT EXISTS spread_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    user_id TEXT,
    platform TEXT NOT NULL,
    ip_location TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    register_date TEXT DEFAULT '',
    followers_count INTEGER DEFAULT 0,
    following_count INTEGER DEFAULT 0,
    posts_count INTEGER DEFAULT 0,
    avatar_hash TEXT DEFAULT '',
    nickname_hash TEXT DEFAULT '',
    FOREIGN KEY (event_id) REFERENCES hot_event(id)
);

-- 7. 用户历史内容表（用于画像分析）
CREATE TABLE IF NOT EXISTS user_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    content_type TEXT DEFAULT 'post',
    content TEXT NOT NULL,
    keywords TEXT DEFAULT '[]',
    published_at TEXT DEFAULT '',
    likes INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_spread_user_event    ON spread_user(event_id);
CREATE INDEX IF NOT EXISTS idx_spread_user_platform ON spread_user(platform);
CREATE INDEX IF NOT EXISTS idx_user_content_user    ON user_content(user_name);
CREATE INDEX IF NOT EXISTS idx_user_content_platform ON user_content(platform);
