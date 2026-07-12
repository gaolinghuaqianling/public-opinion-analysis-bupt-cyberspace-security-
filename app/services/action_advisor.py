# -*- coding: utf-8 -*-
"""
================================================================================
  轻量化处置建议输出模块 (action_advisor.py)
================================================================================
整合文本真伪置信结果、传播链路、情绪、热度分析的全部结论，
自动输出适配普通用户/运营方的参考举措。

输出内容:
  1. 辟谣话术参考（针对低置信度事件）
  2. 重点监测节点清单（基于传播链路）
  3. 规避次生谣言的小贴士
  4. 面向运营方的专业建议

复用已有数据:
  - fake_detector → credibility_score, fake_flags
  - spread_analyzer → 传播节点、graph_data
  - emotion_analyzer → 情绪占比、激化节点
  - heat_predictor → 热度趋势预判
  - event_analysis → 情感分析、关键词

输出结构:
  {
    "public_advice": [...],      // 面向普通用户的建议
    "operation_advice": [...],   // 面向运营方的建议
    "rumor_refute": str|null,    // 辟谣话术参考
    "monitor_nodes": [...],      // 重点监测节点
    "risk_tips": [...]          // 规避次生谣言贴士
  }
================================================================================
"""

import logging
from typing import List, Dict, Optional
from app.core.database import get_connection

logger = logging.getLogger("services.action_advisor")


def generate_action_advice(event_id: int) -> Dict:
    """
    为指定事件生成轻量化处置建议。

    参数:
        event_id: 事件 ID

    返回:
        处置建议结果字典
    """
    conn = get_connection()
    try:
        event = conn.execute(
            "SELECT * FROM hot_event WHERE id = ?", (event_id,)
        ).fetchone()
        if event is None:
            return None
        event = dict(event)  # 转为 dict 以支持 .get() 方法

        # 收集各类分析数据
        credibility = _get_credibility(conn, event_id)
        spread = _get_spread_info(conn, event_id)
        emotion = _get_emotion_info(conn, event_id)
        heat = _get_heat_info(conn, event_id)
        analysis = _get_analysis_info(conn, event_id)

        # 生成建议
        public_advice = _gen_public_advice(event, credibility, emotion, heat)
        operation_advice = _gen_operation_advice(event, credibility, spread, emotion, heat)
        rumor_refute = _gen_rumor_refute(event, credibility)
        monitor_nodes = _gen_monitor_nodes(spread)
        risk_tips = _gen_risk_tips(event, credibility, emotion, spread)

        result = {
            "event_id": event_id,
            "event_title": event["title"],
            "public_advice": public_advice,
            "operation_advice": operation_advice,
            "rumor_refute": rumor_refute,
            "monitor_nodes": monitor_nodes,
            "risk_tips": risk_tips,
        }

        logger.info("事件 %d 处置建议生成完成: 公众建议%d条, 运营建议%d条",
                     event_id, len(public_advice), len(operation_advice))

        return result

    except Exception as e:
        logger.error("处置建议生成失败: event_id=%d, %s", event_id, e)
        return None
    finally:
        conn.close()


