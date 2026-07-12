# -*- coding: utf-8 -*-
"""
================================================================================
  网络舆情智能分析系统 — NLP 文本处理模块
================================================================================
基于 jieba + sklearn + TF-IDF + KMeans 的舆情分析引擎。

功能：
  1. 文本分词 + 中文停用词过滤
  2. TF-IDF + KMeans 聚类：相似新闻聚合为热点事件 → 写入 hot_event
  3. 情感分析（基于情感词典 + TF-IDF 关键词加权）→ 写入 event_analysis
  4. TextRank 提取高频关键词
  5. 根据每日新闻量趋势划分舆情生命周期（潜伏期/成长期/高潮期/衰退期）
  6. 所有结果自动写入 SQLite，可对接 FastAPI 项目

用法：
  python nlp_analysis.py                  # 分析全部 pending 新闻
  python nlp_analysis.py --limit 100      # 仅分析最近 100 条
  python nlp_analysis.py --clusters 8     # 指定聚类数为 8
  python nlp_analysis.py --help          # 查看帮助
================================================================================
"""

import sys
import re
import json
import math
import logging
import sqlite3
import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

import jieba
import jieba.posseg as pseg
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# -----------------------------------------------------------------------
# 日志配置
# -----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nlp_analysis")

# -----------------------------------------------------------------------
# 数据库路径（与 FastAPI + crawler 项目共用同一数据库）
# -----------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "sentiment.db"

# -----------------------------------------------------------------------
# 中文停用词表
# -----------------------------------------------------------------------
# 内置常用中文停用词（覆盖虚词、标点、数字、单字等高频无意义词）
# 如需扩展，可在项目下创建 stopwords.txt 文件，每行一个词
BUILTIN_STOPWORDS = set(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 "
    "自己 这 他 她 它 们 那 里 让 把 给 从 而 但 与 被 对 或 又 如 将 因 已 所 以 可 能 "
    "还 这 个 那个 这些 那些 什么 怎么 为什么 哪 哪里 多少 几 怎样 谁 吗 呢 吧 啊 哦 "
    "嗯 哈 呀 哇 呀 哎 唉 噢 嗯 嘛 呗 哟 啦 啧 嘿 呼 哼 咔 么 没 地 得 过 来 下 中 大 小 "
    "出 后 前 之 只 为 时 年 月 日 第 等 及 至 其 更 比 最 然 并 且 虽然 但是 因为 所以 "
    "如果 那么 就是 那么 由于 不过 然后 或者 以及 根据 通过 关于 对于 可以 已经 同时 "
    "不是 一些 这种 那种 每个 任何 没有 已 一些 那些 其他 另外 此外 同时 另外 总体 "
    "目前 近日 近期 今年 去年 明天 昨天 今天 昨天 上午 下午 晚上 早上 中午 晚间 "
    "发布 报道 表示 认为 指出 强调 介绍 说明 称 告诉 讲 提出 引起 引起 有关 "
    "记者 了解 据介绍 据悉 众所周知 另据介绍 据了解 根据"
    "nbsp amp quot lt gt".split()
)


