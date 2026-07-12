# -*- coding: utf-8 -*-
"""
================================================================================
  短期热度走势简易预判模块 (heat_predictor.py)
================================================================================
依托传播节点、过往传播节奏，预测未来 24~72 小时事件热度的
上涨/平稳/回落走向，罗列影响热度变动的潜在变量。

复用已有数据:
  - hot_event 表（当前热度、生命周期阶段）
  - raw_news 表（报道量时序数据）
  - spread_info 表（传播节点数据）
  - lifecycle_predictor（生命周期分类）

预判逻辑:
  1. 计算过去 N 天的日均报道量及增长斜率
  2. 结合生命周期阶段判断趋势
  3. 识别影响热度的潜在变量（周末效应、官方介入、情绪激化等）
  4. 输出通俗结论 + 变量清单

输出结构:
  {
    "current_lifecycle": "growth",
    "trend_prediction": "上涨",
    "confidence": 0.7,
    "prediction_details": {
      "24h": {"direction": "up", "description": "..."},
      "72h": {"direction": "stable", "description": "..."}
    },
    "potential_variables": [
      {"factor": "周末效应", "impact": "可能加速传播", "probability": "中"}
    ],
    "summary": "通俗预判结论文本"
  }
================================================================================
"""

import math
import logging
from typing import List, Dict
from datetime import datetime, timedelta
from collections import defaultdict
from app.core.database import get_connection

logger = logging.getLogger("services.heat_predictor")


def predict_heat_trend(event_id: int) -> Dict:
    """
    预测指定事件的短期热度走势。

    参数:
        event_id: 事件 ID

    返回:
        热度预判结果字典
    """
    conn = get_connection()
    try:
        event = conn.execute(
            "SELECT * FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None
        event = dict(event)  # 转为 dict 以支持 .get() 方法

        # 1. 获取报道量时序数据
        daily_counts = _get_daily_report_counts(conn, event_id, event["title"])

        # 2. 计算趋势指标
        slope, acceleration = _calc_trend(daily_counts)

        # 3. 获取当前生命周期
        lifecycle = event.get("lifecycle", "growth")
        heat_score = event.get("heat_score", 0)

        # 4. 识别潜在变量
        variables = _identify_variables(event, daily_counts)

        # 5. 综合预判
        prediction_24h = _predict_24h(slope, acceleration, lifecycle, daily_counts)
        prediction_72h = _predict_72h(slope, acceleration, lifecycle, daily_counts)

        # 整体趋势
        if prediction_24h["direction"] == "up" and prediction_72h["direction"] == "up":
            overall_trend = "上涨"
        elif prediction_24h["direction"] == "down" and prediction_72h["direction"] == "down":
            overall_trend = "回落"
        elif prediction_24h["direction"] == "stable" and prediction_72h["direction"] == "stable":
            overall_trend = "平稳"
        else:
            overall_trend = "先涨后稳" if prediction_24h["direction"] == "up" else "震荡"

        # 置信度
        confidence = _calc_confidence(len(daily_counts), slope, lifecycle)

        # 通俗结论
        summary = _generate_summary(
            event["title"], lifecycle, heat_score,
            overall_trend, prediction_24h, prediction_72h, variables
        )

        result = {
            "event_id": event_id,
            "current_lifecycle": lifecycle,
            "current_heat": heat_score,
            "trend_prediction": overall_trend,
            "confidence": confidence,
            "prediction_details": {
                "24h": prediction_24h,
                "72h": prediction_72h,
            },
            "potential_variables": variables,
            "summary": summary,
        }

        logger.info(
            "事件 %d 热度预判: 当前生命周期=%s, 预测趋势=%s, 置信度=%.0f%%",
            event_id, lifecycle, overall_trend, confidence * 100,
        )

        return result

    except Exception as e:
        logger.error("热度预判失败: event_id=%d, %s", event_id, e)
        return None
    finally:
        conn.close()


def _get_daily_report_counts(conn, event_id: int, event_title: str) -> Dict[str, int]:
    """获取事件每日报道量"""
    from app.services.nlp_tools import segment_text

    # 优先通过 event_id
    rows = conn.execute(
        "SELECT published_at FROM raw_news WHERE event_id = ? AND published_at IS NOT NULL",
        (event_id,),
    ).fetchall()

    if not rows and event_title:
        words = [w for w in segment_text(event_title) if len(w) >= 2][:5]
        if words:
            conditions = " OR ".join(["title LIKE ?" for _ in words])
            params = [f"%{w}%" for w in words]
            rows = conn.execute(
                f"SELECT published_at FROM raw_news WHERE {conditions} AND published_at IS NOT NULL",
                params,
            ).fetchall()

    daily = defaultdict(int)
    for r in rows:
        date_str = dict(r).get("published_at", "")[:10]
        if date_str:
            daily[date_str] += 1

    return dict(sorted(daily.items()))


def _calc_trend(daily_counts: Dict[str, int]):
    """
    计算报道量增长斜率和加速度。
    使用最近3天的数据做线性回归斜率。
    """
    if len(daily_counts) < 2:
        return 0.0, 0.0

    dates = list(daily_counts.keys())
    counts = list(daily_counts.values())

    # 取最近3~7天
    recent = min(7, len(dates))
    x = list(range(recent))
    y = [counts[i] for i in range(len(dates) - recent, len(dates))]

    n = len(x)
    if n < 2:
        return 0.0, 0.0

    # 线性回归求斜率
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi ** 2 for xi in x)

    denominator = n * sum_x2 - sum_x ** 2
    if abs(denominator) < 1e-10:
        return 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denominator

    # 加速度（斜率变化）
    if n >= 3:
        y_diffs = [y[i] - y[i - 1] for i in range(1, n)]
        acceleration = (y_diffs[-1] - y_diffs[0]) / max(n - 2, 1)
    else:
        acceleration = 0.0

    return round(slope, 4), round(acceleration, 4)