def _get_credibility(conn, event_id: int) -> Dict:
    """获取可信度数据"""
    row = conn.execute(
        "SELECT credibility_score, fake_flags FROM event_analysis WHERE event_id = ? "
        "ORDER BY analyzed_at DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    if row:
        import json
        r = dict(row)
        return {
            "score": r.get("credibility_score") or 0,
            "fake_flags": json.loads(r.get("fake_flags") or "[]"),
        }
    return {"score": 0, "fake_flags": []}


def _get_spread_info(conn, event_id: int) -> Optional[Dict]:
    """获取传播链路数据"""
    import json
    row = conn.execute(
        "SELECT * FROM spread_info WHERE event_id = ? ORDER BY traced_at DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    if row:
        data = dict(row)
        try:
            data["graph_data"] = json.loads(data.get("graph_data") or "{}")
            data["spread_nodes"] = json.loads(data.get("spread_nodes") or "[]")
        except (json.JSONDecodeError, TypeError):
            data["graph_data"] = {"nodes": [], "links": []}
            data["spread_nodes"] = []
        return data
    return None


def _get_emotion_info(conn, event_id: int) -> Optional[Dict]:
    """获取情绪分析数据（直接调用模块实时计算）"""
    try:
        from app.services.emotion_analyzer import analyze_event_emotion
        return analyze_event_emotion(event_id)
    except Exception:
        return None


def _get_heat_info(conn, event_id: int) -> Dict:
    """获取热度信息"""
    event = conn.execute(
        "SELECT heat_score, lifecycle, risk_level FROM hot_event WHERE id = ?",
        (event_id,),
    ).fetchone()
    if event:
        return {
            "heat_score": event["heat_score"],
            "lifecycle": event["lifecycle"],
            "risk_level": event["risk_level"],
        }
    return {"heat_score": 0, "lifecycle": "latent", "risk_level": "low"}


def _get_analysis_info(conn, event_id: int) -> Optional[Dict]:
    """获取事件分析数据"""
    import json
    row = conn.execute(
        "SELECT positive_ratio, negative_ratio, neutral_ratio, high_freq_keywords "
        "FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    if row:
        r = dict(row)
        return {
            "positive": r["positive_ratio"],
            "negative": r["negative_ratio"],
            "neutral": r["neutral_ratio"],
            "keywords": json.loads(r.get("high_freq_keywords") or "[]"),
        }
    return None


def _gen_public_advice(event, credibility, emotion, heat) -> List[Dict]:
    """面向普通用户的建议"""
    advice_list = []

    # 基于可信度的建议
    if credibility["score"] < 0.4:
        advice_list.append({
            "type": "credibility",
            "icon": "warning",
            "title": "信息可信度较低",
            "content": "该事件相关报道的可信度评分较低，建议等待官方媒体确认后再做判断，切勿轻信转发。",
        })
    elif credibility["score"] < 0.7:
        advice_list.append({
            "type": "credibility",
            "icon": "info",
            "title": "信息有待验证",
            "content": "该事件部分报道存在不确定因素，建议多方核实后再形成观点。",
        })

    # 基于热度的建议
    if heat["lifecycle"] == "growth":
        advice_list.append({
            "type": "heat",
            "icon": "trending",
            "title": "事件正在升温",
            "content": "该事件关注度持续上升，建议关注权威渠道的后续报道，避免被片面信息误导。",
        })
    elif heat["lifecycle"] == "peak":
        advice_list.append({
            "type": "heat",
            "icon": "fire",
            "title": "事件热度较高",
            "content": "该事件当前讨论热度很高，请注意辨别信息真伪，理性参与讨论。",
        })

    # 基于情绪的建议
    if emotion and isinstance(emotion, dict):
        neg_ratio = emotion.get("emotion_ratios", {}).get("负面", 0)
        if neg_ratio > 0.4:
            advice_list.append({
                "type": "emotion",
                "icon": "emotion",
                "title": "负面情绪较多",
                "content": "当前舆论以负面情绪为主，建议保持冷静客观，避免被情绪化内容影响判断。",
            })

    # 基于风险等级
    if heat["risk_level"] in ("high", "critical"):
        advice_list.append({
            "type": "risk",
            "icon": "alert",
            "title": "高风险事件",
            "content": "该事件被评估为高风险舆情，相关信息可能引发社会恐慌，请以官方发布为准。",
        })

    return advice_list


def _gen_operation_advice(event, credibility, spread, emotion, heat) -> List[Dict]:
    """面向运营方的建议"""
    advice_list = []

    # 监测建议
    advice_list.append({
        "type": "monitor",
        "icon": "eye",
        "title": "持续监测传播动态",
        "content": f"建议对该事件保持每2小时一次的监测频率，重点关注微博、抖音等社媒平台的二次传播情况。",
    })

    # 基于可信度的运营建议
    if credibility["score"] < 0.5:
        advice_list.append({
            "type": "fact_check",
            "icon": "search",
            "title": "启动事实核查",
            "content": "事件可信度偏低，建议立即启动事实核查流程，联系信源方核实信息真实性，准备辟谣预案。",
        })
        if credibility["fake_flags"]:
            flags = credibility["fake_flags"][:3]
            advice_list.append({
                "type": "flag_analysis",
                "icon": "flag",
                "title": "虚假特征分析",
                "content": f"检测到的风险标记：{', '.join(flags)}。建议重点排查信息源头，追溯首次发布账号的发布动机。",
            })

    # 基于热度的运营建议
    if heat["lifecycle"] == "growth":
        advice_list.append({
            "type": "escalation",
            "icon": "bell",
            "title": "预警升级准备",
            "content": "事件处于上升期，建议提升舆情预警等级，准备应急回应方案，必要时安排专人值守。",
        })

    # 基于情绪的运营建议
    if emotion and isinstance(emotion, dict):
        agitated = emotion.get("agitated_nodes", [])
        if agitated:
            advice_list.append({
                "type": "emotion_mgmt",
                "icon": "shield",
                "title": "情绪引导策略",
                "content": f"检测到{len(agitated)}个情绪激化节点，建议通过发布权威信息、平衡报道视角等方式引导舆论情绪降温。",
            })

    # 基于传播的运营建议
    if spread:
        depth = spread.get("spread_depth", 0)
        if depth >= 3:
            advice_list.append({
                "type": "spread_control",
                "icon": "network",
                "title": "传播链管控",
                "content": f"事件传播深度已达{depth}层，覆盖面较广。建议关注核心放大节点，必要时通过官方渠道发布权威信息。",
            })

    # 高风险运营建议
    if heat["risk_level"] in ("high", "critical"):
        advice_list.append({
            "type": "crisis",
            "icon": "emergency",
            "title": "危机应对准备",
            "content": "事件风险等级较高，建议启动危机应对预案，协调多部门联动，准备好对外口径和回应声明。",
        })

    return advice_list


def _gen_rumor_refute(event, credibility) -> Optional[str]:
    """生成辟谣话术参考"""
    score = credibility["score"]
    flags = credibility["fake_flags"]
    title = event["title"]

    if score >= 0.7:
        return None  # 高可信度无需辟谣

    # 低可信度时生成辟谣话术
    parts = []

    if flags:
        parts.append(f"网传「{title[:25]}」相关信息中，存在" + "、".join(flags[:3]) + "等特征表述。")

    if score < 0.4:
        parts.append("经系统多维度检测，该信息可信度较低，请以官方权威渠道发布的信息为准。")
    else:
        parts.append("该信息部分内容有待进一步核实，建议关注官方媒体的后续报道。")

    parts.append("不信谣、不传谣，一切以权威部门发布的信息为准。")

    return "".join(parts)


def _gen_monitor_nodes(spread) -> List[Dict]:
    """生成重点监测节点清单"""
    if not spread:
        return []

    nodes = spread.get("spread_nodes", [])
    if not nodes:
        # 从 graph_data 提取
        graph = spread.get("graph_data", {})
        nodes = graph.get("nodes", [])

    monitor_list = []
    priority_nodes = ["首发来源", "核心放大", "官方回应"]

    for node in nodes:
        category = ""
        if isinstance(node, dict):
            category = node.get("category_name", node.get("name", "")[:10])
            name = node.get("name", "")
            platform = node.get("platform", "")
        else:
            name = str(node)[:25]
            platform = ""
            category = ""

        if category in priority_nodes:
            priority = "高" if category == "核心放大" else "中"
            monitor_list.append({
                "node_name": name,
                "platform": platform,
                "role": category,
                "priority": priority,
                "reason": f"作为{category}节点，对事件传播有重要影响",
            })

    return monitor_list[:5]


def _gen_risk_tips(event, credibility, emotion, spread) -> List[str]:
    """生成规避次生谣言的小贴士"""
    tips = []

    tips.append(
        "关注信源权威性：优先采信官方媒体和政府发布的信息，对自媒体爆料保持审慎态度。"
    )

    if credibility["score"] < 0.6:
        tips.append(
            "警惕断章取义：部分不实信息可能截取真实事件的片段进行误导性解读，建议查阅完整报道。"
        )

    if emotion and isinstance(emotion, dict):
        neg_ratio = emotion.get("emotion_ratios", {}).get("负面", 0)
        if neg_ratio > 0.3:
            tips.append(
                "防止情绪传染：负面舆情容易引发群体性恐慌或愤怒，建议在情绪高峰期减少非必要的信息传播。"
            )

    if spread and spread.get("spread_depth", 0) >= 3:
        tips.append(
            "注意信息衰减：传播层级越深，信息失真概率越高。重要事件应以最初信源为核查依据。"
        )

    tips.append(
        "交叉验证原则：对任何敏感信息，至少通过两个独立权威来源进行交叉验证后再采信。"
    )

    return tips
