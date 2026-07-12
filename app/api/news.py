# -*- coding: utf-8 -*-
"""爬虫原始新闻路由：增删改查"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.database import get_connection
from app.api.auth import get_current_user
from app.schemas.schemas import RawNewsCreate, RawNewsOut, ApiResponse

router = APIRouter(prefix="/news", tags=["原始新闻"])


@router.post("/", response_model=ApiResponse)
def create_news(news: RawNewsCreate, _user=Depends(get_current_user)):
    """新增一条爬虫新闻"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO raw_news (title, content, source_platform, published_at, original_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (news.title, news.content, news.source_platform, news.published_at, news.original_url)
        )
        conn.commit()
        return ApiResponse(message="新闻录入成功")
    finally:
        conn.close()


@router.get("/", response_model=ApiResponse)
def list_news(
    platform: Optional[str] = Query(None, description="按平台筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    """分页查询新闻列表"""
    conn = get_connection()
    try:
        conditions, params = [], []
        if platform:
            conditions.append("source_platform = ?")
            params.append(platform)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        total = conn.execute(f"SELECT COUNT(*) FROM raw_news {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM raw_news {where} ORDER BY crawled_at DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size]
        ).fetchall()

        items = [RawNewsOut(**dict(r)) for r in rows]
        return ApiResponse(data={"total": total, "page": page, "page_size": page_size, "items": items})
    finally:
        conn.close()


@router.get("/{news_id}", response_model=ApiResponse)
def get_news(news_id: int, _user=Depends(get_current_user)):
    """根据ID获取新闻详情"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM raw_news WHERE id = ?", (news_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="新闻不存在")
        return ApiResponse(data=RawNewsOut(**dict(row)))
    finally:
        conn.close()


@router.delete("/{news_id}", response_model=ApiResponse)
def delete_news(news_id: int, _user=Depends(get_current_user)):
    """删除新闻"""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM raw_news WHERE id = ?", (news_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="新闻不存在")
        return ApiResponse(message="删除成功")
    finally:
        conn.close()
