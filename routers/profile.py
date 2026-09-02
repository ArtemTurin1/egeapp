"""
Роутеры профиля пользователя: просмотр и обновление.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User
from schemas import UserUpdateRequest, UserProfileResponse
from dependencies import get_db, get_current_user, get_optional_current_user
from config import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["profile"])


@router.get("/api/profile/me", response_model=UserProfileResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    """Получить профиль текущего авторизованного пользователя."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_mentor=current_user.is_mentor,
        auth_type=current_user.auth_type,
        telegram_id=current_user.telegram_id,
        telegram_username=current_user.telegram_username,
        created_at=current_user.created_at,
    )


@router.get("/api/auth/me", response_model=UserProfileResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Получить текущего авторизованного пользователя (alias)."""
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_mentor=current_user.is_mentor,
        auth_type=current_user.auth_type,
        telegram_id=current_user.telegram_id,
        telegram_username=current_user.telegram_username,
        created_at=current_user.created_at,
    )


@router.get("/api/profile/email/{email}")
async def get_profile_email(email: str, db: AsyncSession = Depends(get_db)):
    """Получить публичный профиль пользователя по email."""
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name or "Пользователь",
        "is_mentor": bool(user.is_mentor),
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "auth_type": user.auth_type,
        "created_at": user.created_at,
    }


@router.put("/api/profile/update")
async def update_profile(
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обновить имя в профиле текущего пользователя."""
    current_user.name = data.name.strip()
    await db.commit()
    await db.refresh(current_user)
    return {"id": current_user.id, "name": current_user.name, "message": "Имя успешно обновлено"}


@router.get("/api/profile/status")
async def get_profile_status(current_user: User = Depends(get_current_user)):
    """Получить статус и роль пользователя."""
    return {
        "user_id": current_user.id,
        "is_mentor": bool(current_user.is_mentor),
        "role": "Наставник" if current_user.is_mentor else "Ученик",
    }