def load_stopwords(custom_path: Optional[str] = None) -> set:
    """
    加载停用词集合。
    优先从自定义文件加载，同时合并内置停用词。
    自定义文件格式：每行一个词，UTF-8 编码，支持 # 开头的注释行。

    参数:
        custom_path: 自定义停用词文件路径，默认为项目根目录下 stopwords.txt

    返回:
        停用词集合
    """
    stopwords = set(BUILTIN_STOPWORDS)

    if custom_path is None:
        custom_path = str(PROJECT_ROOT / "stopwords.txt")

    if Path(custom_path).exists():
        with open(custom_path, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith("#"):
                    stopwords.add(word)
        logger.info("已加载自定义停用词: %s（共 %d 个）", custom_path, len(stopwords))
    else:
        logger.info("使用内置停用词（共 %d 个），未找到自定义文件: %s", len(stopwords), custom_path)

    # 始终过滤纯数字和单字符
    stopwords.update(str(i) for i in range(10))
    return stopwords


# -----------------------------------------------------------------------
# 情感词典
# -----------------------------------------------------------------------
# 正面情感词（用于简单规则情感分析）
POSITIVE_WORDS = set(
    "成功 发展 创新 增长 提升 改善 优秀 突破 进步 升级 领先 优越 稳定 繁荣 "
    "希望 机遇 亮点 好评 赞誉 暖心 感动 精彩 出色 卓越 辉煌 壮丽 美好 幸福 "
    "点赞 推动 促进 落实 优化 规范 高效 合作 交流 支持 帮助 捐赠 关爱 温暖 "
    "丰收 振兴 复苏 回升 畅通 赢得 战胜 克服 保障 肯定 表扬 表彰 推荐 "
    "便民 利民 惠民 安居 乐业 脱贫 奔小康 绿色 低碳 智能 数字化 高质量"
    .split()
)

# 负面情感词
NEGATIVE_WORDS = set(
    "失败 下降 危机 风险 问题 困难 事故 灾难 污染 破坏 腐败 违法 犯罪 欺诈 "
    "事故 隐患 亏损 萎缩 滞后 倒退 紧张 冲突 对立 矛盾 争议 批评 质疑 谴责 "
    "投诉 举报 处罚 警告 担忧 焦虑 恐慌 愤怒 不满 遗憾 遗漏 缺陷 缺陷 "
    "暴跌 跌落 滑坡 崩溃 爆发 泄漏 泛滥 干旱 洪涝 地震 台风 泥石流 "
    "伤亡 死亡 受伤 损失 赔偿 撤职 开除 查处 调查 取缔 整治 打击 "
    "违规 违纪 违法 犯罪 作弊 造假 虚假 欺骗 隐瞒 掩盖 逃避 推诿"
    .split()
)


# -----------------------------------------------------------------------
# 数据库操作
# -----------------------------------------------------------------------
def get_connection() -> sqlite3.Connection:
    """获取 SQLite 数据库连接"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_pending_news(limit: Optional[int] = None) -> List[Dict]:
    """
    从 raw_news 表中获取 status='pending' 的新闻。
    按 published_at 倒序，可选限制条数。

    返回: 字典列表，每条包含 id, title, content, source_platform, published_at, original_url
    """
    conn = get_connection()
    try:
        sql = "SELECT id, title, content, source_platform, published_at, original_url FROM raw_news WHERE status='pending' ORDER BY published_at DESC"
        if limit:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_news_analyzed(news_ids: List[int]):
    """将已分析的新闻状态标记为 analyzed"""
    if not news_ids:
        return
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(news_ids))
        conn.execute(f"UPDATE raw_news SET status='analyzed' WHERE id IN ({placeholders})", news_ids)
        conn.commit()
        logger.info("已标记 %d 条新闻为 analyzed", len(news_ids))
    finally:
        conn.close()


def save_hot_event(title: str, heat_score: float, risk_level: str,
                   summary: str, lifecycle: str) -> int:
    """写入 hot_event 表，返回事件 ID"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO hot_event (title, heat_score, risk_level, summary, lifecycle) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, heat_score, risk_level, summary, lifecycle),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def save_event_analysis(event_id: int, positive_ratio: float, negative_ratio: float,
                        neutral_ratio: float, keywords: List[str],
                        platform_coverage: Dict[str, float],
                        credibility_score: float = 1.0,
                        fake_flags: List[str] = None) -> int:
    """写入 event_analysis 表"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO event_analysis "
            "(event_id, positive_ratio, negative_ratio, neutral_ratio, "
            "high_freq_keywords, platform_coverage, credibility_score, fake_flags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, positive_ratio, negative_ratio, neutral_ratio,
             json.dumps(keywords, ensure_ascii=False),
             json.dumps(platform_coverage, ensure_ascii=False),
             credibility_score,
             json.dumps(fake_flags or [], ensure_ascii=False)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_news_by_date_range(start_date: str, end_date: str) -> List[Dict]:
    """获取指定日期范围内的新闻（用于生命周期分析）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, published_at, source_platform FROM raw_news "
            "WHERE published_at >= ? AND published_at <= ? ORDER BY published_at",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 1. 文本分词与停用词过滤
# -----------------------------------------------------------------------
def tokenize(text: str, stopwords: set, min_word_len: int = 2) -> str:
    """
    对文本进行 jieba 分词，过滤停用词和短词。
    只保留名词、动词、形容词等有意义的词性。

    参数:
        text: 原始文本
        stopwords: 停用词集合
        min_word_len: 最小词长，低于此值的词被过滤

    返回:
        空格分隔的分词结果字符串（供 TF-IDF 向量化使用）
    """
    if not text or not text.strip():
        return ""

    # 允许的词性集合：名词(n)、动词(v)、形容词(a)、成语(i)、缩写(j)
    allowed_pos = {"n", "nr", "ns", "nt", "nz", "v", "vd", "vn", "a", "ad", "an", "i", "j", "eng"}

    words = []
    for word, flag in pseg.cut(text):
        # 过滤条件：非停用词、词长足够、词性允许、非纯数字、非纯英文单字母
        if (word.strip()
                and len(word) >= min_word_len
                and word not in stopwords
                and flag in allowed_pos
                and not word.isdigit()
                and not re.match(r"^[a-zA-Z]$", word)):
            words.append(word)

    return " ".join(words)


