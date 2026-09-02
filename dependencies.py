"""
Общие зависимости, утилиты безопасности, JWT и вспомогательные функции.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_logger,
)
from models import (
    async_session,
    User,
)

logger = get_logger(__name__)
security = HTTPBearer(auto_error=False)


# ---------- Утилиты паролей ----------

def hash_password(password: str) -> str:
    """Безопасный хеш пароля с солью SHA-256 + secret."""
    salt = JWT_SECRET_KEY[:16]
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not hashed_password or not plain_password:
        return False
    return hash_password(plain_password) == hashed_password


# ---------- JWT Утилиты ----------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError as e:
        logger.debug("JWT decode failed: %s", e)
        return None


# ---------- DB Session ----------

async def get_db():
    async with async_session() as session:
        yield session


# ---------- Текущий пользователь ----------

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Извлекает текущего пользователя из JWT токена (Bearer).
    Поддерживает fallback на X-EMAIL для обратной совместимости.
    """
    user_id = None
    email = None

    if credentials and credentials.credentials:
        payload = decode_access_token(credentials.credentials)
        if payload:
            user_id = payload.get("sub") or payload.get("user_id")
            email = payload.get("email")

    if not user_id and not email:
        email = request.headers.get("X-EMAIL")

    if not user_id and not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Не авторизованы. Требуется токен авторизации.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_id:
        try:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            user = result.scalars().first()
        except (ValueError, TypeError):
            user = None
    else:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден или токен недействителен",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    try:
        return await get_current_user(request, credentials, db)
    except HTTPException:
        return None
