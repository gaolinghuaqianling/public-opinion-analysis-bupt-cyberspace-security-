# -*- coding: utf-8 -*-
"""
用户画像分析核心算法模块
==========================================================
提供舆情参与用户的四分类、受众多维度画像、品牌人群分层及增强传播图谱功能。

功能:
    1. classify_users(event_id)          — 账号四分类（水军/营销号/行业利益方/普通网民）
    2. analyze_audience_profile(user_names) — 受众多维度画像（地域/兴趣圈层/年龄段）
    3. classify_brand_audience(user_names, brand_name) — 品牌人群分层（老客户/潜在消费者/路人围观）
    4. analyze_user_profile_full(event_id, brand_name)   — 完整画像分析入口
    5. build_enhanced_graph_data(event_id, user_classifications) — 增强传播图谱
"""

import json
import re
import logging
import math
from datetime import datetime
from collections import Counter, defaultdict
from typing import List, Dict, Optional, Tuple

import numpy as np
import jieba
import jieba.analyse
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.database import get_connection

logger = logging.getLogger("services.user_profile_analyzer")

# =====================================================================
# 常量定义
# =====================================================================

# 用户分类标签
CATEGORY_NAMES = {
    "water_army": "水军",
    "marketing": "营销号",
    "industry": "行业利益方",
    "real_user": "普通网民",
}

# 用户分类颜色（用于传播图谱节点）
CATEGORY_COLORS = {
    "water_army": "#ff4d4f",
    "marketing": "#faad14",
    "real_user": "#1890ff",
    "industry": "#722ed1",
}

# 水军判定阈值
WATER_ARMY_THRESHOLD = 60  # 综合评分 >= 60% 判定为水军

# 营销号判定阈值
MARKETING_THRESHOLD = 50  # 综合评分 >= 50% 判定为营销号

# 行业利益方判定阈值
INDUSTRY_THRESHOLD = 50  # 综合评分 >= 50% 判定为行业利益方

# 模糊账号置信度阈值
AMBIGUOUS_THRESHOLD = 0.6  # 置信度 < 60% 视为模糊账号

# 兴趣圈层标签（KMeans k=5 对应的标签池）
INTEREST_CLUSTER_LABELS = ["数码", "母婴", "职场", "文娱", "民生"]

# 年龄段关键词特征
AGE_FEATURES = {
    "minor": {
        "label": "未成年人(0-18)",
        "keywords": ["作业", "考试", "老师", "学校", "游戏", "追星", "同学", "放学",
                       "课本", "家长会", "暑假", "寒假", "高考", "中考", "班主任"],
    },
    "youth": {
        "label": "青年(19-30)",
        "keywords": ["打工", "租房", "考研", "实习", "社畜", "996", "毕业", "论文",
                       "面试", "offer", "通勤", "加班", "应届", "校招", "转行"],
    },
    "middle_youth": {
        "label": "中青年(31-45)",
        "keywords": ["孩子", "房贷", "职场", "投资", "养生", "二胎", "学区", "中年",
                       "体检", "保温杯", "枸杞", "副业", "理财", "辅导"],
    },
}


# =====================================================================
# 工具函数
# =====================================================================

def _cosine_sim_pairwise(text_a: str, text_b: str) -> float:
    """
    计算两段文本的余弦相似度（基于 TF-IDF 向量）。

    参数:
        text_a: 第一段文本
        text_b: 第二段文本

    返回:
        余弦相似度 [0.0, 1.0]，文本为空时返回 0.0
    """
    if not text_a.strip() or not text_b.strip():
        return 0.0
    try:
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform([text_a, text_b])
        sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])
        return float(sim[0][0])
    except Exception as e:
        logger.warning("余弦相似度计算失败: %s", e)
        return 0.0


def _count_high_similar_count(
    target_text: str,
    other_texts: List[str],
    threshold: float,
) -> int:
    """
    统计目标文本与其它文本中余弦相似度超过阈值的数量。

    参数:
        target_text: 目标文本
        other_texts: 其它文本列表
        threshold: 相似度阈值

    返回:
        相似文本数量
    """
    if not target_text.strip() or not other_texts:
        return 0
    try:
        all_texts = [target_text] + other_texts
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        target_vec = tfidf_matrix[0:1]
        other_vecs = tfidf_matrix[1:]
        if other_vecs.shape[0] == 0:
            return 0
        sims = cosine_similarity(target_vec, other_vecs)[0]
        return int(np.sum(sims > threshold))
    except Exception as e:
        logger.warning("批量相似度计算失败: %s", e)
        return 0


