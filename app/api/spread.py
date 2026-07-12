# -*- coding: utf-8 -*-
"""传播溯源路由：增删改查"""
import json
from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_connection
from app.api.auth import get_current_user
from app.schemas.schemas import SpreadInfoCreate, SpreadInfoOut, ApiResponse

router = APIRouter(prefix="/spread", tags=["传播溯源"])


@router.post("/", response_model=ApiResponse)
def create_spread(spread: SpreadInfoCreate, _user=Depends(get_current_user)):
    """创建传播溯源记录"""
    conn = get_connection()
    try:
        event = conn.execute("SELECT id FROM hot_event WHERE id = ?", (spread.event_id,)).fetchone()
        if event is None:
            raise HTTPException(status_code=404, detail="关联事件不存在")

        conn.execute(
            "INSERT INTO spread_info "
            "(event_id, origin_platform, origin_url, spread_nodes, spread_depth, total_reposts, total_reads) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (spread.event_id, spread.origin_platform, spread.origin_url,
             json.dumps(spread.spread_nodes, ensure_ascii=False),
             spread.spread_depth, spread.total_reposts, spread.total_reads)
        )
        conn.commit()
        return ApiResponse(message="溯源记录创建成功")
    finally:
        conn.close()


@router.get("/event/{event_id}", response_model=ApiResponse)
def get_spread_by_event(event_id: int, _user=Depends(get_current_user)):
    """获取指定事件的传播溯源信息"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM spread_info WHERE event_id = ? ORDER BY traced_at DESC LIMIT 1",
            (event_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="该事件暂无溯源数据")
        out = SpreadInfoOut(
            id=row["id"],
            event_id=row["event_id"],
            origin_platform=row["origin_platform"],
            origin_url=row["origin_url"],
            spread_nodes=json.loads(row["spread_nodes"]),
            spread_depth=row["spread_depth"],
            total_reposts=row["total_reposts"],
            total_reads=row["total_reads"],
            traced_at=row["traced_at"],
        )
        return ApiResponse(data=out)
    finally:
        conn.close()


@router.delete("/{spread_id}", response_model=ApiResponse)
def delete_spread(spread_id: int, _user=Depends(get_current_user)):
    """删除溯源记录"""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM spread_info WHERE id = ?", (spread_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="溯源记录不存在")
        return ApiResponse(message="删除成功")
    finally:
        conn.close()