def tokenize_for_keywords(text: str, stopwords: set) -> List[str]:
    """
    分词用于关键词提取（不过滤词性，保留更多候选）。
    """
    if not text or not text.strip():
        return []
    return [w for w in jieba.cut(text) if w.strip() and len(w) >= 2 and w not in stopwords and not w.isdigit()]


# -----------------------------------------------------------------------
# 2. TF-IDF 向量化 + KMeans 聚类
# -----------------------------------------------------------------------
def build_tfidf_and_cluster(documents: List[str], n_clusters: int = 8,
                            max_features: int = 1000) -> Tuple:
    """
    使用 TF-IDF + KMeans 对新闻文档进行聚类。

    参数:
        documents: 分词后的文档列表（每条是空格分隔的词语字符串）
        n_clusters: 聚类数
        max_features: TF-IDF 最大特征数

    返回:
        (labels, tfidf_matrix, km_model) 元组
    """
    # TF-IDF 向量化
    vectorizer = TfidfVectorizer(
        max_features=max_features,
        min_df=2,               # 至少在2篇文档中出现
        max_df=0.9,             # 在超过90%文档中出现的词被过滤（过于通用）
        token_pattern=r"(?u)\b\w+\b",
    )
    tfidf_matrix = vectorizer.fit_transform(documents)

    # 如果文档数小于聚类数，自动调整
    actual_k = min(n_clusters, len(documents))
    if actual_k < 2:
        actual_k = 2

    # KMeans 聚类
    km_model = KMeans(
        n_clusters=actual_k,
        init="k-means++",
        max_iter=300,
        n_init=10,
        random_state=42,
    )
    labels = km_model.fit_predict(tfidf_matrix)

    # 轮廓系数评估聚类质量
    if len(documents) > actual_k and tfidf_matrix.shape[0] > actual_k:
        score = silhouette_score(tfidf_matrix, labels, sample_size=min(2000, tfidf_matrix.shape[0]))
        logger.info("聚类质量（轮廓系数）: %.3f（范围 -1~1，越接近1越好）", score)
    else:
        logger.info("样本量不足以计算轮廓系数，跳过")

    logger.info("TF-IDF 特征维度: %d，聚类数: %d", tfidf_matrix.shape[1], actual_k)
    return labels, tfidf_matrix, km_model


def get_cluster_center_keywords(km_model, vectorizer, top_n: int = 5) -> List[List[str]]:
    """
    从每个聚类的质心提取代表性关键词。
    通过 TF-IDF 权重最高的词来描述该聚类的核心主题。

    返回: 列表的列表，外层对应每个聚类，内层为该聚类 TOP-N 关键词
    """
    feature_names = vectorizer.get_feature_names_out()
    centers = km_model.cluster_centers_
    cluster_keywords = []
    for i in range(len(centers)):
        # 获取质心向量中权重最高的 top_n 个词
        top_indices = centers[i].argsort()[::-1][:top_n]
        keywords = [feature_names[j] for j in top_indices]
        cluster_keywords.append(keywords)
    return cluster_keywords


# -----------------------------------------------------------------------
# 3. 情感分析（基于情感词典 + TF-IDF 加权）
# -----------------------------------------------------------------------
def analyze_sentiment(texts: List[str], stopwords: set) -> Dict[str, float]:
    """
    对一组文本进行情感分析。
    采用情感词典 + TF-IDF 关键词加权的方法：
    - 先用 jieba 分词
    - 统计正面/负面词出现频次
    - 对高频关键词给予更高权重（体现关键词对情感判断的重要性）

    返回:
        {"positive": 正面占比, "negative": 负面占比, "neutral": 中性占比}
        三者之和为 1.0
    """
    if not texts:
        return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    total_pos = 0.0
    total_neg = 0.0
    total_neu = 0.0

    # 计算所有文本的词频，用于 TF-IDF 加权
    all_word_counts = Counter()
    doc_word_sets = []
    for text in texts:
        words = tokenize_for_keywords(text, stopwords)
        doc_word_sets.append(set(words))
        all_word_counts.update(words)

    total_docs = len(texts)

    for text in texts:
        words = tokenize_for_keywords(text, stopwords)
        word_freq = Counter(words)

        pos_score = 0.0
        neg_score = 0.0

        for word, freq in word_freq.items():
            # TF-IDF 简化权重：tf * log(N / df)
            tf = freq / max(len(words), 1)
            df = sum(1 for ws in doc_word_sets if word in ws)
            idf = math.log(total_docs / max(df, 1)) + 1  # +1 避免 idf=0
            weight = tf * idf

            if word in POSITIVE_WORDS:
                pos_score += weight
            elif word in NEGATIVE_WORDS:
                neg_score += weight

        total_pos += pos_score
        total_neg += neg_score
        total_neu += 1.0  # 每篇文档基础中性分

    total = total_pos + total_neg + total_neu
    if total == 0:
        return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    return {
        "positive": round(total_pos / total, 4),
        "negative": round(total_neg / total, 4),
        "neutral": round(total_neu / total, 4),
    }


