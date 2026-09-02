"""
Роутеры авторизации: Telegram Регистрация и Вход по коду.
"""

from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User, RegistrationCode
from schemas import (
    TokenResponse,
    UserProfileResponse,
    CodeVerifyRequest,
    CodeRegisterRequest,
    CodeLoginRequest,
    EmailRegisterRequest,
    EmailLoginRequest,
    LinkTelegramRequest,
)
from auth_service import oauth_login_or_register, OAuthLoginRequest
from dependencies import (
    get_db,
    get_current_user,
    create_access_token,
    hash_password,
    verify_password,
)
from config import (
    FRONTEND_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_PROXY,
    get_logger,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------- Вспомогательные функции ----------

def make_user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name or "Пользователь",
        "is_mentor": user.is_mentor,
        "auth_type": user.auth_type,
        "telegram_id": user.telegram_id,
        "telegram_username": user.telegram_username,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


async def send_telegram_notification(
    telegram_id: int, name: str, code: str, email: str
) -> bool:
    """Отправляет уведомление о регистрации в Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан, уведомление не отправлено")
        return False

    try:
        message_text = (
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"✅ Вы успешно зарегистрировались на <b>КогдаУрок</b>\n\n"
            f"👤 <b>Имя:</b> {name}\n"
            f"📧 <b>Email:</b> {email}\n"
            f"🔐 <b>Ваш код доступа:</b> <code>{code}</code>\n\n"
            f"⏰ <b>Время:</b> {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')} UTC\n\n"
            f"💡 Сохраните этот код — он нужен для входа на других устройствах\n\n"
            f"Успешных занятий и подготовки! 🚀"
        )

        proxy_arg = TELEGRAM_PROXY if TELEGRAM_PROXY else None
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy_arg) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": message_text,
                    "parse_mode": "HTML",
                },
            )
            return response.status_code == 200
    except Exception as e:
        logger.error("❌ Ошибка отправки в Telegram: %s", e)
        return False


# ---------- Классическая аутентификация (Email + Пароль) ----------

@router.post("/register-email")
async def register_email(data: EmailRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Регистрация нового пользователя по Email и Паролю."""
    email_clean = data.email.strip().lower()
    name_clean = data.name.strip()

    # Проверяем уникальность email
    existing_res = await db.execute(select(User).where(User.email == email_clean))
    if existing_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже зарегистрирован. Пожалуйста, выполните вход.",
        )

    pwd_hash = hash_password(data.password)
    user = User(
        email=email_clean,
        name=name_clean,
        password_hash=pwd_hash,
        is_mentor=data.is_mentor,
        auth_type="email",
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "message": f"Добро пожаловать, {user.name}!",
        "user": make_user_dict(user),
    }


@router.post("/login-email")
async def login_email(data: EmailLoginRequest, db: AsyncSession = Depends(get_db)):
    """Вход существующего пользователя по Email и Паролю."""
    email_clean = data.email.strip().lower()

    res = await db.execute(select(User).where(User.email == email_clean))
    user = res.scalars().first()

    if not user or not user.password_hash or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "message": f"Рады видеть вас снова, {user.name}!",
        "user": make_user_dict(user),
    }


