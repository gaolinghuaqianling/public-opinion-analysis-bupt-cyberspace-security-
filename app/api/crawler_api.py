# -*- coding: utf-8 -*-
"""
爬虫任务管理API路由
提供爬虫任务下发、状态查询、监控统计等HTTP接口

接口清单:
  1. POST /api/crawler/dispatch          — 手动下发单个爬虫任务
  2. POST /api/crawler/dispatch_user_config — 根据用户关注配置批量下发任务
  3. GET  /api/crawler/tasks             — 查询任务列表（支持状态筛选）
  4. GET  /api/crawler/stats             — 获取爬虫运行统计
  5. GET  /api/crawler/platforms         — 获取支持的平台列表

鉴权: 除 /platforms 外均需要 JWT Token 登录鉴权
"""

import json
import uuid
import logging
from typing import List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field

from app.core.database import get_connection
from app.schemas.schemas import ApiResponse
from app.services.event_processor import process_new_news, create_event_analysis

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# 路由与鉴权配置
# -----------------------------------------------------------------------
router = APIRouter(prefix="/crawler", tags=["爬虫任务管理"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/routes/login")


def _get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    从 JWT Token 解析并验证当前登录用户。
    复用与 routes.py 相同的鉴权逻辑，避免循环导入。
    """
    from app.core.auth import decode_access_token

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
# 平台信息配置（平台标识 -> 中文名 + 支持的任务类型）
# -----------------------------------------------------------------------
# 与 crawler/adapters/__init__.py 中的 ADAPTER_REGISTRY 保持一致
PLATFORM_REGISTRY = {
    "weibo": {
        "name": "微博",
        "task_types": ["hotlist", "keyword", "account"],
    },
    "douyin": {
        "name": "抖音",
        "task_types": ["hotlist", "keyword", "account"],
    },
    "zhihu": {
        "name": "知乎",
        "task_types": ["hotlist", "keyword", "account"],
    },
    "xiaohongshu": {
        "name": "小红书",
        "task_types": ["hotlist", "keyword", "account"],
    },
    "bilibili": {
        "name": "B站",
        "task_types": ["hotlist", "keyword", "account"],
    },
    "people_rss": {
        "name": "人民网",
        "task_types": ["hotlist", "keyword"],
    },
}

# 中文名 -> 平台标识 的反向映射（用于从用户配置中解析平台标识）
PLATFORM_NAME_TO_KEY = {v["name"]: k for k, v in PLATFORM_REGISTRY.items()}


# -----------------------------------------------------------------------
# 请求体模型
# -----------------------------------------------------------------------
class DispatchRequest(BaseModel):
    """手动下发爬虫任务的请求体"""
    platform: str = Field(..., description="平台标识，如 weibo、douyin、zhihu 等")
    task_type: str = Field(..., description="任务类型: hotlist/keyword/account")
    target: str = Field(..., description="抓取目标（关键词/账号ID/热搜URL等）")
    keywords: Optional[List[str]] = Field(default=None, description="关键词过滤列表（可选）")


# -----------------------------------------------------------------------
# 内部工具函数：创建任务记录到数据库
# -----------------------------------------------------------------------
def _create_task_in_db(
    platform: str,
    task_type: str,
    target: str,
    keywords: Optional[List[str]] = None,
    priority: int = 0,
) -> str:
    """
    在 crawl_tasks 表中创建一条任务记录（同步操作）。

    参数:
        platform:  平台标识
        task_type: 任务类型 (hotlist/keyword/account)
        target:    抓取目标
        keywords:  关键词列表（可选）
        priority:  优先级（数值越大越优先）

    返回:
        任务 ID (task_id)
    """
    task_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO crawl_tasks "
            "(task_id, platform, task_type, target, keywords, priority, "
            " created_at, status, result_count, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'), 'pending', 0, '')",
            (
                task_id,
                platform,
                task_type,
                target,
                json.dumps(keywords or [], ensure_ascii=False),
                priority,
            ),
        )
        conn.commit()
        logger.info("任务已创建: [%s] %s - %s", task_id[:8], platform, target[:30])
    except Exception as e:
        logger.error("创建任务失败: %s", e)
    finally:
        conn.close()

    return task_id


def _promote_to_hot_events(platform: str) -> int:
    """
    将 raw_news 中最近入库的记录自动升级为 hot_event，使数据出现在看板上。

    规则:
      1. 查找最近 60 秒内入库的 raw_news（避免重复升级历史数据）
      2. 按 title 去重（hot_event 中已存在相同标题则跳过）
      3. 计算 heat_score（基于文本长度 + 互动数据）
      4. 写入 hot_event 表

    参数:
        platform: 平台名称（用于日志标识）

    返回:
        新升级的事件数量
    """
    import datetime

    conn = get_connection()
    try:
        # 查找最近 60 秒内入库的 raw_news
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        one_min_ago = (datetime.datetime.now() - datetime.timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")

        rows = conn.execute(
            "SELECT title, content, source_platform, published_at "
            "FROM raw_news WHERE crawled_at >= ? AND crawled_at <= ?",
            (one_min_ago, now)
        ).fetchall()

        if not rows:
            return 0

        promoted = 0
        promoted_ids = []
        for row in rows:
            title = row["title"]
            if not title or len(title.strip()) < 2:
                continue

            # 去重：hot_event 中是否已存在相同标题
            exists = conn.execute(
                "SELECT 1 FROM hot_event WHERE title = ?", (title.strip(),)
            ).fetchone()
            if exists:
                continue

            # 计算 heat_score（0-100）
            content = row["content"] or ""
            heat = min(100, 30 + len(content) // 20)

            # 截取摘要（使用结构化信息提取）
            try:
                from app.services.event_summarizer import extract_structured_summary
                struct = extract_structured_summary(title.strip(), content)
                summary = struct["summary_text"]
            except Exception as e:
                logger.warning("结构化摘要提取失败，降级为截取: %s", e)
                summary = content[:200].strip() if content else ""

            # 使用新闻发布时间，如果没有则用当前时间
            created = row["published_at"] or now

            conn.execute(
                "INSERT INTO hot_event (title, heat_score, risk_level, summary, lifecycle, created_at, updated_at) "
                "VALUES (?, ?, 'low', ?, 'growth', ?, ?)",
                (title.strip(), float(heat), summary, created, now)
            )
            # 获取刚插入的事件 ID
            new_event = conn.execute(
                "SELECT id FROM hot_event WHERE title = ?", (title.strip(),)
            ).fetchone()
            if new_event:
                promoted_ids.append(new_event["id"])
            promoted += 1

        conn.commit()
        logger.info("[%s] 升级 %d 条 raw_news → hot_event", platform, promoted)

        # 对每个新创建的 hot_event 生成情感分析记录
        for eid in promoted_ids:
            try:
                create_event_analysis(eid)
                logger.info("已为新事件 #%d 创建情感分析记录", eid)
            except Exception as e:
                logger.warning("为事件 #%d 创建分析记录失败: %s", eid, e)

        return promoted

    except Exception as e:
        logger.error("升级为热点事件失败: %s", e)
        return 0
    finally:
        conn.close()


def _execute_crawl_task(task_id: str):
    """
    后台执行单个爬虫任务（由 FastAPI BackgroundTasks 调用）。

    流程:
        1. 从数据库读取任务详情
        2. 更新状态为 running
        3. 尝试调用对应平台适配器执行抓取
        4. 更新状态为 success/failed

    参数:
        task_id: 任务 ID
    """
    from crawler.storage import update_task, save_crawled_items
    from crawler.models import CrawlTask, CrawledItem
    from crawler.cleaners import cross_platform_normalize, validate_public_content

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM crawl_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            logger.warning("后台执行任务失败: 任务不存在 %s", task_id)
            return

        task = CrawlTask(
            task_id=row["task_id"],
            platform=row["platform"],
            task_type=row["task_type"],
            target=row["target"],
            keywords=json.loads(row["keywords"] or "[]"),
            priority=row["priority"],
            status=row["status"],
        )
    finally:
        conn.close()

    # 标记为运行中
    update_task(task_id, status="running")
    logger.info("开始执行任务: [%s] %s - %s", task_id[:8], task.platform, task.target[:30])

    try:
        # 尝试获取适配器并执行抓取
        import asyncio
        from crawler.adapters import get_adapter

        adapter = get_adapter(task.platform)

        # 根据任务类型调用适配器方法（适配器方法是 async 的，需要 asyncio.run）
        async def _run_adapter():
            return await adapter.execute_task(task)

        try:
            raw_items = asyncio.run(_run_adapter())
        except RuntimeError:
            # 如果已经在事件循环中，使用 nest_asyncio 或新建线程
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                raw_items = pool.submit(asyncio.run, _run_adapter()).result(timeout=60)
        except Exception as e:
            raw_items = []

        # 清洗和入库
        crawled_items = []
        for raw in raw_items:
            normalized = cross_platform_normalize(raw)
            if validate_public_content(normalized):
                crawled_items.append(normalized)

        saved_count = save_crawled_items(crawled_items) if crawled_items else 0

        # ---- 将新入库的 raw_news 自动升级为 hot_event ----
        promoted_count = _promote_to_hot_events(task.platform)
        if promoted_count > 0:
            logger.info("升级为热点事件: %d 条", promoted_count)

        # ---- 处理刚入库的 raw_news：分词 + 关键词提取 + 情感分析 ----
        try:
            analysis_stats = process_new_news(task.platform)
            if analysis_stats.get("processed", 0) > 0:
                logger.info(
                    "新闻分析完成: processed=%d, keywords=%d, sentiment=%d",
                    analysis_stats["processed"],
                    analysis_stats["keywords_extracted"],
                    analysis_stats["sentiment_scored"],
                )
        except Exception as e:
            logger.warning("process_new_news 调用失败: %s", e)

        # ---- 后续高级分析（热点发现/新闻关联/聚合/生命周期） ----
        try:
            from app.services.hotspot_detector import run_hotspot_detection
            hotspot_result = run_hotspot_detection(time_window_hours=24, min_news_count=3)
            logger.info("热点发现完成: 检测 %d, 升级 %d",
                        hotspot_result.get("detected", 0), hotspot_result.get("promoted", 0))
        except Exception as e:
            logger.warning("热点发现跳过: %s", e)

        try:
            from app.services.event_aggregator import link_news_to_events, aggregate_similar_events
            link_result = link_news_to_events()
            logger.info("新闻关联完成: 关联 %d", link_result.get("linked", 0))
            agg_result = aggregate_similar_events()
            logger.info("事件聚合完成: 发现 %d 组相似事件", agg_result.get("groups_found", 0))
        except Exception as e:
            logger.warning("事件聚合跳过: %s", e)

        try:
            from app.services.lifecycle_predictor import update_all_lifecycles
            lc_result = update_all_lifecycles()
            logger.info("生命周期更新完成: %s", lc_result)
        except Exception as e:
            logger.warning("生命周期更新跳过: %s", e)

        # ---- 虚假文本检测 ----
        try:
            import datetime
            one_min_ago_str = (datetime.datetime.now() - datetime.timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
            from app.services.fake_detector import detect_fake_text
            from app.services.spread_analyzer import analyze_spread_path
            # 对新入库的新闻进行虚假检测
            conn_local = get_connection()
            try:
                new_news = conn_local.execute(
                    "SELECT id, title, content, source_platform FROM raw_news WHERE crawled_at >= ?",
                    (one_min_ago_str,)
                ).fetchall()
            finally:
                conn_local.close()
            
            if new_news:
                # 批量检测并更新 credibility_score
                for news_item in new_news:
                    fake_result = detect_fake_text(
                        title=news_item["title"],
                        content=news_item["content"] or "",
                        source_platform=news_item["source_platform"],
                    )
                    # 更新 event_analysis 的 credibility_score 和 fake_flags
                    conn_local2 = get_connection()
                    try:
                        analysis = conn_local2.execute(
                            "SELECT id FROM event_analysis ORDER BY analyzed_at DESC LIMIT 1"
                        ).fetchone()
                        if analysis:
                            conn_local2.execute(
                                "UPDATE event_analysis SET credibility_score = ?, fake_flags = ? WHERE id = ?",
                                (fake_result["credibility_score"],
                                 json.dumps(fake_result["fake_flags"], ensure_ascii=False),
                                 analysis["id"])
                            )
                            conn_local2.commit()
                    finally:
                        conn_local2.close()
                logger.info("虚假文本检测完成: 检测 %d 条", len(new_news))
        except Exception as e:
            logger.warning("虚假文本检测跳过: %s", e)

        # ---- 传播路径分析（对新升级的事件） ----
        try:
            import datetime
            one_min_ago_str = (datetime.datetime.now() - datetime.timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
            from app.services.spread_analyzer import analyze_spread_path
            # 获取最近升级的事件
            conn_local3 = get_connection()
            try:
                recent_events = conn_local3.execute(
                    "SELECT id FROM hot_event WHERE created_at >= ? ORDER BY id DESC LIMIT 5",
                    (one_min_ago_str,)
                ).fetchall()
            finally:
                conn_local3.close()
            
            for evt in recent_events:
                analyze_spread_path(event_id=evt["id"])
            logger.info("传播路径分析完成: 分析 %d 个事件", len(recent_events))
        except Exception as e:
            logger.warning("传播路径分析跳过: %s", e)

        # ---- 情绪量化分析（对新升级的事件） ----
        try:
            from app.services.emotion_analyzer import analyze_event_emotion
            for evt in recent_events:
                analyze_event_emotion(event_id=evt["id"])
            logger.info("情绪量化分析完成: 分析 %d 个事件", len(recent_events))
        except Exception as e:
            logger.warning("情绪量化分析跳过: %s", e)

        # ---- 热度走势预判（对新升级的事件） ----
        try:
            from app.services.heat_predictor import predict_heat_trend
            for evt in recent_events:
                predict_heat_trend(event_id=evt["id"])
            logger.info("热度走势预判完成: 预测 %d 个事件", len(recent_events))
        except Exception as e:
            logger.warning("热度走势预判跳过: %s", e)

        # ---- 处置建议生成（对新升级的事件） ----
        try:
            from app.services.action_advisor import generate_action_advice
            for evt in recent_events:
                generate_action_advice(event_id=evt["id"])
            logger.info("处置建议生成完成: 生成 %d 个事件", len(recent_events))
        except Exception as e:
            logger.warning("处置建议生成跳过: %s", e)

        # 更新任务状态
        update_task(task_id, status="success", result_count=saved_count)
        logger.info("任务完成: [%s] 采集 %d 条, 升级 %d 条", task_id[:8], saved_count, promoted_count)

    except Exception as e:
        error_msg = str(e)[:500]
        update_task(task_id, status="failed", error_message=error_msg)
        logger.error("任务失败: [%s] %s", task_id[:8], error_msg)


def _dispatch_and_execute(platform, task_type, target, keywords=None):
    """
    创建任务记录并立即在后台执行。
    这是 BackgroundTasks 的入口函数（必须是同步的）。
    """
    task_id = _create_task_in_db(platform, task_type, target, keywords)
    _execute_crawl_task(task_id)
    return task_id


def _batch_dispatch_and_execute(platforms: List[str], keywords: List[str]) -> List[str]:
    """
    根据平台列表和关键词列表批量创建并执行爬虫任务。

    策略:
        - 为每个平台创建一个 hotlist（热搜）任务
        - 为每个平台 x 关键词组合创建一个 keyword 任务
        - 所有任务在后台依次执行

    参数:
        platforms: 平台名称列表（如 ["微博", "抖音"]）
        keywords:  关键词列表（如 ["人工智能", "芯片"]）

    返回:
        创建的任务 ID 列表
    """
    dispatched_ids = []

    # 为每个平台下发热搜抓取任务
    for platform_name in platforms:
        platform_key = PLATFORM_NAME_TO_KEY.get(platform_name)
        if not platform_key:
            logger.warning("跳过不支持的平台: %s", platform_name)
            continue

        # 创建热搜任务
        task_id = _create_task_in_db(
            platform=platform_key,
            task_type="hotlist",
            target="hotlist",
            priority=5,
        )
        dispatched_ids.append(task_id)

        # 为每个关键词创建关键词搜索任务
        for kw in keywords:
            kw_task_id = _create_task_in_db(
                platform=platform_key,
                task_type="keyword",
                target=kw,
                keywords=[kw],
                priority=3,
            )
            dispatched_ids.append(kw_task_id)

    # 后台依次执行所有任务
    for tid in dispatched_ids:
        _execute_crawl_task(tid)

    return dispatched_ids


# =======================================================================
# 1. POST /api/crawler/dispatch — 手动下发爬虫任务
# =======================================================================
@router.post("/dispatch", response_model=ApiResponse)
def dispatch_crawler_task(
    req: DispatchRequest,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(_get_current_user),
):
    """
    手动下发单个爬虫任务。

    请求体（JSON）:
      - platform:  平台标识（weibo/douyin/zhihu/xiaohongshu/bilibili/people_rss）
      - task_type: 任务类型（hotlist/keyword/account）
      - target:    抓取目标
      - keywords:  关键词过滤列表（可选）

    返回: {code: 200, data: {task_id: "xxx"}}
    """
    # 校验平台是否支持
    if req.platform not in PLATFORM_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: {req.platform}，支持的平台: {list(PLATFORM_REGISTRY.keys())}",
        )

    # 校验任务类型
    supported_types = PLATFORM_REGISTRY[req.platform]["task_types"]
    if req.task_type not in supported_types:
        raise HTTPException(
            status_code=400,
            detail=f"平台 {req.platform} 不支持任务类型 {req.task_type}，支持: {supported_types}",
        )

    # 创建任务记录并存入数据库
    task_id = _create_task_in_db(
        platform=req.platform,
        task_type=req.task_type,
        target=req.target,
        keywords=req.keywords,
    )

    # 通过后台任务异步执行爬虫，不阻塞 HTTP 响应
    background_tasks.add_task(_execute_crawl_task, task_id)

    return ApiResponse(
        message="爬虫任务已下发",
        data={"task_id": task_id},
    )


# =======================================================================
# 2. POST /api/crawler/dispatch_user_config — 根据用户配置批量下发任务
# =======================================================================
@router.post("/dispatch_user_config", response_model=ApiResponse)
def dispatch_user_config_tasks(
    background_tasks: BackgroundTasks,
    _user: dict = Depends(_get_current_user),
):
    """
    根据当前登录用户的关注配置，批量下发爬虫任务。

    无需请求参数，从当前用户的 focus_platforms 和 focus_keywords 读取配置。
    为每个关注平台创建热搜任务，为每个平台+关键词组合创建关键词搜索任务。

    返回: {code: 200, data: {dispatched_tasks: ["id1", ...], count: N}}
    """
    # 读取用户的关注配置
    platform_names = json.loads(_user.get("focus_platforms") or "[]")
    keyword_list = json.loads(_user.get("focus_keywords") or "[]")

    # 语义关键词扩展：为每个关键词找出语义相近的扩展词
    expanded_keywords = list(keyword_list)  # 原始关键词保留
    try:
        from app.services.nlp_tools import expand_keywords_semantic
        for kw in keyword_list:
            expanded = expand_keywords_semantic(kw, topk=3)
            expanded_keywords.extend(expanded)
        # 去重
        expanded_keywords = list(dict.fromkeys(expanded_keywords))
        if len(expanded_keywords) > len(keyword_list):
            logger.info("关键词语义扩展: %s → %s", keyword_list, expanded_keywords)
    except Exception as e:
        logger.debug("关键词扩展跳过: %s", e)

    if not platform_names and not keyword_list:
        return ApiResponse(
            message="用户暂无关注配置，无需下发任务",
            data={"dispatched_tasks": [], "count": 0},
        )

    # 通过后台任务批量创建并执行爬虫任务（使用扩展后的关键词）
    background_tasks.add_task(_batch_dispatch_and_execute, platform_names, expanded_keywords)

    # 先同步计算会下发的任务数量（用于响应提示）
    estimated_count = 0
    for name in platform_names:
        if name in PLATFORM_NAME_TO_KEY:
            estimated_count += 1  # 每个平台一个 hotlist 任务
            estimated_count += len(expanded_keywords)  # 每个扩展关键词一个 keyword 任务

    return ApiResponse(
        message=f"已触发批量任务下发，预计 {estimated_count} 个任务",
        data={
            "dispatched_tasks": [],
            "count": estimated_count,
        },
    )


# =======================================================================
# 3. GET /api/crawler/tasks — 查询任务列表
# =======================================================================
@router.get("/tasks", response_model=ApiResponse)
def get_crawler_tasks(
    status: Optional[str] = Query(None, description="筛选状态: pending/running/success/failed"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    _user: dict = Depends(_get_current_user),
):
    """
    查询爬虫任务列表。

    参数:
      - status: 按状态筛选（可选: pending/running/success/failed）
      - limit:  返回数量（默认20，最大100）

    返回: {code: 200, data: {tasks: [...], total: N}}
    """
    conn = get_connection()
    try:
        # 确保 crawl_tasks 表存在
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

        # 构建查询条件
        conditions = []
        params = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 查询总数
        total = conn.execute(
            f"SELECT COUNT(*) FROM crawl_tasks {where_clause}", params
        ).fetchone()[0]

        # 查询任务列表（按创建时间倒序）
        rows = conn.execute(
            f"SELECT * FROM crawl_tasks {where_clause} "
            f"ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        tasks = []
        for row in rows:
            task = dict(row)
            # 解析 keywords JSON 字段
            try:
                task["keywords"] = json.loads(task.get("keywords") or "[]")
            except (json.JSONDecodeError, TypeError):
                task["keywords"] = []
            # 附加平台中文名
            platform_info = PLATFORM_REGISTRY.get(task["platform"], {})
            task["platform_name"] = platform_info.get("name", task["platform"])
            tasks.append(task)

        return ApiResponse(data={
            "tasks": tasks,
            "total": total,
        })
    finally:
        conn.close()


# =======================================================================
# 4. GET /api/crawler/stats — 获取爬虫运行统计
# =======================================================================
@router.get("/stats", response_model=ApiResponse)
def get_crawler_stats(
    _user: dict = Depends(_get_current_user),
):
    """
    获取爬虫运行统计数据。

    返回:
      - today_tasks:     今日创建任务总数
      - today_collected: 今日入库数据总数
      - by_platform:     按平台分组的任务统计
      - by_status:       按状态分组的任务统计
    """
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        # 确保 crawl_tasks 表存在
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

        # ---- 今日任务总数 ----
        today_tasks_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM crawl_tasks WHERE created_at LIKE ? || '%'",
            (today,),
        ).fetchone()
        today_tasks = today_tasks_row["cnt"] if today_tasks_row else 0

        # ---- 今日入库数据总数 ----
        today_collected_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM raw_news WHERE crawled_at LIKE ? || '%'",
            (today,),
        ).fetchone()
        today_collected = today_collected_row["cnt"] if today_collected_row else 0

        # ---- 按平台分组统计 ----
        by_platform_rows = conn.execute(
            "SELECT platform, COUNT(*) AS cnt FROM crawl_tasks "
            "WHERE created_at LIKE ? || '%' GROUP BY platform",
            (today,),
        ).fetchall()
        by_platform = {}
        for row in by_platform_rows:
            platform_key = row["platform"]
            # 附加平台中文名
            platform_name = PLATFORM_REGISTRY.get(platform_key, {}).get("name", platform_key)
            by_platform[platform_name] = row["cnt"]

        # ---- 按状态分组统计 ----
        by_status_rows = conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM crawl_tasks "
            "WHERE created_at LIKE ? || '%' GROUP BY status",
            (today,),
        ).fetchall()
        by_status = {}
        for row in by_status_rows:
            by_status[row["status"]] = row["cnt"]

        return ApiResponse(data={
            "today_tasks": today_tasks,
            "today_collected": today_collected,
            "by_platform": by_platform,
            "by_status": by_status,
        })
    finally:
        conn.close()


# =======================================================================
# 5. GET /api/crawler/platforms — 获取支持的平台列表
# =======================================================================
@router.get("/platforms", response_model=ApiResponse)
def get_supported_platforms():
    """
    获取系统支持的所有平台列表。

    返回: {code: 200, data: [{key, name, task_types}, ...]}
    """
    platforms = []
    for key, info in PLATFORM_REGISTRY.items():
        platforms.append({
            "key": key,
            "name": info["name"],
            "task_types": info["task_types"],
        })

    return ApiResponse(data=platforms)


# =======================================================================
# 6. GET /api/crawler/similar_events — 搜索相似事件
# =======================================================================
@router.get("/similar_events", response_model=ApiResponse)
def search_similar_events_api(
    title: str = Query(..., description="事件标题"),
    topk: int = Query(5, description="返回数量"),
    _user: dict = Depends(_get_current_user),
):
    """搜索与给定标题相似的历史事件"""
    from app.services.event_aggregator import search_similar_events
    results = search_similar_events(title, topk=topk)
    return ApiResponse(data=results)


# =======================================================================
# 7. POST /api/crawler/detect_fake — 虚假文本检测
# =======================================================================
@router.post("/detect_fake", response_model=ApiResponse)
def detect_fake_text_api(
    title: str = Body(..., embed=True),
    content: str = Body("", embed=True),
    source_platform: str = Body("", embed=True),
    _user: dict = Depends(_get_current_user),
):
    """虚假文本检测接口，接收标题和正文，返回可信度评分和判定理由"""
    from app.services.fake_detector import detect_fake_text
    result = detect_fake_text(
        title=title,
        content=content,
        source_platform=source_platform,
    )
    return ApiResponse(data=result)


# =======================================================================
# 8. POST /api/crawler/analyze_spread — 传播路径分析
# =======================================================================
@router.post("/analyze_spread", response_model=ApiResponse)
def analyze_spread_api(
    event_id: int = Body(..., embed=True),
    _user: dict = Depends(_get_current_user),
):
    """事件传播路径分析接口，分析指定事件的传播链路并生成可视化图数据"""
    from app.services.spread_analyzer import analyze_spread_path
    result = analyze_spread_path(event_id=event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="事件不存在或无关联数据")
    return ApiResponse(data=result)


# =======================================================================
# 9. POST /api/crawler/analyze_emotion — 舆情情绪量化分析
# =======================================================================
@router.post("/analyze_emotion", response_model=ApiResponse)
def analyze_emotion_api(
    event_id: int = Body(..., embed=True),
    _user: dict = Depends(_get_current_user),
):
    """舆情情绪量化分析接口，分析事件关联新闻的情感分布和激化节点"""
    from app.services.emotion_analyzer import analyze_event_emotion
    result = analyze_event_emotion(event_id=event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="事件不存在或无关联数据")
    return ApiResponse(data=result)


# =======================================================================
# 10. POST /api/crawler/predict_heat — 短期热度走势预判
# =======================================================================
@router.post("/predict_heat", response_model=ApiResponse)
def predict_heat_api(
    event_id: int = Body(..., embed=True),
    _user: dict = Depends(_get_current_user),
):
    """短期热度走势预判接口，预测事件未来24~72小时的热度走向"""
    from app.services.heat_predictor import predict_heat_trend
    result = predict_heat_trend(event_id=event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="事件不存在或无关联数据")
    return ApiResponse(data=result)


# =======================================================================
# 11. POST /api/crawler/action_advice — 轻量化处置建议
# =======================================================================
@router.post("/action_advice", response_model=ApiResponse)
def action_advice_api(
    event_id: int = Body(..., embed=True),
    _user: dict = Depends(_get_current_user),
):
    """轻量化处置建议接口，整合全部分析结论输出参考举措"""
    from app.services.action_advisor import generate_action_advice
    result = generate_action_advice(event_id=event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="事件不存在或无关联数据")
    return ApiResponse(data=result)
