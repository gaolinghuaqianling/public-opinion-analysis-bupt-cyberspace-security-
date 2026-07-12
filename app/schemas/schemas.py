# -*- coding: utf-8 -*-
"""Pydantic 数据模型定义"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field


# ==================== 用户 ====================
class UserCreate(BaseModel):
    """用户注册"""
    username: str = Field(..., min_length=3, max_length=32, description="用户名")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    focus_platforms: List[str] = Field(default_factory=list, description="关注平台列表")
    focus_keywords: List[str] = Field(default_factory=list, description="关注关键词列表")


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class UserOut(BaseModel):
    """用户信息输出"""
    id: int
    username: str
    focus_platforms: List[str]
    focus_keywords: List[str]
    created_at: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """登录Token响应"""
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ==================== 原始新闻 ====================
class RawNewsCreate(BaseModel):
    """新增爬虫新闻"""
    title: str
    content: str = ""
    source_platform: str
    published_at: Optional[str] = None
    original_url: Optional[str] = None


class RawNewsOut(BaseModel):
    """新闻输出"""
    id: int
    title: str
    content: str
    source_platform: str
    published_at: Optional[str]
    original_url: Optional[str]
    crawled_at: str
    status: str


# ==================== 热点事件 ====================
class HotEventCreate(BaseModel):
    """创建热点事件"""
    title: str
    heat_score: float = Field(default=0.0, ge=0, le=100)
    risk_level: str = Field(default="low")
    summary: str = ""
    lifecycle: str = Field(default="latent")  # latent/growth/peak/decline


class HotEventOut(BaseModel):
    """热点事件输出"""
    id: int
    title: str
    heat_score: float
    risk_level: str
    summary: str
    lifecycle: str
    created_at: str
    updated_at: str


# ==================== 事件分析 ====================
class EventAnalysisCreate(BaseModel):
    """创建事件分析"""
    event_id: int
    positive_ratio: float = Field(default=0.0, ge=0, le=1)
    negative_ratio: float = Field(default=0.0, ge=0, le=1)
    neutral_ratio: float = Field(default=1.0, ge=0, le=1)
    high_freq_keywords: List[str] = Field(default_factory=list)
    platform_coverage: Dict[str, float] = Field(default_factory=dict)


class EventAnalysisOut(BaseModel):
    """事件分析输出"""
    id: int
    event_id: int
    positive_ratio: float
    negative_ratio: float
    neutral_ratio: float
    high_freq_keywords: List[str]
    platform_coverage: Dict[str, float]
    analyzed_at: str


# ==================== 传播溯源 ====================
class SpreadInfoCreate(BaseModel):
    """创建传播溯源"""
    event_id: int
    origin_platform: str
    origin_url: Optional[str] = None
    spread_nodes: List[Dict] = Field(default_factory=list)
    spread_depth: int = 0
    total_reposts: int = 0
    total_reads: int = 0


class SpreadInfoOut(BaseModel):
    """传播溯源输出"""
    id: int
    event_id: int
    origin_platform: str
    origin_url: Optional[str]
    spread_nodes: List[Dict]
    spread_depth: int
    total_reposts: int
    total_reads: int
    traced_at: str


# ==================== 通用响应 ====================
class ApiResponse(BaseModel):
    """统一API响应"""
    code: int = 200
    message: str = "success"
    data: Optional[object] = None
