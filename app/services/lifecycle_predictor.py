# -*- coding: utf-8 -*-
"""
================================================================================
  舆情生命周期预测模块 (lifecycle_predictor.py)
================================================================================
基于历史热度时序数据，判断舆情所处的生命周期阶段。

生命周期定义:
  - latent   (萌芽期): 事件刚被发现，报道数量极少
  - growth   (发酵期): 报道数量持续增长，热度上升
  - peak     (峰值期): 报道数量达到最高点或趋于平稳
  - decline  (衰退期): 报道数量持续下降，热度衰退

核心功能:
  1. classify_lifecycle — 基于事件分析记录的时间序列判断生命周期阶段
  2. predict_trend — 简易热度趋势预测（基于线性外推）
  3. update_all_lifecycles — 批量更新所有事件的 lifecycle 字段

使用方式:
  from app.services.lifecycle_predictor import update_all_lifecycles
  result = update_all_lifecycles()

  from app.services.lifecycle_predictor import classify_lifecycle, predict_trend
  stage = classify_lifecycle(event_id=42)
  trend = predict_trend(event_id=42)

依赖:
  - app.core.database: 数据库连接管理
================================================================================
"""

import logging
from datetime import datetime, timedelta

from app.core.database import get_connection

logger = logging.getLogger("services.lifecycle_predictor")


# ---------------------------------------------------------------------------
# 辅助函数：解析日期时间字符串
# ---------------------------------------------------------------------------
def _parse_datetime(dt_str: str) -> datetime:
    """
    安全解析日期时间字符串为 datetime 对象。
    支持格式: "2024-01-15 10:30:00" 或 "2024-01-15T10:30:00"

    参数:
        dt_str: 日期时间字符串

    返回:
        datetime 对象，解析失败返回当前时间
    """
    if not dt_str:
        return datetime.now()

    # 尝试多种常见格式
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(dt_str, fmt)
        except (ValueError, TypeError):
            continue

    logger.debug("日期解析失败: %s，使用当前时间", dt_str)
    return datetime.now()