def _predict_24h(slope: float, acceleration: float,
                  lifecycle: str, daily_counts: Dict) -> Dict:
    """预测未来24小时走势"""
    direction = "stable"
    description = ""

    if lifecycle == "peak":
        direction = "stable"
        description = "事件处于高潮期，预计未来24小时内热度维持高位震荡，单日报道量与近期持平。"
    elif lifecycle == "decline":
        direction = "down"
        desc_extra = "热度预计继续走低" if slope < -1 else "热度可能缓慢回落"
        description = f"事件已进入衰退期，{desc_extra}，新增报道量逐步减少。"
    elif lifecycle == "growth":
        if slope > 0.5:
            direction = "up"
            description = "事件处于成长期且报道量增速明显，预计未来24小时内热度将继续攀升。"
        elif slope > 0:
            direction = "up"
            description = "事件报道量呈温和增长态势，预计未来24小时热度小幅上涨。"
        else:
            direction = "stable"
            description = "事件成长期增速放缓，预计未来24小时热度趋于平稳。"
    else:  # latent
        direction = "stable"
        description = "事件尚处于潜伏期，报道量较低，后续发展需持续观察。"

    return {"direction": direction, "description": description}


def _predict_72h(slope: float, acceleration: float,
                  lifecycle: str, daily_counts: Dict) -> Dict:
    """预测未来72小时走势"""
    direction = "stable"
    description = ""

    recent_count = len(daily_counts)
    recent_avg = sum(daily_counts.values()) / max(recent_count, 1)

    if lifecycle == "peak":
        if slope < -0.5:
            direction = "down"
            description = "虽然处于高潮期，但增速已开始回落，预计72小时内热度将从峰值逐步下降。"
        else:
            direction = "stable"
            description = "事件处于高潮期，预计72小时内维持较高热度，随后可能进入衰退阶段。"
    elif lifecycle == "decline":
        direction = "down"
        description = "事件处于衰退期，预计72小时内热度将持续走低，除非出现新的重大进展。"
    elif lifecycle == "growth":
        if slope > 1.0 and acceleration > 0:
            direction = "up"
            description = "事件加速增长中，预计72小时内可能达到热度峰值，需密切监测。"
        elif slope > 0:
            direction = "up"
            description = "事件处于上升通道，预计72小时内热度将继续上涨，但增速可能放缓。"
        else:
            direction = "stable"
            description = "事件增速趋于平缓，预计72小时内热度进入平台期。"
    else:  # latent
        if slope > 0:
            direction = "up"
            description = "事件开始获得关注，若后续出现引爆性报道，72小时内可能快速升温。"
        else:
            direction = "stable"
            description = "事件关注度较低，72小时内维持现状，需关注是否有新的信息刺激。"

    return {"direction": direction, "description": description}