# -----------------------------------------------------------------------
# 4. TextRank 关键词提取
# -----------------------------------------------------------------------
def extract_textrank_keywords(texts: List[str], stopwords: set, top_n: int = 20) -> List[str]:
    """
    基于 TextRank 算法从一组文本中提取高频关键词。
    利用词共现关系构建图，通过迭代计算词语权重排序。

    参数:
        texts: 文本列表
        stopwords: 停用词集合
        top_n: 返回前 N 个关键词

    返回:
        关键词列表（按权重降序）
    """
    if not texts:
        return []

    # 合并所有文本的分词结果
    all_words = []
    for text in texts:
        all_words.extend(tokenize_for_keywords(text, stopwords))

    if not all_words:
        return []

    # 统计词频，作为 TextRank 的初始权重参考
    word_freq = Counter(all_words)

    # 构建共现窗口（窗口大小=4）
    window_size = 4
    cooccurrence = defaultdict(lambda: defaultdict(float))
    for i in range(len(all_words) - window_size + 1):
        window = all_words[i:i + window_size]
        for j in range(len(window)):
            for k in range(j + 1, len(window)):
                if all_words[j] != all_words[k]:
                    cooccurrence[all_words[j]][all_words[k]] += 1.0
                    cooccurrence[all_words[k]][all_words[j]] += 1.0

    # TextRank 迭代计算
    # 只对词频前100的词计算（减少计算量）
    top_words = set(w for w, _ in word_freq.most_common(100))
    d = 0.85  # 阻尼系数
    scores = {w: word_freq[w] for w in top_words}  # 初始值=词频

    for _ in range(30):  # 迭代30次
        new_scores = {}
        for word in top_words:
            rank_sum = 0.0
            for neighbor, weight in cooccurrence[word].items():
                if neighbor in scores:
                    neighbor_sum = sum(cooccurrence[neighbor].values())
                    if neighbor_sum > 0:
                        rank_sum += (weight / neighbor_sum) * scores[neighbor]
            new_scores[word] = (1 - d) + d * rank_sum
        scores = new_scores

    # 按分数降序排列，返回 top_n
    sorted_words = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]


# -----------------------------------------------------------------------
# 5. 舆情生命周期判定
# -----------------------------------------------------------------------
def determine_lifecycle(event_news_count: int, daily_counts: List[int]) -> Tuple[str, float]:
    """
    根据每日新闻发布量趋势判断事件所处的生命周期阶段。

    判定规则：
      - 潜伏期(latent):   当前事件新闻总数 <= 3 篇，或日均发布 < 1
      - 高潮期(peak):     最新一天发布量 >= 总量的 30%（爆发式增长）
      - 衰退期(decline):   最近3天呈递减趋势（最新 < 前天 < 大前天）
      - 成长期(growth):    不满足以上条件，但有持续增长趋势

    参数:
        event_news_count: 当前事件关联的新闻总数
        daily_counts: 按日期的新闻量列表（从最早到最新）

    返回:
        (生命周期阶段, 热度分数)
    """
    # --- 热度分数计算（0~100）---
    # 基于新闻数量、增速、覆盖平台综合评分
    base_score = min(event_news_count * 5, 40)  # 基础分：每篇新闻5分，上限40

    if daily_counts:
        latest = daily_counts[-1]
        avg_count = sum(daily_counts) / len(daily_counts)

        # 增速加成
        if len(daily_counts) >= 2:
            growth = latest - daily_counts[-2]
            speed_bonus = min(max(growth * 3, 0), 30)
        else:
            speed_bonus = 5

        # 密度加成（日均量越高越热）
        density_bonus = min(avg_count * 5, 30)

        heat_score = min(base_score + speed_bonus + density_bonus, 100)
    else:
        heat_score = min(base_score, 20)

    heat_score = round(heat_score, 1)

    # --- 生命周期判定 ---
    if event_news_count <= 3 or (daily_counts and max(daily_counts) < 1):
        return "latent", heat_score

    if not daily_counts or len(daily_counts) < 2:
        return "growth", heat_score

    latest = daily_counts[-1]

    # 高潮期：最新一天发布量占总量 30% 以上
    total = sum(daily_counts)
    if total > 0 and latest / total >= 0.3:
        return "peak", heat_score

    # 衰退期：最近3天呈递减趋势
    if len(daily_counts) >= 3:
        last3 = daily_counts[-3:]
        if last3[0] > last3[1] > last3[2] and last3[2] > 0:
            return "decline", heat_score

    # 成长期：有新闻且不在高潮或衰退阶段
    return "growth", heat_score


