# -*- coding: utf-8 -*-
"""事件分析详情路由：增删改查"""
import json
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_connection
from app.api.auth import get_current_user
from app.schemas.schemas import EventAnalysisCreate, EventAnalysisOut, ApiResponse

router = APIRouter(prefix="/analysis", tags=["事件分析"])


@router.post("/", response_model=ApiResponse)
def create_analysis(analysis: EventAnalysisCreate, _user=Depends(get_current_user)):
    """创建事件分析详情"""
    conn = get_connection()
    try:
        # 校验事件是否存在
        event = conn.execute("SELECT id FROM hot_event WHERE id = ?", (analysis.event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="关联事件不存在")

        conn.execute(
            "INSERT INTO event_analysis "
            "(event_id, positive_ratio, negative_ratio, neutral_ratio, high_freq_keywords, platform_coverage) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (analysis.event_id, analysis.positive_ratio, analysis.negative_ratio,
             analysis.neutral_ratio,
             json.dumps(analysis.high_freq_keywords, ensure_ascii=False),
             json.dumps(analysis.platform_coverage, ensure_ascii=False))
        )
        conn.commit()
        return ApiResponse(message="分析创建成功")
    finally:
        conn.close()


@router.get("/event/{event_id}", response_model=ApiResponse)
def get_analysis_by_event(event_id: int, _user=Depends(get_current_user)):
    """获取指定事件的分析详情"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM event_analysis WHERE event_id = ? ORDER BY analyzed_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="该事件暂无分析数据")
        out = EventAnalysisOut(
            id=row["id"],
            event_id=row["event_id"],
            positive_ratio=row["positive_ratio"],
            negative_ratio=row["negative_ratio"],
            neutral_ratio=row["neutral_ratio"],
            high_freq_keywords=json.loads(row["high_freq_keywords"]),
            platform_coverage=json.loads(row["platform_coverage"]),
            analyzed_at=row["analyzed_at"],
        )
        return ApiResponse(data=out)
    finally:
        conn.close()


@router.delete("/{analysis_id}", response_model=ApiResponse)
def delete_analysis(analysis_id: int, _user=Depends(get_current_user)):
    """删除分析记录"""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM event_analysis WHERE id = ?", (analysis_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="分析记录不存在")
        return ApiResponse(message="删除成功")
    finally:
        conn.close()
