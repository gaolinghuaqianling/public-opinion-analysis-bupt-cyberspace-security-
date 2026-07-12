# -*- coding: utf-8 -*-
"""
网络舆情智能分析系统 - FastAPI 主入口
启动方式: uvicorn main:app --reload --port 8000
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import init_db
from app.api.auth import router as auth_router
from app.api.news import router as news_router
from app.api.event import router as event_router
from app.api.analysis import router as analysis_router
from app.api.spread import router as spread_router
from app.api.routes import router as routes_router
from app.api.crawler_api import router as crawler_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    try:
        init_db()
        print("数据库初始化完成，系统启动成功")
    except Exception as e:
        print(f"数据库初始化跳过（已存在或异常: {e}）")
    yield


app = FastAPI(
    title="网络舆情智能分析系统",
    description="基于 FastAPI + SQLite 的舆情监控后端服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router,  prefix="/api")
app.include_router(news_router,  prefix="/api")
app.include_router(event_router,  prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(spread_router,  prefix="/api")
app.include_router(routes_router, prefix="/api")
app.include_router(crawler_router, prefix="/api")


@app.get("/", tags=["系统"])
def root():
    return {"message": "网络舆情智能分析系统 API", "docs": "/docs"}


@app.get("/health", tags=["系统"])
def health_check():
    """健康检查"""
    return {"status": "ok"}