# -----------------------------------------------------------------------
# 6. 虚假文本检测（基于文本特征的简单分类器）
# -----------------------------------------------------------------------
# 虚假文本常见特征模式
FAKE_TITLE_PATTERNS = re.compile(
    r"(震惊|吓傻|沸腾了|紧急扩散|央视曝光|惊天大秘密|万人泪目"
    r"|速看|删前速看|刚刚确认|内部消息|不敢相信|看完沉默了"
    r"|疯传|刷屏|炸锅|万万没想到|细思极恐|背后真相)"
)

FAKE_CLICKBAIT_PATTERNS = re.compile(
    r"(!{2,}|！{2,}|？{2,}|\?{2,}|…{3,}|——)"
)

FAKE_EXAGGERATION_WORDS = set(
    "必看 绝版 罕见 史上最 天下第一 震撼全国 瞬间引爆 全网疯转 "
    "绝对 震惊 恐怖 惊人 惊呆了 崩溃 哭了 毁三观 绝了 离谱 "
    "逆天 炸裂 碾压 吊打 秒杀 封神 天花板 降维打击".split()
)

FAKE_SOURCE_SUSPICIOUS = set(
    "匿名 网友爆料 据传 内部人士 知情人士 某专家 某官员 消息人士 "
    "据爆料 据透露 据称 据内部消息".split()
)


def extract_fake_features(text: str, title: str = "", stopwords: set = None) -> Dict[str, float]:
    """
    从单篇文本中提取虚假文本特征向量。
    返回特征字典，每个特征值为 0.0~1.0。

    提取的特征维度：
      1. 标题党程度：标题中感叹号/夸张词密度
      2. 情绪煽动词比例：正文中夸张/煽动词占比
      3. 来源可信度：是否使用匿名/模糊来源
      4. 信息密度：有效信息词（非停用词）占比
      5. 标题-正文重复度：标题内容在正文中出现的比例
      6. 数字精确度：文中精确数字（日期/百分比）的丰富程度
      7. 文本长度：过长或过短都可疑
      8. 标点异常：连续感叹号/问号的使用
    """
    if stopwords is None:
        stopwords = set()

    features = {}

    # 1. 标题党程度
    title_text = title or text[:50]
    fake_title_hits = len(FAKE_TITLE_PATTERNS.findall(title_text))
    fake_clickbait_hits = len(FAKE_CLICKBAIT_PATTERNS.findall(title_text))
    title_len = max(len(title_text), 1)
    features["title_bait"] = min((fake_title_hits * 0.3 + fake_clickbait_hits * 0.2) / title_len * 10, 1.0)

    # 2. 情绪煽动词比例
    words = list(jieba.cut(text))
    non_stop = [w for w in words if w.strip() and w not in stopwords and len(w) >= 2]
    total_words = max(len(non_stop), 1)
    emotion_count = sum(1 for w in non_stop if w in FAKE_EXAGGERATION_WORDS)
    features["emotion_stir"] = min(emotion_count / total_words * 5, 1.0)

    # 3. 来源可信度（匿名来源越多越可疑）
    source_hits = sum(1 for pat in FAKE_SOURCE_SUSPICIOUS if pat in text)
    features["source_suspicious"] = min(source_hits * 0.25, 1.0)

    # 4. 信息密度（有效词占总字符数的比例）
    content_len = max(len(text), 1)
    info_density = len("".join(non_stop)) / content_len
    # 信息密度过低（<0.3）或过高（>0.7）都可疑
    if info_density < 0.2:
        features["info_density"] = 0.6
    elif info_density > 0.7:
        features["info_density"] = 0.3
    else:
        features["info_density"] = 1.0 - abs(info_density - 0.45) * 2
    features["info_density"] = max(0, min(1, features["info_density"]))

    # 5. 标题-正文重复度（标题在正文中完整出现说明正文引用标题）
    title_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", title_text)
    content_clean = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text)
    if title_clean and content_clean:
        overlap = sum(1 for c in title_clean if c in content_clean) / max(len(title_clean), 1)
        features["title_content_overlap"] = overlap
    else:
        features["title_content_overlap"] = 0.5

    # 6. 数字精确度（包含具体日期、百分比、数据量的文本更可信）
    date_pattern = re.findall(r"\d{4}年|\d{1,2}月\d{1,2}日|\d{1,2}:\d{2}", text)
    percent_pattern = re.findall(r"\d+(\.\d+)?%", text)
    data_pattern = re.findall(r"\d+(\.\d+)?(万|亿|元|人|件|吨|公里)", text)
    total_data_points = len(date_pattern) + len(percent_pattern) + len(data_pattern)
    features["data_richness"] = min(total_data_points / 5.0, 1.0)

    # 7. 文本长度（过短缺乏信息量，过长可能冗余）
    char_count = len(text)
    if char_count < 50:
        features["text_length"] = 0.3
    elif char_count < 200:
        features["text_length"] = 0.6
    elif char_count < 2000:
        features["text_length"] = 1.0
    else:
        features["text_length"] = 0.85

    # 8. 标点异常度
    punctuation_count = len(re.findall(r"[!！?？]{2,}", text))
    features["punct_abnormal"] = min(punctuation_count * 0.15, 1.0)

    return features


