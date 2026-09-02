"""
OAuth авторизация — логин или регистрация пользователя с выдачей JWT токена.
"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User
from fastapi import HTTPException
from datetime import datetime, timezone
from config import get_logger
from dependencies import create_access_token

logger = get_logger(__name__)


class OAuthLoginRequest:
    def __init__(
        self,
        email: str,
        name: str,
        auth_type: str,
        telegram_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
    ):
        self.email = email
        self.name = name
        self.auth_type = auth_type
        self.telegram_id = telegram_id
        self.telegram_username = telegram_username


async def oauth_login_or_register(data: OAuthLoginRequest, db: AsyncSession) -> Dict[str, Any]:
    """Логин или регистрация через OAuth с выдачей JWT-токена."""
    try:
        # Поиск по email или telegram_id
        user = None
        if data.telegram_id:
            result = await db.execute(select(User).where(User.telegram_id == data.telegram_id))
            user = result.scalars().first()

        if not user:
            result = await db.execute(select(User).where(User.email == data.email))
            user = result.scalars().first()

        if user:
            # Обновляем при необходимости недостающие поля
            updated = False
            if data.telegram_id and not user.telegram_id:
                user.telegram_id = data.telegram_id
                user.telegram_username = data.telegram_username
                updated = True
            if updated:
                await db.commit()
                await db.refresh(user)

            logger.info("✅ Пользователь вошел через OAuth: %s", user.email)
            token = create_access_token({"sub": str(user.id), "email": user.email})
            return {
                "access_token": token,
                "token_type": "bearer",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "is_mentor": user.is_mentor,
                    "auth_type": user.auth_type,
                },
                "message": "✅ Вы успешно вошли",
            }

        # Создаём нового пользователя через OAuth
        user = User(
            email=data.email,
            name=data.name or "Пользователь",
            auth_type=data.auth_type,
            password_hash=None,
            created_at=datetime.now(timezone.utc),
        )

        if data.auth_type == "telegram" and data.telegram_id:
            user.telegram_id = data.telegram_id
            user.telegram_username = data.telegram_username

        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info("✅ Новый пользователь создан через OAuth: %s (%s)", user.email, data.auth_type)
        token = create_access_token({"sub": str(user.id), "email": user.email})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "is_mentor": user.is_mentor,
                "auth_type": user.auth_type,
            },
            "message": "✅ Аккаунт создан и вы вошли",
        }
    except Exception as e:
        await db.rollback()
        logger.error("❌ Ошибка OAuth: %s", e)
        raise HTTPException(status_code=500, detail=f"❌ Ошибка OAuth: {e}")