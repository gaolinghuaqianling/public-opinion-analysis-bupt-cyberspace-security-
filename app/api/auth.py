# -*- coding: utf-8 -*-
"""用户认证路由：注册、登录、获取当前用户信息"""
import json
import hashlib
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.database import get_connection
from app.core.auth import hash_password, verify_password, create_access_token, decode_access_token
from app.schemas.schemas import UserCreate, UserLogin, UserOut, TokenResponse, ApiResponse

router = APIRouter(prefix="/auth", tags=["用户认证"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """依赖注入：从Token解析当前用户"""
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效或过期的Token")
    user_id = payload.get("sub")
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
        return dict(row)
    finally:
        conn.close()


@router.post("/register", response_model=ApiResponse)
def register(user_in: UserCreate):
    """用户注册"""
    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM user WHERE username = ?", (user_in.username,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 前端传来的已经是 MD5 值，服务端再 MD5 一次后存储（与登录 double-md5 逻辑一致）
        double_md5 = hashlib.md5(user_in.password.encode("utf-8")).hexdigest()
        pwd_hash = hash_password(double_md5)
        conn.execute(
            "INSERT INTO user (username, password_hash, focus_platforms, focus_keywords) VALUES (?, ?, ?, ?)",
            (user_in.username, pwd_hash, json.dumps(user_in.focus_platforms, ensure_ascii=False),
             json.dumps(user_in.focus_keywords, ensure_ascii=False))
        )
        conn.commit()
        return ApiResponse(message="注册成功")
    finally:
        conn.close()


@router.post("/login", response_model=TokenResponse)
def login(user_in: UserLogin):
    """用户登录，返回JWT Token"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM user WHERE username = ?", (user_in.username,)).fetchone()
        if row is None or not verify_password(user_in.password, row["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

        token = create_access_token(data={"sub": str(row["id"])})
        user_out = UserOut(
            id=row["id"],
            username=row["username"],
            focus_platforms=json.loads(row["focus_platforms"]),
            focus_keywords=json.loads(row["focus_keywords"]),
            created_at=row["created_at"],
        )
        return TokenResponse(access_token=token, user=user_out)
    finally:
        conn.close()


@router.get("/me", response_model=ApiResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return ApiResponse(data={
        "id": current_user["id"],
        "username": current_user["username"],
        "focus_platforms": json.loads(current_user["focus_platforms"]),
        "focus_keywords": json.loads(current_user["focus_keywords"]),
        "created_at": current_user["created_at"],
    })
