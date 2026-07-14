# -*- coding: utf-8 -*-
"""热点事件路由：增删改查"""
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import get_connection
from app.api.auth import get_current_user
from app.schemas.schemas import HotEventCreate, HotEventOut, ApiResponse

router = APIRouter(prefix="/events", tags=["热点事件"])


@router.post("/", response_model=ApiResponse)
def create_event(event: HotEventCreate, _user=Depends(get_current_user)):
    """创建热点事件"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO hot_event (title, heat_score, risk_level, summary, lifecycle) "
            "VALUES (?, ?, ?, ?, ?)",
            (event.title, event.heat_score, event.risk_level, event.summary, event.lifecycle)
        )
        conn.commit()
        return ApiResponse(message="事件创建成功")
    finally:
        conn.close()


@router.get("/", response_model=ApiResponse)
def list_events(
    risk_level: Optional[str] = Query(None, description="按风险等级筛选"),
    lifecycle: Optional[str] = Query(None, description="按生命周期筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    """分页查询热点事件"""
    conn = get_connection()
    try:
        conditions, params = [], []
        if risk_level:
            conditions.append("risk_level = ?")
            params.append(risk_level)
        if lifecycle:
            conditions.append("lifecycle = ?")
            params.append(lifecycle)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = conn.execute(f"SELECT COUNT(*) FROM hot_event {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM hot_event {where} ORDER BY heat_score DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size]
        ).fetchall()

        items = [HotEventOut(**dict(r)) for r in rows]
        return ApiResponse(data={"total": total, "page": page, "page_size": page_size, "items": items})
    finally:
        conn.close()


@router.get("/{event_id}", response_model=ApiResponse)
def get_event(event_id: int, _user=Depends(get_current_user)):
    """获取事件详情"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM hot_event WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="事件不存在")
        data = dict(row)
        summary = data.get("summary", "")
        interaction_data = None
        # 检测 summary 中是否包含 interaction_data JSON 字符串
        # summary 格式可能是: 【地点】xx 【概述】{"interaction_data": {...}}
        if summary:
            import re
            # 尝试提取 {} 包裹的 JSON 部分
            json_match = re.search(r'\{.*"interaction_data".*\}', summary, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    if isinstance(parsed, dict) and "interaction_data" in parsed:
                        interaction_data = parsed["interaction_data"]
                        # 清理 summary：去掉 JSON 部分，保留前面的文本
                        cleaned = summary[:json_match.start()].strip()
                        # 去掉末尾的【概述】等标签
                        cleaned = re.sub(r'【概述】\s*$', '', cleaned).strip()
                        data["summary"] = cleaned
                except Exception:
                    pass
            # 再尝试整串解析（纯 JSON 的情况）
            elif summary.strip().startswith("{"):
                try:
                    parsed = json.loads(summary)
                    if isinstance(parsed, dict) and "interaction_data" in parsed:
                        interaction_data = parsed["interaction_data"]
                        data["summary"] = ""
                except Exception:
                    pass
        if interaction_data is not None:
            data["interaction_data"] = interaction_data
        return ApiResponse(data=data)
    finally:
        conn.close()


@router.put("/{event_id}/summary", response_model=ApiResponse)
def update_event_summary(event_id: int, body: dict, _user=Depends(get_current_user)):
    """编辑事件概述（仅更新 summary 字段）"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE hot_event SET summary = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (body.get("summary", ""), event_id)
        )
        conn.commit()
        return {"code": 200, "message": "概述更新成功"}
    finally:
        conn.close()


@router.put("/{event_id}", response_model=ApiResponse)
def update_event(event_id: int, event: HotEventCreate, _user=Depends(get_current_user)):
    """更新事件信息"""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE hot_event SET title=?, heat_score=?, risk_level=?, summary=?, lifecycle=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (event.title, event.heat_score, event.risk_level, event.summary, event.lifecycle, event_id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="事件不存在")
        return ApiResponse(message="更新成功")
    finally:
        conn.close()


@router.delete("/{event_id}", response_model=ApiResponse)
def delete_event(event_id: int, _user=Depends(get_current_user)):
    """删除事件（级联删除关联的分析和溯源）"""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM hot_event WHERE id = ?", (event_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="事件不存在")
        return ApiResponse(message="删除成功")
    finally:
        conn.close()