@router.post("/link-telegram")
async def link_telegram(
    data: LinkTelegramRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Привязывает Telegram-аккаунт по коду из бота к текущему пользователю."""
    code = data.code.strip().upper()
    result = await db.execute(select(RegistrationCode).where(RegistrationCode.code == code))
    reg_code = result.scalars().first()

    if not reg_code:
        raise HTTPException(status_code=404, detail="Код не найден или недействителен")

    # Проверяем, не привязан ли этот telegram_id уже к другому аккаунту
    conflict_res = await db.execute(
        select(User).where(User.telegram_id == reg_code.telegram_id, User.id != current_user.id)
    )
    if conflict_res.scalars().first():
        raise HTTPException(status_code=400, detail="Этот Telegram-аккаунт уже привязан к другому пользователю")

    current_user.telegram_id = reg_code.telegram_id
    current_user.telegram_username = reg_code.telegram_username
    reg_code.is_used = True
    reg_code.used_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(current_user)

    return {
        "success": True,
        "message": f"Telegram @{current_user.telegram_username or current_user.telegram_id} успешно привязан!",
        "user": make_user_dict(current_user),
    }


@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(user: User = Depends(get_current_user)):
    """Получение профиля текущего авторизованного пользователя."""
    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_mentor=user.is_mentor,
        auth_type=user.auth_type,
        telegram_id=user.telegram_id,
        telegram_username=user.telegram_username,
        created_at=user.created_at,
    )


# ---------- Telegram Direct Auth ----------

@router.post("/telegram")
async def telegram_auth(data: dict, db: AsyncSession = Depends(get_db)):
    """Авторизация через Telegram виджет с выдачей JWT."""
    try:
        telegram_id = data.get("id")
        first_name = data.get("first_name", "")
        username = data.get("username", "")

        if not telegram_id:
            raise HTTPException(status_code=400, detail="Telegram ID не получен")

        email = f"telegram_{telegram_id}@kogdaurok.local"
        name = first_name or username or f"User_{telegram_id}"

        oauth_data = OAuthLoginRequest(
            email=email,
            name=name,
            auth_type="telegram",
            telegram_id=int(telegram_id),
            telegram_username=username,
        )

        result = await oauth_login_or_register(oauth_data, db)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("❌ Telegram Auth error: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


# ---------- Регистрация и Вход по Коду ----------

@router.post("/code/generate")
async def generate_code_endpoint(data: dict, db: AsyncSession = Depends(get_db)):
    """Генерирует и сохраняет код регистрации для Telegram-бота."""
    try:
        telegram_id = data.get("telegram_id")
        telegram_username = data.get("telegram_username", "")
        code = str(data.get("code", "")).upper().strip()

        if not telegram_id or not code:
            raise HTTPException(status_code=400, detail="Не указаны обязательные параметры")

        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        if result.scalars().first():
            raise HTTPException(status_code=400, detail="Код уже существует")

        reg_code = RegistrationCode(
            code=code,
            telegram_id=int(telegram_id),
            telegram_username=telegram_username,
            is_used=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(reg_code)
        await db.commit()
        await db.refresh(reg_code)

        return {"success": True, "code": code, "message": "Код сохранён"}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


@router.post("/code/verify")
async def verify_code(data: CodeVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Проверяет валидность регистрационного кода."""
    code = data.code.strip().upper()
    result = await db.execute(
        select(RegistrationCode).where(RegistrationCode.code == code)
    )
    reg_code = result.scalars().first()

    if not reg_code:
        return {"valid": False, "message": "Код не найден"}

    return {
        "valid": True,
        "message": "Код верный",
        "telegram_username": reg_code.telegram_username,
    }


@router.post("/code/register")
async def register_with_code(data: CodeRegisterRequest, db: AsyncSession = Depends(get_db)):
    """Регистрирует пользователя по коду и выдает JWT токен (имя берется из Telegram)."""
    code = data.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Укажите код")

    result = await db.execute(
        select(RegistrationCode).where(RegistrationCode.code == code)
    )
    reg_code = result.scalars().first()
    if not reg_code:
        raise HTTPException(status_code=404, detail="Код не найден или недействителен")

    # Имя берется из Telegram профиля (или переданного значения)
    name = (data.name or "").strip() or reg_code.telegram_username or f"Пользователь {reg_code.telegram_id}"


    # Проверяем, существует ли уже пользователь с таким telegram_id
    existing_user_result = await db.execute(
        select(User).where(User.telegram_id == reg_code.telegram_id)
    )
    existing_user = existing_user_result.scalars().first()

    if existing_user:
        token = create_access_token({"sub": str(existing_user.id), "email": existing_user.email})
        return {
            "success": True,
            "access_token": token,
            "token_type": "bearer",
            "message": "Вы уже зарегистрированы!",
            "user": make_user_dict(existing_user),
            "status": "existing_user",
        }

    email = f"telegram_{reg_code.telegram_id}@kogdaurok.local"
    new_user = User(
        email=email,
        name=name,
        auth_type="telegram",
        telegram_id=reg_code.telegram_id,
        telegram_username=reg_code.telegram_username,
        password_hash=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_user)
    await db.flush()

    reg_code.is_used = True
    reg_code.used_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(new_user)

    await send_telegram_notification(reg_code.telegram_id, name, code, email)
    token = create_access_token({"sub": str(new_user.id), "email": new_user.email})

    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "message": f"Добро пожаловать, {name}!",
        "user": make_user_dict(new_user),
        "status": "new_user",
    }


@router.post("/code/login")
async def login_with_code(data: CodeLoginRequest, db: AsyncSession = Depends(get_db)):
    """Вход по коду для существующего пользователя с выдачей JWT токена."""
    code = data.code.strip().upper()
    result = await db.execute(
        select(RegistrationCode).where(RegistrationCode.code == code)
    )
    reg_code = result.scalars().first()
    if not reg_code:
        raise HTTPException(status_code=404, detail="Код не найден")

    if reg_code.telegram_id != data.telegram_id:
        raise HTTPException(status_code=403, detail="Этот код принадлежит другому Telegram аккаунту")

    user_result = await db.execute(
        select(User).where(User.telegram_id == data.telegram_id)
    )
    user = user_result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден. Пожалуйста, завершите регистрацию.",
        )

    token = create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "message": f"Добро пожаловать, {user.name}!",
        "user": make_user_dict(user),
        "status": "login_success",
    }


@router.post("/code/mark-used")
async def mark_code_used(data: dict, db: AsyncSession = Depends(get_db)):
    """Отмечает код как использованный."""
    code = str(data.get("code", "")).strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Укажите код")

    result = await db.execute(
        select(RegistrationCode).where(RegistrationCode.code == code)
    )
    reg_code = result.scalars().first()
    if not reg_code:
        raise HTTPException(status_code=404, detail="Код не найден")

    if not reg_code.is_used:
        reg_code.is_used = True
        reg_code.used_at = datetime.now(timezone.utc)
        await db.commit()

    return {"success": True, "message": "Код отмечен"}


@router.post("/check-registration")
async def check_registration(data: dict, db: AsyncSession = Depends(get_db)):
    """Проверяет регистрацию по Telegram ID."""
    telegram_id = data.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram ID не указан")

    result = await db.execute(
        select(User).where(User.telegram_id == int(telegram_id))
    )
    user = result.scalars().first()

    if user:
        return {
            "registered": True,
            "user_data": make_user_dict(user),
        }
    return {"registered": False, "user_data": {}}


@router.post("/code/get-user-code")
async def get_user_code(data: dict, db: AsyncSession = Depends(get_db)):
    """Получает последний сгенерированный код пользователя."""
    telegram_id = data.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Telegram ID не указан")

    result = await db.execute(
        select(RegistrationCode)
        .where(RegistrationCode.telegram_id == int(telegram_id))
        .order_by(RegistrationCode.created_at.desc())
        .limit(1)
    )
    reg_code = result.scalars().first()
    if not reg_code:
        raise HTTPException(status_code=404, detail="Код не найден")

    return {
        "code": reg_code.code,
        "telegram_id": telegram_id,
        "created_at": reg_code.created_at.isoformat() if reg_code.created_at else None,
        "message": "Код найден",
    }

