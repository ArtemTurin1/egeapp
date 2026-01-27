from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import User
from fastapi import HTTPException
import os

FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')


class OAuthLoginRequest:
    def __init__(self, email: str, name: str, auth_type: str,
                 yandex_id: str = None, telegram_id: int = None,
                 telegram_username: str = None):
        self.email = email
        self.name = name
        self.auth_type = auth_type
        self.yandex_id = yandex_id
        self.telegram_id = telegram_id
        self.telegram_username = telegram_username


async def oauth_login_or_register(data, db: AsyncSession):
    """Логин или регистрация через OAuth"""
    try:
        # Ищем пользователя по email
        result = await db.execute(select(User).where(User.email == data.email))
        user = result.scalars().first()

        if user:
            # Пользователь существует
            print(f"✅ Пользователь существует: {user.email}")
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "auth_type": user.auth_type,
                "message": "✅ Вы успешно вошли"
            }

        # Создаём нового пользователя через OAuth
        user = User(
            email=data.email,
            name=data.name,
            auth_type=data.auth_type,
            password_hash=None,  # Нет пароля для OAuth
        )

        if data.auth_type == 'yandex' and data.yandex_id:
            user.yandex_id = data.yandex_id
        elif data.auth_type == 'telegram' and data.telegram_id:
            user.telegram_id = data.telegram_id
            user.telegram_username = data.telegram_username

        db.add(user)
        await db.commit()
        await db.refresh(user)

        print(f"✅ Новый пользователь создан: {user.email} ({data.auth_type})")
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "auth_type": user.auth_type,
            "message": "✅ Аккаунт создан и вы вошли"
        }

    except Exception as e:
        await db.rollback()
        print(f"❌ Ошибка OAuth: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')