def detect_fake_text(texts: List[str], titles: List[str] = None,
                     stopwords: set = None) -> Dict[str, float]:
    """
    对一组文本进行虚假/可信度检测。
    基于文本特征加权评分，输出可信度分数和虚假特征标记。

    参数:
        texts: 文本列表（正文）
        titles: 对应标题列表（可选）
        stopwords: 停用词集合

    返回:
        {
            "credibility_score": 0.85,   # 可信度分数 (0~1)，越高越可信
            "fake_flags": ["标题党", "匿名来源"],  # 检测到的虚假特征标记
        }
    """
    if not texts:
        return {"credibility_score": 1.0, "fake_flags": []}

    if stopwords is None:
        stopwords = set()

    titles = titles or [""] * len(texts)

    # 特征权重（越高表示该特征对虚假检测的贡献越大）
    feature_weights = {
        "title_bait": 0.20,          # 标题党：高权重
        "emotion_stir": 0.15,        # 情绪煽动
        "source_suspicious": 0.18,   # 匿名来源
        "info_density": 0.10,         # 信息密度异常
        "title_content_overlap": 0.05,# 标题正文重复度（影响较小）
        "data_richness": 0.12,       # 数据丰富度（正面特征，反向计算）
        "text_length": 0.08,         # 文本长度
        "punct_abnormal": 0.12,       # 标点异常
    }

    # 收集所有文本的特征
    all_features = []
    for text, title in zip(texts, titles):
        feats = extract_fake_features(text, title, stopwords)
        all_features.append(feats)

    # 对每个维度取平均值
    avg_features = {}
    for key in all_features[0].keys():
        avg_features[key] = sum(f[key] for f in all_features) / len(all_features)

    # 计算虚假嫌疑分（0~1，越高越可能虚假）
    fake_suspicion = 0.0
    for key, weight in feature_weights.items():
        if key == "data_richness":
            # data_richness 是正面特征（高=可信），需要反向
            fake_suspicion += weight * (1 - avg_features[key])
        else:
            fake_suspicion += weight * avg_features[key]

    fake_suspicion = max(0, min(1, fake_suspicion))

    # 转换为可信度分数
    credibility = round(1.0 - fake_suspicion, 4)

    # 收集虚假特征标记
    fake_flags = []
    if avg_features["title_bait"] > 0.3:
        fake_flags.append("标题党嫌疑")
    if avg_features["emotion_stir"] > 0.15:
        fake_flags.append("情绪煽动词过多")
    if avg_features["source_suspicious"] > 0.3:
        fake_flags.append("匿名/模糊来源")
    if avg_features["data_richness"] < 0.2:
        fake_flags.append("缺乏具体数据支撑")
    if avg_features["punct_abnormal"] > 0.2:
        fake_flags.append("标点符号异常")
    if avg_features["info_density"] < 0.3:
        fake_flags.append("信息密度过低")
    if avg_features["text_length"] < 0.4:
        fake_flags.append("文本过短")

    return {"credibility_score": credibility, "fake_flags": fake_flags}


def compute_risk_level(sentiment: Dict[str, float], heat_score: float) -> str:
    """
    根据情感比例和热度综合评估风险等级。

    规则：
      - critical: 热度>80 且 负面>40%
      - high:     热度>60 且 负面>30%，或 负面>40%
      - medium:   热度>40 且 负面>20%，或 负面>25%
      - low:      其他情况
    """
    neg = sentiment.get("negative", 0)
    heat = heat_score

    if neg > 0.4 and heat > 80:
        return "critical"
    if neg > 0.3 and heat > 60:
        return "high"
    if neg > 0.4:
        return "high"
    if neg > 0.2 and heat > 40:
        return "medium"
    if neg > 0.25:
        return "medium"
    return "low"


