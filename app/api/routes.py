# -*- coding: utf-8 -*-
"""
================================================================================
  网络舆情智能分析系统 — 完整路由接口 (routes.py)
================================================================================
对接前端 Vue 的完整 API 路由集合，包含：
  1. 用户登录（支持 MD5 加密校验）+ Token 签发
  2. 热点事件看板（分页、排序、筛选）
  3. 事件完整分析数据（情感/关键词/平台覆盖/传播溯源/关联新闻）
  4. 智能问答（调用豆包大模型 API，基于事件数据生成回答）
  5. 个人中心（读取/修改用户关注平台、关键词）

所有接口统一返回格式: {"code": 200, "message": "...", "data": {...}}
跨域 CORS 已在 main.py 中全局配置，适配前端 Vue axios 请求。
================================================================================
"""

import json
import hashlib
import logging
from typing import List, Dict, Optional

import jieba

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field

from app.core.database import get_connection
from app.core.auth import create_access_token, decode_access_token, verify_password
from app.schemas.schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["完整路由接口"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/routes/login")


# -----------------------------------------------------------------------
# 依赖注入：从 Token 解析当前用户
# -----------------------------------------------------------------------
def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """从 JWT Token 解析并验证当前登录用户"""
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token无效或已过期，请重新登录")
    user_id = payload.get("sub")
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="用户不存在")
        return dict(row)
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 1. 用户登录接口（MD5 加密校验）
# -----------------------------------------------------------------------
@router.post("/routes/login", response_model=ApiResponse)
def login(username: str, password: str, pwd_md5: bool = False):
    """
    用户登录接口。
    
    - pwd_md5=False (默认): 密码为明文，服务端 bcrypt 校验
    - pwd_md5=True:  密码为前端 MD5 hash（32位hex），服务端再次 MD5 后 bcrypt 校验
      前端流程: MD5(用户输入) → 发送到后端 → 后端 MD5(接收值) → bcrypt 对比数据库
      
    返回 JWT Token + 用户基本信息
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM user WHERE username = ?", (username,)).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        db_pwd_hash = row["password_hash"]

        # ---- MD5 模式：前端传来的已经是 MD5 值，服务端再 MD5 后与 bcrypt 对比 ----
        if pwd_md5:
            # 双重 MD5：前端MD5 → 后端再MD5 → 与数据库 bcrypt hash 比较
            # 这样数据库存的是 bcrypt(MD5(明文))，传输的是 MD5(明文)
            # 后端验证: bcrypt.checkpw(MD5(MD5(明文)), db_hash)
            double_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
            if not verify_password(double_md5, db_pwd_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")
        else:
            # 明文模式：直接 bcrypt 校验
            if not verify_password(password, db_pwd_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

        # 签发 JWT Token
        token = create_access_token(data={"sub": str(row["id"])})

        return ApiResponse(data={
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": row["id"],
                "username": row["username"],
                "focus_platforms": json.loads(row["focus_platforms"]),
                "focus_keywords": json.loads(row["focus_keywords"]),
                "created_at": row["created_at"],
            },
        })
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 2. 热点事件看板接口（分页 + 排序 + 筛选）
# -----------------------------------------------------------------------
@router.get("/routes/dashboard", response_model=ApiResponse)
def dashboard(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    sort_by: str = Query("heat", description="排序方式: heat=按热度, time=按时间"),
    order: str = Query("desc", description="排序方向: desc=降序, asc=升序"),
    risk_level: Optional[str] = Query(None, description="风险等级筛选: low/medium/high/critical"),
    lifecycle: Optional[str] = Query(None, description="生命周期筛选: latent/growth/peak/decline"),
    keyword: Optional[str] = Query(None, description="关键词搜索（标题模糊匹配）"),
    _user: dict = Depends(get_current_user),
):
    """
    热点事件看板接口。
    支持按热度/时间排序、风险等级/生命周期筛选、关键词搜索。
    返回分页数据 + 每个事件的最新情感摘要。
    """
    conn = get_connection()
    try:
        # ---- 读取当前用户的关注配置 ----
        user_focus_platforms = json.loads(_user.get("focus_platforms") or "[]")
        user_focus_keywords = json.loads(_user.get("focus_keywords") or "[]")
        has_focus_config = bool(user_focus_platforms) or bool(user_focus_keywords)

        conditions, params = [], []

        # 筛选条件
        if risk_level:
            conditions.append("he.risk_level = ?")
            params.append(risk_level)
        if lifecycle:
            conditions.append("he.lifecycle = ?")
            params.append(lifecycle)
        if keyword:
            conditions.append("he.title LIKE ?")
            params.append(f"%{keyword}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 动态排序：防止 SQL 注入，只允许白名单字段
        allowed_sort_fields = {
            "heat": "he.heat_score",
            "time": "he.created_at",
        }
        sort_column = allowed_sort_fields.get(sort_by, "he.heat_score")
        sort_direction = "DESC" if order.lower() == "desc" else "ASC"
        order_clause = f"ORDER BY {sort_column} {sort_direction}"

        # 总数
        total = conn.execute(f"SELECT COUNT(*) FROM hot_event he {where}", params).fetchone()[0]

        # 分页查询事件
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT he.* FROM hot_event he {where} {order_clause} LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()

        # 为每个事件附带最新的情感分析摘要
        items = []
        for r in rows:
            event = dict(r)
            # 查询最新分析
            analysis = conn.execute(
                "SELECT positive_ratio, negative_ratio, neutral_ratio, high_freq_keywords "
                "FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
                (event["id"],)
            ).fetchone()

            event["sentiment"] = None
            if analysis:
                event["sentiment"] = {
                    "positive_ratio": analysis["positive_ratio"],
                    "negative_ratio": analysis["negative_ratio"],
                    "neutral_ratio": analysis["neutral_ratio"],
                    "top_keywords": json.loads(analysis["high_freq_keywords"])[:5],
                }

            # 计算事件与用户关注内容的匹配度
            event["is_focus_hit"] = False
            event["match_score"] = 0
            if has_focus_config:
                title = event.get("title", "")
                matched_keywords = [kw for kw in user_focus_keywords if kw in title]
                if matched_keywords:
                    event["is_focus_hit"] = True
                    event["match_score"] = len(matched_keywords) * 10

                # 查询关联新闻的平台匹配
                if user_focus_platforms:
                    kw_for_match = [w for w in jieba.cut(title) if len(w.strip()) >= 2][:5]
                    if kw_for_match:
                        like_conditions = " OR ".join(["title LIKE ?" for _ in kw_for_match])
                        platform_rows = conn.execute(
                            f"SELECT source_platform FROM raw_news WHERE {like_conditions} LIMIT 10",
                            [f"%{kw}%" for kw in kw_for_match]
                        ).fetchall()
                        for pr in platform_rows:
                            for fp in user_focus_platforms:
                                if fp in pr["source_platform"]:
                                    event["match_score"] += 5
                                    event["is_focus_hit"] = True
                                    break

            items.append(event)

        # 如果有关注配置，将匹配事件标记提升（不改变主排序顺序，只做同分优先）
        # 注意：数据库已按用户选择的字段排序，此处仅对匹配事件做标记展示

        return ApiResponse(data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
            "items": items,
            "has_focus_config": has_focus_config,
            "total_news": conn.execute("SELECT COUNT(*) FROM raw_news").fetchone()[0],
            "high_risk_count": conn.execute("SELECT COUNT(*) FROM hot_event WHERE risk_level IN ('high','critical')").fetchone()[0],
        })
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 3. 事件完整分析数据接口
# -----------------------------------------------------------------------
@router.get("/routes/event/{event_id}/full", response_model=ApiResponse)
def event_full_analysis(event_id: int, _user: dict = Depends(get_current_user)):
    """
    根据事件 ID 查询完整分析数据。
    返回: 事件基本信息 + 情感分析 + 关键词 + 平台覆盖 + 传播溯源 + 关联新闻列表
    """
    conn = get_connection()
    try:
        # 1. 事件基本信息
        event = conn.execute("SELECT * FROM hot_event WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="事件不存在")

        result = {
            "event": dict(event),
            "analysis": None,
            "spread": None,
            "related_news": [],
            "emotion": None,
            "heat_prediction": None,
            "action_advice": None,
        }

        # 2. 情感分析详情
        analysis = conn.execute(
            "SELECT * FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if analysis:
            a = dict(analysis)
            a["high_freq_keywords"] = json.loads(a["high_freq_keywords"])
            a["platform_coverage"] = json.loads(a["platform_coverage"])
            a["fake_flags"] = json.loads(a.get("fake_flags") or "[]")
            result["analysis"] = a

        # 3. 传播溯源
        spread = conn.execute(
            "SELECT * FROM spread_info WHERE event_id = ? ORDER BY traced_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if spread:
            s = dict(spread)
            s["spread_nodes"] = json.loads(s["spread_nodes"])
            # 解析ECharts关系图数据
            raw_graph = s.get("graph_data", "{}")
            try:
                s["graph_data"] = json.loads(raw_graph) if isinstance(raw_graph, str) else raw_graph
            except (json.JSONDecodeError, TypeError):
                s["graph_data"] = {"nodes": [], "links": []}
            result["spread"] = s

        # 4. 关联新闻（从 raw_news 中按标题关键词匹配）
        title = event["title"]
        # 使用jieba分词提取标题关键词进行模糊匹配
        keywords = [w for w in jieba.cut(title) if len(w.strip()) >= 2][:5]
        if keywords:
            like_conditions = " OR ".join(["rn.title LIKE ?" for _ in keywords])
            news_rows = conn.execute(
                f"SELECT id, title, source_platform, published_at, original_url "
                f"FROM raw_news rn WHERE {like_conditions} "
                f"ORDER BY published_at DESC LIMIT 20",
                [f"%{kw}%" for kw in keywords]
            ).fetchall()
            result["related_news"] = [dict(r) for r in news_rows]

        # 5. 情绪量化分析
        try:
            from app.services.emotion_analyzer import analyze_event_emotion
            result["emotion"] = analyze_event_emotion(event_id)
        except Exception:
            pass

        # 6. 热度走势预判
        try:
            from app.services.heat_predictor import predict_heat_trend
            result["heat_prediction"] = predict_heat_trend(event_id)
        except Exception:
            pass

        # 7. 处置建议
        try:
            from app.services.action_advisor import generate_action_advice
            result["action_advice"] = generate_action_advice(event_id)
        except Exception:
            pass

        return ApiResponse(data=result)
    finally:
        conn.close()


# -----------------------------------------------------------------------
# 4. 智能问答接口（调用 DeepSeek 大模型 API）
# -----------------------------------------------------------------------
# DeepSeek API 配置（兼容 OpenAI 格式）
DOUBAO_API_URL = "https://api.deepseek.com/chat/completions"
DOUBAO_MODEL = "deepseek-chat"
DOUBAO_API_KEY = "sk-b8283a42acad460d8114f75e6ec10cc9"


class QARequest(BaseModel):
    """智能问答请求体"""
    event_id: int = Field(..., description="事件ID")
    question: str = Field(..., min_length=1, description="用户提问")


def _build_context_prompt(event_data: dict) -> str:
    """
    根据事件数据构建给大模型的上下文提示词。
    将事件信息、情感分析、关键词、平台覆盖、传播溯源组装为结构化文本。
    """
    lines = []

    # 事件基本信息
    event = event_data.get("event", {})
    lines.append(f"【事件标题】{event.get('title', '')}")
    lines.append(f"【热度分数】{event.get('heat_score', 0)}")
    lines.append(f"【风险等级】{event.get('risk_level', '')}")
    lines.append(f"【生命周期】{event.get('lifecycle', '')}")
    lines.append(f"【事件概述】{event.get('summary', '')}")
    lines.append(f"【创建时间】{event.get('created_at', '')}")

    # 情感分析
    analysis = event_data.get("analysis")
    if analysis:
        lines.append(f"【正面情感占比】{analysis.get('positive_ratio', 0) * 100:.1f}%")
        lines.append(f"【负面情感占比】{analysis.get('negative_ratio', 0) * 100:.1f}%")
        lines.append(f"【中性情感占比】{analysis.get('neutral_ratio', 0) * 100:.1f}%")
        keywords = analysis.get("high_freq_keywords", [])
        lines.append(f"【高频关键词】{', '.join(keywords[:15])}")
        platform = analysis.get("platform_coverage", {})
        if platform:
            platform_str = "、".join([f"{k} {v}%" for k, v in platform.items()])
            lines.append(f"【平台报道占比】{platform_str}")

    # 传播溯源
    spread = event_data.get("spread")
    if spread:
        lines.append(f"【首发平台】{spread.get('origin_platform', '')}")
        lines.append(f"【传播深度】{spread.get('spread_depth', 0)}层")
        lines.append(f"【转发总量】{spread.get('total_reposts', 0)}")
        lines.append(f"【阅读总量】{spread.get('total_reads', 0)}")

    # 关联新闻标题
    related = event_data.get("related_news", [])
    if related:
        news_titles = [n["title"] for n in related[:10]]
        lines.append(f"【相关报道标题】{' | '.join(news_titles)}")

    return "\n".join(lines)


async def _call_doubao_api(prompt: str, context: str) -> str:
    """
    调用 DeepSeek 大模型 API（兼容 OpenAI 格式）。

    参数:
        prompt: 用户提问
        context: 事件上下文信息

    返回:
        大模型回答文本
    """
    import httpx

    # 从环境变量读取 API Key（优先级高于硬编码）
    import os
    api_key = os.environ.get("DOUBAO_API_KEY", DOUBAO_API_KEY)
    model_id = os.environ.get("DOUBAO_MODEL", DOUBAO_MODEL)

    if not api_key:
        return (
            "【系统提示】大模型 API Key 未配置。\n"
            "请在 .env 文件中设置 DOUBAO_API_KEY，或在代码中填写 DOUBAO_API_KEY 变量。"
        )

    system_msg = (
        "你是一位专业的网络舆情分析专家。基于系统提供的舆情事件数据，"
        "回答用户的问题。回答应专业、客观、有条理，善用数据支撑观点。"
        "如果问题超出提供的数据范围，可以基于常识进行合理推断，但需说明。"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"以下是舆情事件数据：\n\n{context}\n\n用户问题：{prompt}"},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(DOUBAO_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        return "【系统提示】请求大模型 API 超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        return f"【系统提示】大模型 API 返回错误: {e.response.status_code}"
    except Exception as e:
        return f"【系统提示】调用大模型 API 异常: {str(e)}"


@router.post("/routes/qa", response_model=ApiResponse)
async def intelligent_qa(
    qa: QARequest,
    _user: dict = Depends(get_current_user),
):
    """
    智能问答接口。
    接收事件 ID + 用户提问，自动提取事件数据作为上下文，
    调用豆包大模型 API 生成专业回答。
    
    请求体（JSON）:
      - event_id: 事件ID
      - question: 用户提问文本
    
    返回: 大模型回答
    """
    event_id = qa.event_id
    question = qa.question

    # 从数据库加载事件完整数据
    conn = get_connection()
    try:
        event = conn.execute("SELECT * FROM hot_event WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="事件不存在")

        event_data = {"event": dict(event), "analysis": None, "spread": None, "related_news": []}

        analysis = conn.execute(
            "SELECT * FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if analysis:
            a = dict(analysis)
            a["high_freq_keywords"] = json.loads(a["high_freq_keywords"])
            a["platform_coverage"] = json.loads(a["platform_coverage"])
            event_data["analysis"] = a

        spread = conn.execute(
            "SELECT * FROM spread_info WHERE event_id = ? ORDER BY traced_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if spread:
            s = dict(spread)
            s["spread_nodes"] = json.loads(s["spread_nodes"])
            event_data["spread"] = s

        # 关联新闻（关键词匹配）
        title = event["title"]
        keywords = [w.strip() for w in title[:20] if len(w.strip()) >= 2][:5]
        keyword_news_ids = set()
        if keywords:
            like_conditions = " OR ".join(["title LIKE ?" for _ in keywords])
            news_rows = conn.execute(
                f"SELECT id, title, source_platform, published_at FROM raw_news "
                f"WHERE {like_conditions} ORDER BY published_at DESC LIMIT 10",
                [f"%{kw}%" for kw in keywords]
            ).fetchall()
            event_data["related_news"] = [dict(r) for r in news_rows]
            keyword_news_ids = {r["id"] for r in news_rows}

        # ---- 语义搜索分支：尝试用语义模型补充检索相关新闻 ----
        try:
            from app.services.nlp_tools import find_similar_texts, _load_semantic_model
            semantic_model = _load_semantic_model()

            if semantic_model is not None:
                # 获取所有新闻标题用于语义匹配
                all_news_rows = conn.execute(
                    "SELECT id, title, source_platform, published_at FROM raw_news "
                    "WHERE title IS NOT NULL AND length(title) >= 2 "
                    "ORDER BY published_at DESC LIMIT 200"
                ).fetchall()

                if all_news_rows:
                    all_news_titles = [r["title"] for r in all_news_rows]
                    semantic_results = find_similar_texts(
                        question.strip(), all_news_titles, topk=10, threshold=0.5
                    )

                    # 将语义搜索结果与关键词搜索结果合并（去重）
                    if semantic_results:
                        existing_ids = set(keyword_news_ids)
                        for sr in semantic_results:
                            news_row = all_news_rows[sr["index"]]
                            if news_row["id"] not in existing_ids:
                                event_data["related_news"].append({
                                    "id": news_row["id"],
                                    "title": news_row["title"],
                                    "source_platform": news_row["source_platform"],
                                    "published_at": news_row["published_at"],
                                    "_match_method": "semantic",
                                    "_semantic_score": sr["score"],
                                })
                                existing_ids.add(news_row["id"])

                        # 按发布时间重新排序，保留最新条目
                        event_data["related_news"].sort(
                            key=lambda x: x.get("published_at", ""), reverse=True
                        )
                        # 限制总数不超过 20 条
                        event_data["related_news"] = event_data["related_news"][:20]

                        logger.info(
                            "QA 语义搜索补充: 用户问题='%s', 语义命中 %d 条, 合并后共 %d 条",
                            question[:30], len(semantic_results),
                            len(event_data["related_news"]),
                        )
        except Exception as e:
            logger.debug("QA 语义搜索分支异常（不影响原有逻辑）: %s", e)
    finally:
        conn.close()

    # 构建上下文并调用大模型
    context = _build_context_prompt(event_data)
    answer = await _call_doubao_api(question.strip(), context)

    return ApiResponse(data={
        "event_id": event_id,
        "question": question.strip(),
        "answer": answer,
    })


# -----------------------------------------------------------------------
# 5. 个人中心接口
# -----------------------------------------------------------------------
@router.get("/routes/profile", response_model=ApiResponse)
def get_profile(_user: dict = Depends(get_current_user)):
    """
    读取个人中心信息。
    返回用户基本信息 + 关注平台 + 关注关键词 + 统计数据。
    """
    conn = get_connection()
    try:
        user_id = _user["id"]

        # 基本信息
        profile = {
            "id": _user["id"],
            "username": _user["username"],
            "focus_platforms": json.loads(_user["focus_platforms"]),
            "focus_keywords": json.loads(_user["focus_keywords"]),
            "created_at": _user["created_at"],
        }

        # 统计数据：关注的新闻数、事件数
        platforms = json.loads(_user["focus_platforms"])
        keywords = json.loads(_user["focus_keywords"])

        news_total = 0
        event_total = conn.execute("SELECT COUNT(*) FROM hot_event").fetchone()[0]

        if platforms:
            placeholders = ",".join("?" * len(platforms))
            news_total = conn.execute(
                f"SELECT COUNT(*) FROM raw_news WHERE source_platform IN ({placeholders})",
                platforms
            ).fetchone()[0]

        # 关注关键词命中统计
        keyword_hits = {}
        for kw in keywords[:10]:
            count = conn.execute(
                "SELECT COUNT(*) FROM raw_news WHERE title LIKE ? OR content LIKE ?",
                (f"%{kw}%", f"%{kw}%")
            ).fetchone()[0]
            keyword_hits[kw] = count

        profile["stats"] = {
            "related_news_count": news_total,
            "total_events": event_total,
            "keyword_hits": keyword_hits,
        }

        return ApiResponse(data=profile)
    finally:
        conn.close()


class ProfileUpdateRequest:
    """个人中心更新请求（内联模型，避免修改 schemas.py）"""
    def __init__(self, focus_platforms: Optional[List[str]] = None,
                 focus_keywords: Optional[List[str]] = None):
        self.focus_platforms = focus_platforms or []
        self.focus_keywords = focus_keywords or []


@router.put("/routes/profile", response_model=ApiResponse)
def update_profile(
    focus_platforms: Optional[List[str]] = None,
    focus_keywords: Optional[List[str]] = None,
    background_tasks: BackgroundTasks = None,
    _user: dict = Depends(get_current_user),
):
    """
    修改个人中心信息。
    支持更新关注的平台列表和关键词列表。
    保存成功后，异步触发爬虫任务下发（通过 BackgroundTasks 不阻塞响应）。

    请求体（JSON）:
      - focus_platforms: 平台列表，如 ["微博", "抖音", "知乎"]
      - focus_keywords: 关键词列表，如 ["人工智能", "芯片"]
    """
    conn = get_connection()
    try:
        user_id = _user["id"]

        # 只更新传入的字段，未传入的保持原值
        current_platforms = json.loads(_user["focus_platforms"])
        current_keywords = json.loads(_user["focus_keywords"])

        new_platforms = json.dumps(focus_platforms, ensure_ascii=False) if focus_platforms is not None else json.dumps(current_platforms, ensure_ascii=False)
        new_keywords = json.dumps(focus_keywords, ensure_ascii=False) if focus_keywords is not None else json.dumps(current_keywords, ensure_ascii=False)

        conn.execute(
            "UPDATE user SET focus_platforms=?, focus_keywords=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (new_platforms, new_keywords, user_id)
        )
        conn.commit()

        # ---- 保存成功后，异步触发爬虫任务下发 ----
        # 将用户关注配置中的平台名和关键词解析出来，在后台创建爬虫任务
        if background_tasks:
            from app.api.crawler_api import _batch_dispatch_and_execute
            platform_names = json.loads(new_platforms)
            keyword_list = json.loads(new_keywords)
            if platform_names or keyword_list:
                background_tasks.add_task(
                    _batch_dispatch_and_execute, platform_names, keyword_list
                )

        return ApiResponse(data={
            "id": user_id,
            "focus_platforms": json.loads(new_platforms),
            "focus_keywords": json.loads(new_keywords),
        }, message="个人中心更新成功")
    finally:
        conn.close()
