# -*- coding: utf-8 -*-
"""用户画像分析 API 路由"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.database import get_connection
from app.api.auth import get_current_user
from app.schemas.schemas import ApiResponse
from app.services.user_profile_analyzer import (
    analyze_user_profile_full,
    classify_users,
    analyze_audience_profile,
    classify_brand_audience,
    build_enhanced_graph_data,
)

logger = logging.getLogger("api.user_profile")

router = APIRouter(prefix="/user-profile", tags=["用户画像分析"])


# ==================== 请求模型 ====================

class AnalyzeRequest(BaseModel):
    """画像分析请求"""
    event_id: int = Field(..., description="事件 ID")
    brand_name: Optional[str] = Field(None, description="品牌名称（可选）")


class LoadTestDataRequest(BaseModel):
    """加载测试数据请求"""
    pass


# ==================== 端点 1：完整画像分析 ====================

@router.post("/analyze", response_model=ApiResponse)
def analyze_user_profile(
    req: AnalyzeRequest,
    _user=Depends(get_current_user),
):
    """
    对指定事件执行完整的用户画像分析。

    请求体:
        {"event_id": int, "brand_name": str(可选)}

    返回:
        完整画像分析结果，包括:
        - user_classifications: 用户四分类结果
        - audience_profile: 受众多维度画像（地域/兴趣圈层/年龄段）
        - brand_audience: 品牌人群分层
        - graph_data: 增强传播图谱数据
        - statistics: 分类统计汇总
    """
    # 验证事件是否存在
    conn = get_connection()
    try:
        event = conn.execute(
            "SELECT id FROM hot_event WHERE id = ?", (req.event_id,)
        ).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="事件不存在")
    finally:
        conn.close()

    # 执行完整画像分析
    try:
        result = analyze_user_profile_full(
            event_id=req.event_id,
            brand_name=req.brand_name,
        )
    except Exception as e:
        logger.error("画像分析失败: event_id=%d, error=%s", req.event_id, e)
        raise HTTPException(status_code=500, detail=f"画像分析失败: {str(e)}")

    if result is None:
        raise HTTPException(status_code=404, detail="该事件无传播参与用户数据")

    return ApiResponse(
        message="画像分析完成",
        data=result,
    )


# ==================== 端点 2：加载测试数据 ====================

@router.post("/load-test-data", response_model=ApiResponse)
def load_test_data(
    _req: LoadTestDataRequest = LoadTestDataRequest(),
    _user=Depends(get_current_user),
):
    """
    加载内置的测试数据集到数据库。

    测试数据模拟"某品牌手机电池爆炸事件"的舆情传播参与用户，
    包含约 43 个用户（水军 10 + 真实网民 20 + 营销号 8 + 行业利益方 5）。

    请求体:
        {}

    返回:
        加载结果统计信息
    """
    try:
        from app.data.test_user_profile_data import generate_test_data
        from app.core.database import get_db_path

        db_path = str(get_db_path())
        users = generate_test_data(db_path=db_path)

        # 统计信息
        total = len(users)
        categories = {}
        for u in users:
            cat = u.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        category_names = {
            "water_army": "水军",
            "marketing": "营销号",
            "industry": "行业利益方",
            "real_user": "普通网民",
        }

        return ApiResponse(
            message="测试数据加载成功",
            data={
                "total_users": total,
                "detail": {
                    category_names.get(cat, cat): count
                    for cat, count in categories.items()
                },
                "hint": "请使用 event_id=1 进行画像分析测试",
            },
        )
    except Exception as e:
        logger.error("加载测试数据失败: %s", e)
        raise HTTPException(status_code=500, detail=f"加载测试数据失败: {str(e)}")


# ==================== 端点 3：单个用户画像详情 ====================

@router.get("/user-detail", response_model=ApiResponse)
def get_user_detail(
    user_name: str = Query(..., description="用户名"),
    event_id: int = Query(..., description="事件 ID"),
    _user=Depends(get_current_user),
):
    """
    查询单个用户的完整画像信息。

    查询参数:
        - user_name: 用户名
        - event_id: 事件 ID

    返回:
        单个用户的详细画像数据，包括:
        - 基本信息（昵称、IP属地、简介等）
        - 分类结果
        - 历史内容列表
        - 画像分析数据
    """
    # 获取用户基本信息
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM spread_user WHERE user_name = ? AND event_id = ?",
            (user_name, event_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="未找到该用户在此事件中的记录")

        user_info = dict(row)

        # 获取用户历史内容
        content_rows = conn.execute(
            "SELECT * FROM user_content WHERE user_name = ?",
            (user_name,),
        ).fetchall()
        contents = [dict(r) for r in content_rows]
    finally:
        conn.close()

    # 执行该用户的四分类
    try:
        all_classifications = classify_users(event_id)
        user_classification = None
        for uc in all_classifications:
            if uc["user_name"] == user_name:
                user_classification = uc
                break
    except Exception as e:
        logger.warning("用户分类查询失败: %s", e)
        user_classification = None

    # 执行受众多维度画像（单用户）
    try:
        audience_profile = analyze_audience_profile([user_name])
    except Exception as e:
        logger.warning("受众画像查询失败: %s", e)
        audience_profile = None

    return ApiResponse(
        message="查询成功",
        data={
            "user_info": {
                "user_name": user_info.get("user_name"),
                "user_id": user_info.get("user_id"),
                "platform": user_info.get("platform"),
                "ip_location": user_info.get("ip_location"),
                "bio": user_info.get("bio"),
                "register_date": user_info.get("register_date"),
                "followers_count": user_info.get("followers_count"),
                "following_count": user_info.get("following_count"),
                "posts_count": user_info.get("posts_count"),
            },
            "classification": user_classification,
            "contents": contents,
            "audience_profile": audience_profile,
        },
    )