# -----------------------------------------------------------------------
# 主流程：端到端分析
# -----------------------------------------------------------------------
def run_analysis(limit: Optional[int] = None, n_clusters: int = 10):
    """
    执行完整的 NLP 分析流程：
      1. 从数据库加载 pending 新闻
      2. 分词 + 停用词过滤
      3. TF-IDF + KMeans 聚类
      4. 对每个聚类生成热点事件
      5. 情感分析 + 关键词提取 + 生命周期判定
      6. 写入数据库
    """
    logger.info("=" * 60)
    logger.info("NLP 舆情分析引擎启动")
    logger.info("=" * 60)

    # ---------- Step 1: 加载 pending 新闻 ----------
    news_list = fetch_pending_news(limit)
    if not news_list:
        logger.info("没有 pending 状态的新闻需要分析，退出。")
        return

    logger.info("加载到 %d 条 pending 新闻", len(news_list))

    # ---------- Step 2: 加载停用词 ----------
    stopwords = load_stopwords()

    # ---------- Step 3: 文本分词 ----------
    logger.info("正在分词...")
    # 合并标题和正文作为分析文本（标题权重更高）
    documents_raw = []
    tokenized_docs = []
    for news in news_list:
        raw_text = f"{news['title']} {news['content']}"
        documents_raw.append(raw_text)
        tokenized = tokenize(raw_text, stopwords, min_word_len=2)
        tokenized_docs.append(tokenized)

    # 过滤空文档
    valid_indices = [i for i, d in enumerate(tokenized_docs) if d.strip()]
    if len(valid_indices) < n_clusters:
        n_clusters = max(2, len(valid_indices) // 3)
        logger.info("有效文档较少，自动调整聚类数为 %d", n_clusters)

    if len(valid_indices) < 2:
        logger.warning("有效分词文档不足 2 篇，无法聚类，退出。")
        return

    filtered_docs = [tokenized_docs[i] for i in valid_indices]
    filtered_news = [news_list[i] for i in valid_indices]

    logger.info("有效文档: %d 篇", len(filtered_docs))

    # ---------- Step 4: TF-IDF + KMeans 聚类 ----------
    logger.info("正在进行 TF-IDF + KMeans 聚类（k=%d）...", n_clusters)
    labels, tfidf_matrix, km_model = build_tfidf_and_cluster(
        filtered_docs, n_clusters=n_clusters, max_features=1500
    )

    # 获取每个聚类的代表关键词
    vectorizer = TfidfVectorizer(
        max_features=1500, min_df=2, max_df=0.9, token_pattern=r"(?u)\b\w+\b"
    )
    tfidf_matrix2 = vectorizer.fit_transform(filtered_docs)
    # 重新训练 vectorizer 以获取 feature_names
    km_model2 = KMeans(n_clusters=min(n_clusters, len(filtered_docs)), init="k-means++",
                       max_iter=300, n_init=10, random_state=42)
    labels = km_model2.fit_predict(tfidf_matrix2)
    cluster_keywords_list = get_cluster_center_keywords(km_model2, vectorizer, top_n=5)

    # ---------- Step 5: 按聚类分组处理 ----------
    logger.info("正在对 %d 个聚类进行事件生成、情感分析和关键词提取...", n_clusters)

    # 按聚类标签分组
    clusters = defaultdict(list)
    for idx, label in enumerate(labels):
        clusters[label].append(filtered_news[idx])

    all_analyzed_news_ids = []
    created_events = 0

    for cluster_id, cluster_news in clusters.items():
        if len(cluster_news) < 1:
            continue

        logger.info("-" * 40)
        logger.info("聚类 #%d: %d 条新闻", cluster_id, len(cluster_news))

        # --- 事件标题：取该聚类中最长的标题作为事件标题（通常信息量最大）---
        titles = [n["title"] for n in cluster_news]
        event_title = max(titles, key=len)
        if len(event_title) > 80:
            event_title = event_title[:80] + "..."

        # --- 关键词提取（TextRank）---
        cluster_texts = [f"{n['title']} {n['content']}" for n in cluster_news]
        keywords = extract_textrank_keywords(cluster_texts, stopwords, top_n=20)
        logger.info("  关键词: %s", ", ".join(keywords[:10]))

        # --- 情感分析 ---
        sentiment = analyze_sentiment(cluster_texts, stopwords)
        logger.info("  情感: 正面=%.1f%% 负面=%.1f%% 中性=%.1f%%",
                     sentiment["positive"] * 100, sentiment["negative"] * 100, sentiment["neutral"] * 100)

        # --- 生命周期 + 热度 ---
        lifecycle, heat_score = determine_lifecycle(len(cluster_news), [len(cluster_news)])
        logger.info("  生命周期: %s, 热度: %.1f", lifecycle, heat_score)

        # --- 风险等级 ---
        risk_level = compute_risk_level(sentiment, heat_score)
        logger.info("  风险等级: %s", risk_level)

        # --- 虚假文本检测 ---
        fake_result = detect_fake_text(
            texts=cluster_texts,
            titles=[n["title"] for n in cluster_news],
            stopwords=stopwords,
        )
        credibility = fake_result["credibility_score"]
        fake_flags = fake_result["fake_flags"]
        logger.info("  可信度: %.2f (%s)", credibility, "可信" if credibility > 0.7 else "存疑")
        if fake_flags:
            logger.info("  虚假标记: %s", ", ".join(fake_flags))

        # --- 事件概述 ---
        summary_parts = []
        summary_parts.append(f"共{len(cluster_news)}篇相关报道")
        summary_parts.append(f"关键词：{'、'.join(keywords[:6])}")
        summary_parts.append(f"情感倾向：正面{sentiment['positive']*100:.0f}%/负面{sentiment['negative']*100:.0f}%/中性{sentiment['neutral']*100:.0f}%")
        summary = "；".join(summary_parts)

        # --- 平台覆盖统计 ---
        platform_counts = Counter(n["source_platform"] for n in cluster_news)
        total = sum(platform_counts.values())
        platform_coverage = {k: round(v / total * 100, 1) for k, v in platform_counts.items()}

        # --- 按日发布量统计（用于生命周期）---
        date_counts = defaultdict(int)
        for n in cluster_news:
            pub_date = n.get("published_at", "")[:10]  # YYYY-MM-DD
            if pub_date:
                date_counts[pub_date] += 1
        daily_counts = [date_counts[d] for d in sorted(date_counts.keys())]

        # 更精确的生命周期判定
        if len(daily_counts) > 1:
            lifecycle, heat_score = determine_lifecycle(len(cluster_news), daily_counts)
            logger.info("  修正生命周期: %s (基于 %d 天数据)", lifecycle, len(daily_counts))

        # --- 写入 hot_event ---
        event_id = save_hot_event(
            title=event_title,
            heat_score=heat_score,
            risk_level=risk_level,
            summary=summary,
            lifecycle=lifecycle,
        )
        logger.info("  -> hot_event #%d 已写入", event_id)
        created_events += 1

        # --- 写入 event_analysis ---
        save_event_analysis(
            event_id=event_id,
            positive_ratio=sentiment["positive"],
            negative_ratio=sentiment["negative"],
            neutral_ratio=sentiment["neutral"],
            keywords=keywords,
            platform_coverage=platform_coverage,
            credibility_score=credibility,
            fake_flags=fake_flags,
        )
        logger.info("  -> event_analysis 已写入 (可信度=%.2f)", credibility)

        # 记录已分析的新闻 ID
        for n in cluster_news:
            all_analyzed_news_ids.append(n["id"])

    # ---------- Step 6: 标记新闻为已分析 ----------
    mark_news_analyzed(all_analyzed_news_ids)

    # ---------- 汇总报告 ----------
    logger.info("=" * 60)
    logger.info("分析完成汇总:")
    logger.info("  处理新闻: %d 条", len(filtered_news))
    logger.info("  生成热点事件: %d 个", created_events)
    logger.info("  聚类数: %d", len(clusters))
    logger.info("=" * 60)


# -----------------------------------------------------------------------
# CLI 入口
# -----------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="舆情 NLP 分析引擎（jieba + sklearn + TF-IDF + KMeans）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python nlp_analysis.py                    # 分析全部 pending 新闻
  python nlp_analysis.py --limit 100        # 仅分析最近 100 条
  python nlp_analysis.py --clusters 12      # 指定聚类数为 12
  python nlp_analysis.py --stopwords data/custom_stopwords.txt
        """,
    )

    parser.add_argument("--limit", type=int, default=None, help="限制分析的新闻条数")
    parser.add_argument("--clusters", type=int, default=10, help="KMeans 聚类数（默认10）")
    parser.add_argument("--stopwords", type=str, default=None, help="自定义停用词文件路径")

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_analysis(limit=args.limit, n_clusters=args.clusters)