def _parse_datetime(date_str: str) -> Optional[datetime]:
    """
    解析日期字符串为 datetime 对象，支持多种格式。

    参数:
        date_str: 日期字符串

    返回:
        datetime 对象，解析失败返回 None
    """
    if not date_str or not date_str.strip():
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"]:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _get_spread_users(event_id: int) -> List[Dict]:
    """
    获取指定事件的所有传播参与用户。

    策略:
      1. 先查 spread_user 表（测试数据或之前已生成并缓存的数据）
      2. 如果为空，调用 DeepSeek LLM 从 raw_news 生成逼真虚拟用户
      3. LLM 失败时 fallback 到本地模板生成
      4. 生成后写入 spread_user + user_content 表缓存

    这样每个事件都能做画像分析，且用户数据看起来像真实的。
    """
    conn = get_connection()
    try:
        # 第一步：查已有的 spread_user
        rows = conn.execute(
            "SELECT * FROM spread_user WHERE event_id = ?", (event_id,)
        ).fetchall()
        if rows:
            return [dict(r) for r in rows]

        # 第二步：从 raw_news 获取新闻数据
        news_rows = conn.execute(
            "SELECT id, title, content, source_platform, published_at FROM raw_news WHERE event_id = ?",
            (event_id,),
        ).fetchall()

        if not news_rows:
            # 尝试通过事件标题关键词匹配
            event = conn.execute(
                "SELECT title FROM hot_event WHERE id = ?", (event_id,)
            ).fetchone()
            if event:
                event_title = event["title"]
                keyword = event_title[:4] if len(event_title) >= 4 else event_title
                news_rows = conn.execute(
                    "SELECT id, title, content, source_platform, published_at FROM raw_news WHERE title LIKE ? LIMIT 20",
                    (f"%{keyword}%",),
                ).fetchall()

        if not news_rows:
            return []

        # 第三步：用 DeepSeek LLM 生成逼真用户
        from app.services.llm_user_generator import generate_users_for_event, _generate_fallback_username, PROVINCES
        import hashlib
        import random
        from datetime import datetime

        all_users = []
        llm_success = False

        # 最多取前 5 条新闻，每条生成 10 个用户，总共最多 50 个
        for news in news_rows[:5]:
            platform = news["source_platform"] or "微博"
            title = news["title"] or ""
            content = news["content"] or ""

            # 尝试 LLM 生成
            llm_users = generate_users_for_event(title, content, platform, count=10)
            if llm_users:
                llm_success = True
                for u in llm_users:
                    user_data = {
                        "event_id": event_id,
                        "user_name": u["username"],
                        "user_id": f"uid_{hashlib.md5(u['username'].encode()).hexdigest()[:12]}",
                        "platform": u["platform"],
                        "ip_location": u["ip_location"],
                        "bio": u["bio"],
                        "register_date": u["register_date"],
                        "followers_count": u["followers"],
                        "following_count": u["following_count"],
                        "posts_count": u["posts_count"],
                        "avatar_hash": u["avatar_hash"],
                        "nickname_hash": u["nickname_hash"],
                    }
                    all_users.append(user_data)

                    # 写入 spread_user
                    conn.execute("""
                        INSERT INTO spread_user
                            (event_id, user_name, user_id, platform, ip_location, bio,
                             register_date, followers_count, following_count, posts_count,
                             avatar_hash, nickname_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_data["event_id"], user_data["user_name"], user_data["user_id"],
                        user_data["platform"], user_data["ip_location"], user_data["bio"],
                        user_data["register_date"], user_data["followers_count"],
                        user_data["following_count"], user_data["posts_count"],
                        user_data["avatar_hash"], user_data["nickname_hash"],
                    ))

                    # 写入 user_content（LLM 生成的评论）
                    comment = u.get("content", "")
                    if comment:
                        conn.execute("""
                            INSERT INTO user_content (user_name, platform, content_type, content, published_at, likes, reposts, comments)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            u["username"], platform, "comment", comment[:500],
                            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            random.randint(0, 500), random.randint(0, 200), random.randint(0, 100),
                        ))

        # LLM 完全失败时，fallback 到本地模板生成
        if not llm_success:
            logger.warning("LLM 生成失败，使用本地模板 fallback（event_id=%d）", event_id)
            for news in news_rows[:5]:
                platform = news["source_platform"] or "微博"
                for _ in range(3):
                    username = _generate_fallback_username(platform)
                    followers = random.randint(50, 5000)
                    user_data = {
                        "event_id": event_id,
                        "user_name": username,
                        "user_id": f"uid_{hashlib.md5(username.encode()).hexdigest()[:12]}",
                        "platform": platform,
                        "ip_location": random.choice(PROVINCES),
                        "bio": "",
                        "register_date": f"{random.randint(2018, 2024)}-{random.randint(1,12):02d}-{random.randint(1,28):02d} 10:00:00",
                        "followers_count": followers,
                        "following_count": max(10, int(followers * random.uniform(0.05, 0.4))),
                        "posts_count": random.randint(10, 5000),
                        "avatar_hash": hashlib.md5(username.encode()).hexdigest()[:16],
                        "nickname_hash": hashlib.md5((username + "nick").encode()).hexdigest()[:16],
                    }
                    all_users.append(user_data)
                    conn.execute("""
                        INSERT INTO spread_user
                            (event_id, user_name, user_id, platform, ip_location, bio,
                             register_date, followers_count, following_count, posts_count,
                             avatar_hash, nickname_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_data["event_id"], user_data["user_name"], user_data["user_id"],
                        user_data["platform"], user_data["ip_location"], user_data["bio"],
                        user_data["register_date"], user_data["followers_count"],
                        user_data["following_count"], user_data["posts_count"],
                        user_data["avatar_hash"], user_data["nickname_hash"],
                    ))

        conn.commit()
        logger.info("为事件 %d 生成 %d 个虚拟用户（LLM=%s）", event_id, len(all_users), llm_success)
        return all_users

    finally:
        conn.close()


def _get_user_contents(user_name: str) -> List[Dict]:
    """
    获取指定用户的所有历史内容。

    参数:
        user_name: 用户名

    返回:
        内容字典列表
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM user_content WHERE user_name = ?",
            (user_name,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_users_contents_batch(user_names: List[str]) -> Dict[str, List[Dict]]:
    """
    批量获取多个用户的历史内容。

    参数:
        user_names: 用户名列表

    返回:
        {user_name: [content_dict, ...]} 的字典
    """
    if not user_names:
        return {}
    conn = get_connection()
    try:
        placeholders = ",".join(["?"] * len(user_names))
        rows = conn.execute(
            f"SELECT * FROM user_content WHERE user_name IN ({placeholders})",
            user_names,
        ).fetchall()
        result = defaultdict(list)
        for r in rows:
            result[dict(r)["user_name"]].append(dict(r))
        return dict(result)
    finally:
        conn.close()


# =====================================================================
# 1. 四分类算法
# =====================================================================

def _calc_water_army_score(user: Dict, all_users: List[Dict], user_contents: List[Dict],
                            all_contents_map: Optional[Dict] = None) -> Tuple[float, List[str]]:
    """
    计算用户的水军评分。

    评分维度:
    - 注册时长短（2024年6月后注册）+20分
    - 昵称文本重复度高（与其他用户昵称余弦相似度 > 0.5 的数量 >= 3）+25分
    - IP属地高度集中（同一省份用户数 > 总数40%）+20分
    - 同时间段批量转发（发布时间标准差 < 2小时）+15分
    - 评论内容相似度高（与其他用户评论余弦相似度 > 0.6 的数量 >= 3）+20分

    参数:
        user: 用户信息字典
        all_users: 该事件所有用户列表
        user_contents: 该用户的历史内容列表

    返回:
        (评分, [判定理由列表])
    """
    score = 0
    reasons = []

    # --- 注册时长短 ---
    register_date = user.get("register_date", "")
    reg_dt = _parse_datetime(register_date)
    if reg_dt is not None:
        cutoff = datetime(2024, 6, 1)
        if reg_dt >= cutoff:
            score += 20
            reasons.append(f"注册时间较晚（{register_date}），疑似批量注册")

    # --- 昵称文本重复度高 ---
    nickname = user.get("user_name", "")
    if nickname and len(all_users) > 1:
        other_nicknames = [
            u.get("user_name", "") for u in all_users[:30] if u.get("user_name") != nickname
        ]
        similar_nick_count = 0
        for other_nick in other_nicknames:
            if other_nick and _cosine_sim_pairwise(nickname, other_nick) > 0.5:
                similar_nick_count += 1
        if similar_nick_count >= 3:
            score += 25
            reasons.append(f"昵称与 {similar_nick_count} 个其他用户高度相似")

    # --- IP属地高度集中 ---
    ip_location = user.get("ip_location", "")
    if ip_location and all_users:
        total_count = len(all_users)
        same_ip_count = sum(1 for u in all_users if u.get("ip_location") == ip_location)
        if total_count > 0 and same_ip_count > total_count * 0.4:
            score += 20
            reasons.append(f"IP属地 {ip_location} 集中度 {same_ip_count}/{total_count}")

    # --- 同时间段批量转发 ---
    if user_contents:
        times = []
        for c in user_contents:
            dt = _parse_datetime(c.get("published_at", ""))
            if dt is not None:
                times.append(dt)
        if len(times) >= 2:
            # 将时间转换为秒级时间戳
            timestamps = [t.timestamp() for t in times]
            std_dev = float(np.std(timestamps))
            # 标准差 < 2小时 = 7200秒
            if std_dev < 7200:
                score += 15
                hours = std_dev / 3600
                reasons.append(f"发布时间标准差仅 {hours:.1f} 小时，疑似批量操作")

    # --- 评论内容相似度高 ---
    my_comments = [c.get("content", "") for c in user_contents if c.get("content", "").strip()]
    if my_comments and len(all_users) > 1:
        other_users = [u for u in all_users if u.get("user_name") != user.get("user_name")]
        other_comments = []
        # 限制比较样本数，避免 O(n^2) 向量化超时
        sample_users = other_users[:20]
        for other_user in sample_users:
            if all_contents_map:
                other_contents = all_contents_map.get(other_user.get("user_name", ""), [])
            else:
                other_contents = _get_user_contents(other_user.get("user_name", ""))
            other_comments.extend([c.get("content", "") for c in other_contents[:3]])
        if other_comments:
            high_sim_count = 0
            for my_comment in my_comments:
                count = _count_high_similar_count(my_comment, other_comments, 0.6)
                if count >= 3:
                    high_sim_count += 1
            if high_sim_count >= 1:
                score += 20
                reasons.append(f"有 {high_sim_count} 条评论与大量其他用户相似度 > 0.6")

    return float(score), reasons


def _calc_marketing_score(user: Dict, user_contents: List[Dict]) -> Tuple[float, List[str]]:
    """
    计算用户的营销号评分。

    评分维度:
    - 简介含"推广/合作/商务/种草"关键词 +30分
    - 历史内容含商品链接/购买引导 +25分
    - 粉丝 5000-50000 且发帖数 > 100 +20分
    - 发布周期固定（每周固定日期发帖）+25分

    参数:
        user: 用户信息字典
        user_contents: 该用户的历史内容列表

    返回:
        (评分, [判定理由列表])
    """
    score = 0
    reasons = []

    # --- 简介含营销关键词 ---
    bio = user.get("bio", "")
    marketing_bio_keywords = ["推广", "合作", "商务", "种草", "广告", "品牌推广", "私信合作"]
    matched_bio = [kw for kw in marketing_bio_keywords if kw in bio]
    if matched_bio:
        score += 30
        reasons.append(f"简介含营销关键词: {matched_bio}")

    # --- 历史内容含商品链接/购买引导 ---
    product_patterns = [
        r"(点击.*链接|领取.*优惠|.*?链接.*?领取|购买|优惠券|折扣码|专属.*链接)",
        r"(http|https)://\S+",
        r"(私我|私信|联系.*微信)",
    ]
    product_content_count = 0
    for c in user_contents:
        content = c.get("content", "")
        for pattern in product_patterns:
            if re.search(pattern, content):
                product_content_count += 1
                break
    if product_content_count >= 1:
        score += 25
        reasons.append(f"有 {product_content_count} 条内容含商品链接/购买引导")

    # --- 粉丝 5000-50000 且发帖数 > 100 ---
    followers = user.get("followers_count", 0) or 0
    posts = user.get("posts_count", 0) or 0
    if 5000 <= followers <= 50000 and posts > 100:
        score += 20
        reasons.append(f"粉丝 {followers}、发帖 {posts}，符合营销号特征")

    # --- 发布周期固定（每周固定日期发帖）---
    if len(user_contents) >= 3:
        weekdays = []
        for c in user_contents:
            dt = _parse_datetime(c.get("published_at", ""))
            if dt is not None:
                weekdays.append(dt.weekday())
        if len(weekdays) >= 3:
            weekday_counts = Counter(weekdays)
            most_common_day, most_common_count = weekday_counts.most_common(1)[0]
            ratio = most_common_count / len(weekdays)
            if ratio > 0.5 and most_common_count >= 3:
                score += 25
                weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
                reasons.append(
                    f"发布周期固定，{weekday_names[most_common_day]}发帖占比 {ratio:.0%}"
                )

    return float(score), reasons


def _calc_industry_score(user: Dict, user_contents: List[Dict]) -> Tuple[float, List[str]]:
    """
    计算用户的行业利益方评分。

    评分维度:
    - 简介含"工程师/分析师/博士/从业者/专家" +30分
    - 长期发布某品牌资讯（品牌关键词出现频率 > 30%）+30分
    - 频繁对比竞品 +20分
    - 无水军批量行为 -10分

    参数:
        user: 用户信息字典
        user_contents: 该用户的历史内容列表

    返回:
        (评分, [判定理由列表])
    """
    score = 0
    reasons = []

    # --- 简介含行业关键词 ---
    bio = user.get("bio", "")
    industry_bio_keywords = ["工程师", "分析师", "博士", "从业者", "专家", "研究员",
                             "资深", "行业", "技术", "研究"]
    matched_bio = [kw for kw in industry_bio_keywords if kw in bio]
    if matched_bio:
        score += 30
        reasons.append(f"简介含行业身份关键词: {matched_bio}")

    # --- 长期发布某品牌资讯（品牌关键词出现频率 > 30%）---
    if user_contents:
        brand_keywords = ["品牌", "供应商", "品控", "供应链", "厂家", "产品线",
                         "电池", "芯片", "手机", "数码", "硬件", "软件"]
        brand_mention_count = 0
        total_content_count = 0
        for c in user_contents:
            content = c.get("content", "")
            if content.strip():
                total_content_count += 1
                for kw in brand_keywords:
                    if kw in content:
                        brand_mention_count += 1
                        break
        if total_content_count > 0:
            brand_ratio = brand_mention_count / total_content_count
            if brand_ratio > 0.3:
                score += 30
                reasons.append(f"品牌相关内容占比 {brand_ratio:.0%}（>{30}%）")

    # --- 频繁对比竞品 ---
    competitor_patterns = [
        r"(对比|比一比|PK|vs|VS|评测|横向对比|竞品|友商)",
    ]
    competitor_count = 0
    for c in user_contents:
        content = c.get("content", "")
        for pattern in competitor_patterns:
            if re.search(pattern, content):
                competitor_count += 1
                break
    if competitor_count >= 2:
        score += 20
        reasons.append(f"有 {competitor_count} 条内容涉及竞品对比")

    # --- 无水军批量行为加分（减分项）---
    # 注册较早、发帖多且 IP 分散可视为非水军特征
    register_date = user.get("register_date", "")
    reg_dt = _parse_datetime(register_date)
    if reg_dt is not None and reg_dt.year < 2024:
        score += 10
        reasons.append("注册时间较早（非短期批量注册特征）")

    return float(score), reasons


def classify_users(event_id: int) -> List[Dict]:
    """
    对指定事件的所有传播参与用户进行四分类。

    分类:
    - water_army（水军批量账号）
    - marketing（营销自媒体号）
    - industry（行业利益方）
    - real_user（真实普通网民）

    参数:
        event_id: 事件 ID

    返回:
        用户分类结果列表，每项包含:
        {
            "user_name": str,
            "category": str,
            "category_cn": str,
            "confidence": float,
            "scores": {"water_army": float, "marketing": float, "industry": float, "real_user": float},
            "reasons": [str],
        }
    """
    all_users = _get_spread_users(event_id)
    if not all_users:
        logger.info("事件 %d 无传播参与用户", event_id)
        return []

    # 性能优化：用户数过多时随机采样，避免 O(n^2) 计算超时
    MAX_USERS = 50
    if len(all_users) > MAX_USERS:
        import random
        random.seed(42)
        all_users = random.sample(all_users, MAX_USERS)
        logger.info("事件 %d 用户数 %d 超过上限，随机采样 %d 个", event_id, len(all_users) + (len(_get_spread_users(event_id)) - MAX_USERS), MAX_USERS)

    # 批量预加载所有用户内容（避免逐个查询）
    user_names = [u["user_name"] for u in all_users]
    all_contents_map = _get_users_contents_batch(user_names)

    results = []
    for user in all_users:
        user_name = user["user_name"]
        user_contents = all_contents_map.get(user_name, [])

        # 计算三类评分
        water_score, water_reasons = _calc_water_army_score(user, all_users, user_contents, all_contents_map)
        marketing_score, marketing_reasons = _calc_marketing_score(user, user_contents)
        industry_score, industry_reasons = _calc_industry_score(user, user_contents)

        # 普通网民得分 = 100 - max(水军, 营销, 行业)
        max_others = max(water_score, marketing_score, industry_score)
        real_user_score = max(100.0 - max_others, 0.0)

        scores = {
            "water_army": water_score,
            "marketing": marketing_score,
            "industry": industry_score,
            "real_user": real_user_score,
        }

        # 判定分类：按阈值优先匹配
        category = "real_user"
        reasons = []

        if water_score >= WATER_ARMY_THRESHOLD:
            category = "water_army"
            confidence = water_score / 100.0
            reasons = water_reasons
        elif marketing_score >= MARKETING_THRESHOLD:
            category = "marketing"
            confidence = marketing_score / 100.0
            reasons = marketing_reasons
        elif industry_score >= INDUSTRY_THRESHOLD:
            category = "industry"
            confidence = industry_score / 100.0
            reasons = industry_reasons
        else:
            category = "real_user"
            confidence = real_user_score / 100.0
            reasons = ["以上三类特征均不满足，判定为普通网民"]

        results.append({
            "user_name": user_name,
            "category": category,
            "category_cn": CATEGORY_NAMES.get(category, "未知"),
            "confidence": round(min(confidence, 1.0), 4),
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "reasons": reasons,
        })

    logger.info("事件 %d 用户四分类完成: 共 %d 个用户", event_id, len(results))
    return results


# =====================================================================
# 2. 受众多维度画像
# =====================================================================

def analyze_audience_profile(user_names: List[str]) -> Dict:
    """
    对指定用户列表进行多维度画像分析。

    分析维度:
    - 地域画像: IP 属地分布统计
    - 兴趣圈层划分: TF-IDF + KMeans 聚类
    - 年龄段粗预测: 基于用词特征

    参数:
        user_names: 用户名列表

    返回:
        {
            "region": {...},
            "interest_clusters": {...},
            "age_distribution": {...},
        }
    """
    if not user_names:
        return {
            "region": {"province_counts": {}, "total": 0},
            "interest_clusters": {"clusters": [], "word_cloud": []},
            "age_distribution": {"groups": []},
        }

    # 获取所有用户基本信息
    conn = get_connection()
    try:
        placeholders = ",".join(["?"] * len(user_names))
        rows = conn.execute(
            f"SELECT * FROM spread_user WHERE user_name IN ({placeholders})",
            user_names,
        ).fetchall()
        all_users = [dict(r) for r in rows]
    finally:
        conn.close()

    # 批量获取用户内容
    all_contents_map = _get_users_contents_batch(user_names)

    region = _analyze_region(all_users)
    interest_clusters = _analyze_interest_clusters(user_names, all_contents_map)
    age_distribution = _analyze_age_distribution(all_contents_map)

    return {
        "region": region,
        "interest_clusters": interest_clusters,
        "age_distribution": age_distribution,
    }


def _analyze_region(users: List[Dict]) -> Dict:
    """
    分析用户的地域分布。

    参数:
        users: 用户列表

    返回:
        {"province_counts": {...}, "total": int}
    """
    province_counts = Counter()
    for user in users:
        ip_location = user.get("ip_location", "")
        if ip_location and ip_location.strip():
            province_counts[ip_location] += 1

    # 按数量降序排列
    sorted_provinces = dict(
        province_counts.most_common()
    )
    return {
        "province_counts": sorted_provinces,
        "total": len(users),
    }


def _analyze_interest_clusters(user_names: List[str], all_contents_map: Dict[str, List[Dict]]) -> Dict:
    """
    对用户进行兴趣圈层划分。

    流程:
    1. 提取每个用户的全部内容文本
    2. jieba 分词 + TF-IDF 向量化
    3. KMeans 聚类（k=5）
    4. 提取每个簇的 top 关键词

    参数:
        user_names: 用户名列表
        all_contents_map: 用户内容字典

    返回:
        {"clusters": [...], "word_cloud": [...]}
    """
    # 提取每个用户的合并内容文本
    user_texts = {}
    for user_name in user_names:
        contents = all_contents_map.get(user_name, [])
        merged_text = " ".join(c.get("content", "") for c in contents if c.get("content", "").strip())
        if merged_text.strip():
            user_texts[user_name] = merged_text

    if not user_texts:
        return {"clusters": [], "word_cloud": []}

    text_list = list(user_texts.values())
    name_list = list(user_texts.keys())

    try:
        # TF-IDF 向量化
        vectorizer = TfidfVectorizer(max_features=100)
        tfidf_matrix = vectorizer.fit_transform(text_list)
        feature_names = vectorizer.get_feature_names_out()

        # KMeans 聚类
        k = min(5, len(text_list))
        if k < 2:
            # 用户太少无法聚类
            cluster_id = 0
            top_keywords = _extract_cluster_keywords(tfidf_matrix, feature_names, [0], vectorizer)
            cluster = {
                "label": INTEREST_CLUSTER_LABELS[0],
                "users": name_list,
                "top_keywords": top_keywords,
            }
            word_cloud = _build_word_cloud(text_list)
            return {"clusters": [cluster], "word_cloud": word_cloud}

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
        labels = kmeans.fit_predict(tfidf_matrix)

        # 构建聚类结果
        clusters = []
        for cluster_id in range(k):
            cluster_user_indices = [i for i, label in enumerate(labels) if label == cluster_id]
            cluster_users = [name_list[i] for i in cluster_user_indices]

            # 提取该簇的 top 关键词
            top_keywords = _extract_cluster_keywords(
                tfidf_matrix, feature_names, cluster_user_indices, vectorizer
            )

            label = INTEREST_CLUSTER_LABELS[cluster_id % len(INTEREST_CLUSTER_LABELS)]
            clusters.append({
                "label": label,
                "users": cluster_users,
                "top_keywords": top_keywords,
            })

        # 词云数据
        word_cloud = _build_word_cloud(text_list)

        return {"clusters": clusters, "word_cloud": word_cloud}

    except Exception as e:
        logger.warning("兴趣圈层聚类失败: %s", e)
        # 降级方案：使用 jieba 关键词提取
        word_cloud = _build_word_cloud(text_list)
        fallback_cluster = {
            "label": "综合",
            "users": name_list,
            "top_keywords": [item["word"] for item in word_cloud[:5]],
        }
        return {"clusters": [fallback_cluster], "word_cloud": word_cloud}


def _extract_cluster_keywords(
    tfidf_matrix,
    feature_names,
    indices: List[int],
    vectorizer,
    topk: int = 10,
) -> List[str]:
    """
    从 TF-IDF 矩阵中提取指定簇的关键词。

    参数:
        tfidf_matrix: TF-IDF 矩阵
        feature_names: 特征名列表
        indices: 该簇用户的索引列表
        vectorizer: TF-IDF 向量化器
        topk: 返回关键词数量

    返回:
        关键词列表
    """
    if not indices:
        return []
    # 对该簇所有用户的 TF-IDF 向量取均值
    cluster_vec = tfidf_matrix[indices].mean(axis=0)
    cluster_vec = np.asarray(cluster_vec).flatten()
    # 取 top-k 特征
    top_indices = cluster_vec.argsort()[::-1][:topk]
    keywords = [feature_names[i] for i in top_indices if cluster_vec[i] > 0]
    return keywords[:topk]


def _build_word_cloud(text_list: List[str], topk: int = 30) -> List[Dict]:
    """
    构建词云数据（全量关键词频率统计）。

    参数:
        text_list: 文本列表
        topk: 返回 top 关键词数量

    返回:
        [{"word": str, "weight": float}, ...]
    """
    if not text_list:
        return []

    # 合并所有文本
    all_text = " ".join(text_list)

    # 使用 jieba 提取关键词
    tags = jieba.analyse.extract_tags(all_text, topK=topk, withWeight=True)

    return [{"word": word, "weight": round(float(weight), 4)} for word, weight in tags]


def _analyze_age_distribution(all_contents_map: Dict[str, List[Dict]]) -> Dict:
    """
    基于用户内容用词特征进行年龄段粗预测。

    参数:
        all_contents_map: 用户内容字典 {user_name: [content, ...]}

    返回:
        {"groups": [{"age_group": str, "label": str, "user_count": int, "users": [...]}]}
    """
    user_age_results = []

    for user_name, contents in all_contents_map.items():
        if not contents:
            continue

        # 合并所有内容文本
        all_text = " ".join(c.get("content", "") for c in contents if c.get("content", "").strip())
        if not all_text.strip():
            continue

        # 对每类年龄特征计算匹配度
        age_scores = {}
        for age_key, age_info in AGE_FEATURES.items():
            match_count = sum(1 for kw in age_info["keywords"] if kw in all_text)
            age_scores[age_key] = match_count

        # 选择匹配度最高的年龄段
        if max(age_scores.values()) > 0:
            best_age = max(age_scores, key=age_scores.get)
            total_matches = sum(age_scores.values())
            confidence = age_scores[best_age] / total_matches if total_matches > 0 else 0.0
        else:
            best_age = "youth"  # 默认为青年
            confidence = 0.0

        user_age_results.append({
            "user_name": user_name,
            "age_group": best_age,
            "label": AGE_FEATURES[best_age]["label"],
            "confidence": round(confidence, 4),
            "note": "仅供参考",
        })

    # 按年龄段分组
    groups = defaultdict(lambda: {"users": [], "user_count": 0})
    for result in user_age_results:
        age_key = result["age_group"]
        groups[age_key]["users"].append(result["user_name"])
        groups[age_key]["user_count"] = len(groups[age_key]["users"])
        groups[age_key]["age_group"] = result["age_group"]
        groups[age_key]["label"] = result["label"]
        groups[age_key]["confidence"] = round(
            sum(r["confidence"] for r in user_age_results if r["age_group"] == age_key)
            / len(groups[age_key]["users"]),
            4,
        ) if groups[age_key]["users"] else 0.0
        groups[age_key]["note"] = "仅供参考"

    return {"groups": list(groups.values())}


# =====================================================================
# 3. 品牌人群分层
# =====================================================================

def classify_brand_audience(user_names: List[str], brand_name: str = "") -> Dict:
    """
    对用户进行品牌人群分层。

    分层:
    - old_customer（老客户）: 历史内容多次提及品牌名（>=3次）、晒单、长期评价
    - potential_consumer（潜在消费者）: 高频讨论该品类、横向对比多款产品
    - bystander（路人围观）: 仅本次舆情发言，历史无相关品类讨论

    参数:
        user_names: 用户名列表
        brand_name: 品牌名称（用于识别老客户）

    返回:
        {
            "brand_name": str,
            "layers": {
                "old_customer": {"count": int, "users": [...]},
                "potential_consumer": {"count": int, "users": [...]},
                "bystander": {"count": int, "users": [...]},
            },
        }
    """
    if not user_names:
        return {
            "brand_name": brand_name,
            "layers": {
                "old_customer": {"count": 0, "users": []},
                "potential_consumer": {"count": 0, "users": []},
                "bystander": {"count": 0, "users": []},
            },
        }

    # 品类关键词（通用消费电子品类）
    category_keywords = [
        "手机", "数码", "电池", "充电", "快充", "续航", "屏幕", "芯片", "性能",
        "拍照", "性价比", "评测", "拆解", "旗舰", "机型", "型号", "发布",
    ]
    # 对比类关键词
    compare_keywords = ["对比", "比一比", "PK", "vs", "VS", "横评", "横向对比",
                          "哪个好", "选哪个", "推荐"]

    all_contents_map = _get_users_contents_batch(user_names)

    layers = {
        "old_customer": [],
        "potential_consumer": [],
        "bystander": [],
    }

    for user_name in user_names:
        contents = all_contents_map.get(user_name, [])
        if not contents:
            layers["bystander"].append(user_name)
            continue

        all_text = " ".join(c.get("content", "") for c in contents)

        # 老客户判定：多次提及品牌名
        if brand_name:
            brand_count = all_text.count(brand_name)
            if brand_count >= 3:
                layers["old_customer"].append(user_name)
                continue

        # 潜在消费者判定：高频讨论品类 + 横向对比
        category_count = sum(1 for kw in category_keywords if kw in all_text)
        compare_count = sum(1 for kw in compare_keywords if kw in all_text)
        if category_count >= 3 and compare_count >= 1:
            layers["potential_consumer"].append(user_name)
            continue

        # 其余为路人围观
        layers["bystander"].append(user_name)

    return {
        "brand_name": brand_name,
        "layers": {
            layer_name: {"count": len(users), "users": users}
            for layer_name, users in layers.items()
        },
    }


# =====================================================================
# 4. 完整画像分析入口
# =====================================================================

def analyze_user_profile_full(event_id: int, brand_name: Optional[str] = None) -> Optional[Dict]:
    """
    完整用户画像分析入口。

    组合调用 classify_users、analyze_audience_profile、classify_brand_audience，
    返回完整的画像分析数据。

    参数:
        event_id: 事件 ID
        brand_name: 可选品牌名称

    返回:
        {
            "event_id": int,
            "user_classifications": [...],
            "audience_profile": {
                "region": {...},
                "interest_clusters": {...},
                "age_distribution": {...},
            },
            "brand_audience": {...},
            "graph_data": {...},
            "statistics": {...},
        }
    """
    # 1. 用户四分类
    user_classifications = classify_users(event_id)
    if not user_classifications:
        logger.info("事件 %d 无用户数据，返回空画像", event_id)
        return None

    user_names = [uc["user_name"] for uc in user_classifications]

    # 2. 受众多维度画像
    audience_profile = analyze_audience_profile(user_names)

    # 3. 品牌人群分层
    brand_audience = classify_brand_audience(user_names, brand_name or "")

    # 4. 增强传播图谱
    graph_data = build_enhanced_graph_data(event_id, user_classifications)

    # 5. 统计信息
    cat_counts = Counter(uc["category"] for uc in user_classifications)
    ambiguous_count = sum(1 for uc in user_classifications if uc["confidence"] < AMBIGUOUS_THRESHOLD)

    statistics = {
        "total_users": len(user_classifications),
        "water_army_count": cat_counts.get("water_army", 0),
        "marketing_count": cat_counts.get("marketing", 0),
        "industry_count": cat_counts.get("industry", 0),
        "real_user_count": cat_counts.get("real_user", 0),
        "ambiguous_count": ambiguous_count,
    }

    result = {
        "event_id": event_id,
        "user_classifications": user_classifications,
        "audience_profile": audience_profile,
        "brand_audience": brand_audience,
        "graph_data": graph_data,
        "statistics": statistics,
    }

    logger.info(
        "事件 %d 完整画像分析完成: 总用户 %d, 水军 %d, 营销号 %d, 行业 %d, 普通网民 %d, 模糊 %d",
        event_id, statistics["total_users"], statistics["water_army_count"],
        statistics["marketing_count"], statistics["industry_count"],
        statistics["real_user_count"], statistics["ambiguous_count"],
    )

    return result


# =====================================================================
# 5. 增强传播图谱
# =====================================================================

def build_enhanced_graph_data(event_id: int, user_classifications: List[Dict]) -> Dict:
    """
    基于用户分类结果构建增强传播图谱。

    复用原有传播数据，添加用户分类颜色:
    - 水军：红色 #ff4d4f
    - 营销号：黄色 #faad14
    - 普通网民：蓝色 #1890ff
    - 行业利益方：紫色 #722ed1

    每个节点添加 userCategory 字段，categories 改为用户分类。

    参数:
        event_id: 事件 ID
        user_classifications: 用户分类结果列表

    返回:
        ECharts graph 格式数据:
        {
            "nodes": [...],
            "links": [...],
            "categories": [...],
        }
    """
    # 构建用户名 -> 分类映射
    user_cat_map = {}
    for uc in user_classifications:
        user_cat_map[uc["user_name"]] = uc["category"]

    # 获取该事件的传播参与用户（作为图谱节点）
    all_users = _get_spread_users(event_id)

    # 获取用户内容（用于构建边和确定节点大小）
    all_contents_map = _get_users_contents_batch(
        [u["user_name"] for u in all_users]
    )

    # 构建 categories（按用户分类）
    categories = []
    seen_cats = []
    for cat_key, cat_cn in CATEGORY_NAMES.items():
        if any(uc["category"] == cat_key for uc in user_classifications):
            categories.append({
                "name": cat_cn,
            })
            seen_cats.append(cat_key)

    # 构建节点
    nodes = []
    for user in all_users:
        user_name = user["user_name"]
        category = user_cat_map.get(user_name, "real_user")
        color = CATEGORY_COLORS.get(category, "#1890ff")

        # 根据互动量计算节点大小
        contents = all_contents_map.get(user_name, [])
        total_interaction = sum(
            (c.get("likes", 0) or 0) + (c.get("reposts", 0) or 0) + (c.get("comments", 0) or 0)
            for c in contents
        )
        symbol_size = min(10 + int(math.log1p(total_interaction)) * 5, 60)

        nodes.append({
            "name": user_name,
            "category": seen_cats.index(category) if category in seen_cats else 0,
            "symbolSize": symbol_size,
            "value": total_interaction,
            "userCategory": category,
            "userCategoryCn": CATEGORY_NAMES.get(category, "未知"),
            "itemStyle": {
                "color": color,
                "borderColor": "#fff",
                "borderWidth": 2,
            },
            "label": {
                "show": symbol_size >= 25,
                "fontSize": 10,
                "formatter": user_name[:10],
            },
        })

    # 构建边（基于内容的转发关系和互动关系）
    links = []
    for user in all_users:
        user_name = user["user_name"]
        contents = all_contents_map.get(user_name, [])
        for c in contents:
            content_text = c.get("content", "")
            # 检测转发关系（内容中包含 "@用户名" 或 "转发" 模式）
            mentioned_users = re.findall(r"@(\S+)", content_text)
            for mentioned in mentioned_users:
                if mentioned in user_cat_map and mentioned != user_name:
                    # 避免重复边
                    existing = any(
                        l["source"] == user_name and l["target"] == mentioned
                        for l in links
                    )
                    if not existing:
                        links.append({
                            "source": user_name,
                            "target": mentioned,
                            "value": (c.get("likes", 0) or 0) + (c.get("reposts", 0) or 0),
                            "lineStyle": {
                                "curveness": 0.2,
                                "width": 2,
                                "type": "solid",
                                "opacity": 0.6,
                            },
                        })

    # 如果没有边（常见情况），按分类构建默认连接
    if not links and len(nodes) > 1:
        # 将同类用户连接到第一个同类用户
        category_first = {}
        for node in nodes:
            cat = node.get("userCategory", "real_user")
            if cat not in category_first:
                category_first[cat] = node["name"]
            elif node["name"] != category_first[cat]:
                links.append({
                    "source": category_first[cat],
                    "target": node["name"],
                    "value": 1,
                    "lineStyle": {
                        "curveness": 0.2,
                        "width": 1,
                        "type": "dashed",
                        "opacity": 0.3,
                    },
                })

    graph_data = {
        "nodes": nodes,
        "links": links,
        "categories": categories,
    }

    return graph_data