# ---------------------------------------------------------------------------
# 核心函数1：判断事件生命周期阶段
# ---------------------------------------------------------------------------
def classify_lifecycle(event_id: int) -> str:
    """
    基于事件的历史热度数据判断生命周期阶段。

    判断逻辑（简化版，基于 event_analysis 表的分析记录时间序列）:
      1. 查找该事件的所有 event_analysis 记录（按 analyzed_at 排序）
      2. 如果只有 1 条记录 → "latent"（萌芽期）
      3. 如果最近一条的正面+负面情感比例之和比前一条高 → "growth"（发酵期）
         （情感波动大说明讨论增多、热度上升）
      4. 如果最近一条和前一条基本持平或略低 → "peak"（峰值期）
      5. 如果连续下降 → "decline"（衰退期）

    如果没有分析记录:
      - 事件创建 < 1小时 → "latent"（萌芽期）
      - 事件创建 1~6小时 → "growth"（发酵期）
      - 事件创建 > 6小时 → "peak"（峰值期）

    参数:
        event_id: 事件 ID

    返回:
        生命周期阶段字符串: "latent" / "growth" / "peak" / "decline"
    """
    conn = get_connection()
    try:
        # 查询事件的基本信息（用于无分析记录时的估算）
        event = conn.execute(
            "SELECT created_at FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()

        if event is None:
            logger.debug("事件 ID=%d 不存在，返回 latent", event_id)
            return "latent"

        # 查询该事件的所有分析记录（按时间排序）
        analyses = conn.execute(
            "SELECT positive_ratio, negative_ratio, neutral_ratio, analyzed_at "
            "FROM event_analysis "
            "WHERE event_id = ? "
            "ORDER BY analyzed_at ASC",
            (event_id,),
        ).fetchall()

        # 构建热度指标序列（用正面+负面比例之和作为热度代理指标）
        # 情感波动越大，说明讨论越激烈，热度越高
        heat_indicators = []
        for a in analyses:
            # 热度指标 = 正面比例 + 负面比例（中性比例高时说明关注度低）
            heat = (a["positive_ratio"] or 0) + (a["negative_ratio"] or 0)
            heat_indicators.append(heat)

        # 如果没有分析记录，基于创建时间估算
        if len(heat_indicators) == 0:
            created_at = _parse_datetime(event["created_at"])
            hours_elapsed = (datetime.now() - created_at).total_seconds() / 3600

            if hours_elapsed < 1:
                stage = "latent"
            elif hours_elapsed < 6:
                stage = "growth"
            else:
                stage = "peak"

            logger.debug(
                "事件 ID=%d 无分析记录，基于创建时间 %d 小时估算: %s",
                event_id, int(hours_elapsed), stage,
            )
            return stage

        # 只有一条分析记录 → 萌芽期
        if len(heat_indicators) == 1:
            return "latent"

        # 多条记录：比较趋势
        n = len(heat_indicators)
        latest = heat_indicators[-1]
        previous = heat_indicators[-2]

        # 计算变化量
        delta = latest - previous

        # 允许的波动阈值（避免微小波动导致误判）
        threshold = 0.02

        if delta > threshold:
            # 最近的热度指标上升 → 发酵期
            return "growth"
        elif delta < -threshold:
            # 最近的热度指标下降
            # 检查是否连续下降（最后两条都在下降）
            if n >= 3 and heat_indicators[-2] < heat_indicators[-3] - threshold:
                # 连续下降 → 衰退期
                return "decline"
            else:
                # 只是略微下降，可能是波峰过渡 → 峰值期
                return "peak"
        else:
            # 基本持平 → 峰值期
            return "peak"

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数2：热度趋势预测（线性外推）
# ---------------------------------------------------------------------------
def predict_trend(event_id: int) -> dict:
    """
    简易热度趋势预测（基于线性外推）。

    算法:
      1. 获取事件创建时间和当前时间的时间差（小时数）
      2. 获取 raw_news 中关联新闻的数量随时间的分布
      3. 将时间轴划分为若干小时桶，统计每个桶的新闻数量
      4. 如果数据点 >= 2，用线性回归拟合趋势
      5. 基于拟合斜率预测未来 6/12/24 小时的热度

    参数:
        event_id: 事件 ID

    返回:
        趋势预测结果:
        {
            "event_id": int,                # 事件 ID
            "current_lifecycle": str,        # 当前生命周期阶段
            "predicted_trend": str,          # 预测趋势: "rising" / "stable" / "declining"
            "predicted_heat_6h": float,       # 预测 6 小时后热度
            "predicted_heat_12h": float,     # 预测 12 小时后热度
            "predicted_heat_24h": float,     # 预测 24 小时后热度
            "confidence": float,             # 置信度 (0-1，数据点越多越可信)
        }
    """
    conn = get_connection()
    try:
        # 获取事件基本信息
        event = conn.execute(
            "SELECT id, title, created_at, heat_score FROM hot_event WHERE id = ?",
            (event_id,),
        ).fetchone()

        if event is None:
            return {
                "event_id": event_id,
                "current_lifecycle": "unknown",
                "predicted_trend": "stable",
                "predicted_heat_6h": 0.0,
                "predicted_heat_12h": 0.0,
                "predicted_heat_24h": 0.0,
                "confidence": 0.0,
            }

        # 判断当前生命周期
        current_lifecycle = classify_lifecycle(event_id)

        # 获取事件创建时间
        created_at = _parse_datetime(event["created_at"])
        now = datetime.now()

        # 获取关联新闻的时间分布
        # 通过标题关键词匹配获取关联新闻
        title = event["title"] or ""
        import jieba
        keywords = [w for w in jieba.cut(title) if len(w.strip()) >= 2][:5]

        news_data = []  # [(hours_since_creation, count), ...]
        if keywords:
            like_conditions = " OR ".join(["title LIKE ?" for _ in keywords])
            news_rows = conn.execute(
                f"SELECT published_at FROM raw_news "
                f"WHERE ({like_conditions}) AND published_at IS NOT NULL "
                f"ORDER BY published_at ASC",
                [f"%{kw}%" for kw in keywords],
            ).fetchall()

            # 按小时桶统计新闻数量
            hourly_counts = defaultdict(int)
            for row in news_rows:
                pub_time = _parse_datetime(row["published_at"])
                if pub_time < created_at:
                    continue
                hour_bucket = int((pub_time - created_at).total_seconds() / 3600)
                hourly_counts[hour_bucket] += 1

            # 构造数据点列表
            max_hour = max(hourly_counts.keys()) if hourly_counts else 0
            for h in range(max_hour + 1):
                news_data.append((h, hourly_counts.get(h, 0)))

        # 当前热度基数
        current_heat = event["heat_score"] or 0.0

        # 默认预测结果
        default_result = {
            "event_id": event_id,
            "current_lifecycle": current_lifecycle,
            "predicted_trend": "stable",
            "predicted_heat_6h": current_heat,
            "predicted_heat_12h": current_heat,
            "predicted_heat_24h": current_heat,
            "confidence": 0.3,
        }

        # 数据点不足，无法拟合趋势
        if len(news_data) < 2:
            logger.debug(
                "事件 ID=%d 数据点不足 (%d)，返回默认预测",
                event_id, len(news_data),
            )
            return default_result

        # 线性回归拟合：y = slope * x + intercept
        n = len(news_data)
        sum_x = sum(p[0] for p in news_data)
        sum_y = sum(p[1] for p in news_data)
        sum_xy = sum(p[0] * p[1] for p in news_data)
        sum_x2 = sum(p[0] ** 2 for p in news_data)

        denominator = n * sum_x2 - sum_x ** 2
        if abs(denominator) < 1e-10:
            # 分母为零（所有 x 相同），无法拟合
            return default_result

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        # 当前时间距创建的小时数
        hours_elapsed = (now - created_at).total_seconds() / 3600

        # 预测未来 6/12/24 小时的新闻增速
        future_6h = slope * (hours_elapsed + 6) + intercept
        future_12h = slope * (hours_elapsed + 12) + intercept
        future_24h = slope * (hours_elapsed + 24) + intercept

        # 将预测的新闻增速映射到热度分数（0-100）
        def _news_to_heat(news_rate: float) -> float:
            """将预测的新闻速率映射为热度分数"""
            base = current_heat
            delta = news_rate * 5  # 每条新闻贡献 5 点热度
            return max(0.0, min(100.0, base + delta))

        predicted_heat_6h = _news_to_heat(future_6h)
        predicted_heat_12h = _news_to_heat(future_12h)
        predicted_heat_24h = _news_to_heat(future_24h)

        # 判断趋势方向
        if slope > 0.5:
            predicted_trend = "rising"
        elif slope < -0.5:
            predicted_trend = "declining"
        else:
            predicted_trend = "stable"

        # 计算置信度（数据点越多，置信度越高）
        confidence = min(1.0, n / 20.0)  # 20 个数据点时置信度为 1.0

        logger.debug(
            "事件 ID=%d 趋势预测: lifecycle=%s, trend=%s, slope=%.2f, confidence=%.2f",
            event_id, current_lifecycle, predicted_trend, slope, confidence,
        )

        return {
            "event_id": event_id,
            "current_lifecycle": current_lifecycle,
            "predicted_trend": predicted_trend,
            "predicted_heat_6h": round(predicted_heat_6h, 2),
            "predicted_heat_12h": round(predicted_heat_12h, 2),
            "predicted_heat_24h": round(predicted_heat_24h, 2),
            "confidence": round(confidence, 2),
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 核心函数3：批量更新所有事件的 lifecycle 字段
# ---------------------------------------------------------------------------
def update_all_lifecycles() -> dict:
    """
    批量更新所有事件的 lifecycle 字段。
    遍历所有 hot_event，对每个调用 classify_lifecycle 并更新数据库。

    更新策略:
      - 仅当新计算的 lifecycle 与数据库中不同时才更新
      - 同时更新 updated_at 时间戳

    返回:
        批量更新结果统计:
        {
            "updated": int,      # 实际更新的记录数
            "latent": int,       # 当前处于萌芽期的事件数
            "growth": int,       # 当前处于发酵期的事件数
            "peak": int,         # 当前处于峰值期的事件数
            "decline": int,      # 当前处于衰退期的事件数
        }
    """
    conn = get_connection()
    try:
        # 获取所有热点事件
        events = conn.execute(
            "SELECT id, lifecycle FROM hot_event"
        ).fetchall()

        if not events:
            logger.info("无热点事件，跳过生命周期更新")
            return {"updated": 0, "latent": 0, "growth": 0, "peak": 0, "decline": 0}

        updated = 0
        stage_counts = {"latent": 0, "growth": 0, "peak": 0, "decline": 0}

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for event in events:
            event_id = event["id"]
            current_lifecycle = event["lifecycle"] or "latent"

            # 计算新的生命周期阶段
            new_lifecycle = classify_lifecycle(event_id)
            stage_counts[new_lifecycle] = stage_counts.get(new_lifecycle, 0) + 1

            # 仅当阶段发生变化时才更新数据库
            if new_lifecycle != current_lifecycle:
                conn.execute(
                    "UPDATE hot_event SET lifecycle = ?, updated_at = ? WHERE id = ?",
                    (new_lifecycle, now_str, event_id),
                )
                # 同时更新 event_analysis 的 lifecycle 字段（如果存在）
                try:
                    existing = conn.execute(
                        "SELECT event_id FROM event_analysis WHERE event_id = ? LIMIT 1",
                        (event_id,)
                    ).fetchone()
                    if existing:
                        conn.execute(
                            "UPDATE event_analysis SET lifecycle = ? WHERE event_id = ?",
                            (new_lifecycle, event_id)
                        )
                    else:
                        conn.execute(
                            "INSERT INTO event_analysis (event_id, lifecycle, analyzed_at) VALUES (?, ?, ?)",
                            (event_id, new_lifecycle, now_str)
                        )
                except Exception:
                    pass
                updated += 1

        conn.commit()
        logger.info(
            "批量生命周期更新完成: 更新 %d 条, "
            "latent=%d, growth=%d, peak=%d, decline=%d",
            updated,
            stage_counts.get("latent", 0),
            stage_counts.get("growth", 0),
            stage_counts.get("peak", 0),
            stage_counts.get("decline", 0),
        )

        return {
            "updated": updated,
            "latent": stage_counts.get("latent", 0),
            "growth": stage_counts.get("growth", 0),
            "peak": stage_counts.get("peak", 0),
            "decline": stage_counts.get("decline", 0),
        }

    finally:
        conn.close()