def _identify_variables(event, daily_counts: Dict) -> List[Dict]:
    """识别影响热度变动的潜在变量"""
    variables = []
    now = datetime.now()

    # 周末效应
    weekday = now.weekday()
    if weekday >= 4:  # 周五~周日
        variables.append({
            "factor": "周末效应",
            "impact": "用户活跃度增加，可能加速传播",
            "probability": "高",
        })

    # 生命周期阶段变量
    lifecycle = event.get("lifecycle", "")
    if lifecycle == "growth":
        variables.append({
            "factor": "成长期惯性",
            "impact": "事件处于上升期，自然关注增量",
            "probability": "高",
        })
    elif lifecycle == "peak":
        variables.append({
            "factor": "高潮期饱和",
            "impact": "话题已被广泛报道，增量空间有限",
            "probability": "中",
        })

    # 高热度值变量
    heat = event.get("heat_score", 0)
    if heat > 70:
        variables.append({
            "factor": "高热度惯性",
            "impact": "热度分数较高，容易维持公众关注",
            "probability": "中",
        })

    # 传播节点数量变量
    conn = get_connection()
    try:
        spread = conn.execute(
            "SELECT spread_depth, total_reposts FROM spread_info WHERE event_id = ?",
            (event["id"],),
        ).fetchone()
        if spread:
            if spread["total_reposts"] > 100:
                variables.append({
                    "factor": "高转发量",
                    "impact": "已形成较大传播规模，可能引发二次传播",
                    "probability": "中",
                })
            if spread["spread_depth"] >= 3:
                variables.append({
                    "factor": "深层传播网络",
                    "impact": "传播链较长，次级传播可能带来新的关注群体",
                    "probability": "中",
                })
    finally:
        conn.close()

    # 负面情绪变量
    risk = event.get("risk_level", "")
    if risk in ("high", "critical"):
        variables.append({
            "factor": "高风险事件",
            "impact": "负面事件容易引发持续讨论和二次舆情",
            "probability": "高",
        })

    return variables


def _calc_confidence(data_points: int, slope: float, lifecycle: str) -> float:
    """计算预判置信度"""
    # 数据点越多置信度越高
    data_conf = min(1.0, data_points * 0.15 + 0.2)

    # 斜率越明显置信度越高
    slope_conf = min(1.0, abs(slope) * 0.2 + 0.4)

    # 生命周期明确的阶段置信度更高
    lifecycle_conf = {"peak": 0.8, "decline": 0.8, "growth": 0.6, "latent": 0.4}
    lc_conf = lifecycle_conf.get(lifecycle, 0.5)

    return round(min(0.95, (data_conf + slope_conf + lc_conf) / 3), 2)


def _generate_summary(title, lifecycle, heat_score, trend,
                       pred_24h, pred_72h, variables) -> str:
    """生成通俗预判结论"""
    lifecycle_map = {
        "latent": "潜伏期", "growth": "成长期",
        "peak": "高潮期", "decline": "衰退期",
    }
    lc_name = lifecycle_map.get(lifecycle, lifecycle)

    trend_map = {"上涨": "持续升温", "回落": "逐步降温", "平稳": "维持平稳", "震荡": "波动变化"}

    lines = [
        f"「{title[:30]}」当前处于{lc_name}，热度评分{heat_score:.0f}/100。",
        f"预计未来24小时热度{pred_24h['description'][:30]}，72小时{pred_72h['direction']}。",
    ]

    if variables:
        top_factors = [v["factor"] for v in variables[:3]]
        lines.append(f"主要影响因素：{', '.join(top_factors)}。")

    return " ".join(lines)
