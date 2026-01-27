from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from models import (
    async_session, User, Category, RegistrationCode,
    MathProblem, InformaticsProblem,
    UserSolution, TimedAttempt, Task,
    SolveProblemRequest, TaskRequest, Variant, VariantAnswer,
    init_db
)

from fastapi import Request
from fastapi.responses import Response
from auth_service import oauth_login_or_register, OAuthLoginRequest
import re
from datetime import datetime
import asyncio
import os
from dotenv import load_dotenv
import requests
import httpx
from urllib.parse import urlencode
import logging
from fastapi.responses import JSONResponse
load_dotenv()

YANDEX_CLIENT_ID = os.getenv('YANDEX_CLIENT_ID')
YANDEX_CLIENT_SECRET = os.getenv('YANDEX_CLIENT_SECRET')
YANDEX_REDIRECT_URI = os.getenv('YANDEX_REDIRECT_URI', 'http://localhost:8000/api/auth/yandex/callback')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="PlayEx API", version="1.0.0")



@app.middleware("http")
async def universal_cors_middleware(request: Request, call_next):
    """CORS для /api/categories/?subject=math"""

    # ✅ ЛОВИ ВСЕ OPTIONS запросы (с query params!)
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        response.headers.update({
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "86400",
            "Access-Control-Allow-Credentials": "true",
        })
        return response

    # Обычные запросы
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"

    return response




@app.get("/docs")
async def get_docs():
    """Swagger docs"""
    pass

async def get_db():
    async with async_session() as session:
        yield session


def _normalize_answer(answer: str) -> str:
    return answer.strip().lower().replace(' ', '')


def _answer_to_set(answer: str) -> set:
    parts = re.split(r'[;,]', answer.strip())
    return {_normalize_answer(p) for p in parts if p.strip()}


# ============================================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================================

@app.on_event("startup")
async def startup():
    try:
        max_retries = 5
        retry_count = 0
        while retry_count < max_retries:
            try:
                await init_db()
                logger.info("✅ База данных инициализирована")
                logger.info("✅ PlayEx API запущен")
                return
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    logger.warning(f"⚠️ Попытка подключения {retry_count}/{max_retries} не удалась, ждём 2 сек...")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"❌ Не удалось подключиться к БД")
                    raise
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {str(e)}")


@app.get('/health')
async def health_check():
    return {"status": "ok", "message": "✅ API работает"}


# ============================================================================
# TELEGRAM УВЕДОМЛЕНИЯ
# ============================================================================

async def send_telegram_notification(telegram_id: int, name: str, code: str, email: str):
    """Отправляет уведомление о регистрации в Telegram"""
    try:
        message_text = (
            f"🎉 <b>Поздравляем!</b>\n\n"
            f"✅ Вы успешно зарегистрировались на <b>PlayEx</b>\n\n"
            f"👤 <b>Имя:</b> {name}\n"
            f"📧 <b>Email:</b> {email}\n"
            f"🔐 <b>Ваш код доступа:</b> <code>{code}</code>\n\n"
            f"⏰ <b>Время:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💡 Сохраните этот код - он нужен для входа на других устройствах\n\n"
            f"🎉 Спасибо что выбрал PlayEx!\n"
            f"Начни решать задачи и прогрессируй 🚀"
        )

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": message_text,
                    "parse_mode": "HTML"
                }
            )
            if response.status_code == 200:
                logger.info(f"✅ Уведомление отправлено {telegram_id}")
                return True
            else:
                logger.error(f"❌ Ошибка Telegram: {response.text}")
                return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return False


# ============================================================================
# YANDEX OAUTH
# ============================================================================

@app.get('/api/auth/yandex/url')
async def get_yandex_auth_url():
    """Получить URL для авторизации Yandex"""
    try:
        params = {
            'client_id': YANDEX_CLIENT_ID,
            'redirect_uri': YANDEX_REDIRECT_URI,
            'response_type': 'code',
            'state': 'random_state_value'
        }
        auth_url = f'https://oauth.yandex.ru/authorize?{urlencode(params)}'
        return {"auth_url": auth_url}
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/auth/yandex/callback')
async def yandex_callback(code: str, state: str | None = None, db: AsyncSession = Depends(get_db)):
    """Обработка callback от Yandex"""
    try:
        if not code:
            return RedirectResponse(url=f"{FRONTEND_URL}/?auth_error=true&message=Code+not+received", status_code=302)

        token_url = 'https://oauth.yandex.ru/token'
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': YANDEX_CLIENT_ID,
            'client_secret': YANDEX_CLIENT_SECRET
        }

        token_response = requests.post(token_url, data=token_data, timeout=10)
        token_response.raise_for_status()
        tokens = token_response.json()
        access_token = tokens.get('access_token')

        if not access_token:
            return RedirectResponse(url=f"{FRONTEND_URL}/?auth_error=true&message=Token+not+received", status_code=302)

        user_info_url = 'https://login.yandex.ru/info'
        user_info_response = requests.get(
            user_info_url,
            headers={'Authorization': f'OAuth {access_token}'},
            timeout=10
        )
        user_info_response.raise_for_status()
        user_info = user_info_response.json()

        email = user_info.get('default_email') or (
            user_info.get('emails')[0] if user_info.get('emails') else None
        )
        if not email:
            email = f"yandex_{user_info.get('id')}@playex.local"

        name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
        if not name:
            name = email.split('@')[0]

        oauth_data = OAuthLoginRequest(
            email=email,
            name=name,
            auth_type='yandex',
            yandex_id=str(user_info.get('id'))
        )

        result = await oauth_login_or_register(oauth_data, db)
        logger.info(f"✅ Yandex: {result['email']}")

        return RedirectResponse(
            url=f"{FRONTEND_URL}/?auth_success=true&email={result['email']}",
            status_code=302
        )
    except Exception as e:
        logger.error(f"❌ Yandex ошибка: {str(e)}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?auth_error=true&message=Yandex+error",
            status_code=302
        )


# ============================================================================
# TELEGRAM DIRECT AUTH
# ============================================================================

@app.post('/api/auth/telegram')
async def telegram_auth(data: dict, db: AsyncSession = Depends(get_db)):
    """Авторизация через Telegram"""
    try:
        telegram_id = data.get('id')
        first_name = data.get('first_name', '')
        username = data.get('username', '')

        if not telegram_id:
            raise HTTPException(status_code=400, detail='❌ Telegram ID не получен')

        email = f"telegram_{telegram_id}@playex.local"
        name = first_name or username or f"User_{telegram_id}"

        oauth_data = OAuthLoginRequest(
            email=email,
            name=name,
            auth_type='telegram',
            telegram_id=telegram_id,
            telegram_username=username
        )

        result = await oauth_login_or_register(oauth_data, db)
        logger.info(f"✅ Telegram: {result['email']}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# РЕГИСТРАЦИЯ И ВХОД ПО КОДУ
# ============================================================================

@app.post('/api/auth/code/generate')
async def generate_code_endpoint(data: dict, db: AsyncSession = Depends(get_db)):
    """Генерирует и сохраняет код регистрации"""
    try:
        telegram_id = data.get('telegram_id')
        telegram_username = data.get('telegram_username', '')
        code = data.get('code', '').upper()

        if not telegram_id or not code:
            raise HTTPException(status_code=400, detail='❌ Не указаны параметры')

        # Проверяем что код не существует
        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        if result.scalars().first():
            raise HTTPException(status_code=400, detail='❌ Код уже существует')

        # Сохраняем код
        reg_code = RegistrationCode(
            code=code,
            telegram_id=telegram_id,
            telegram_username=telegram_username,
            is_used=False,
            created_at=datetime.utcnow()
        )
        db.add(reg_code)
        await db.commit()
        await db.refresh(reg_code)

        logger.info(f"✅ Код {code} сгенерирован")
        return {
            "success": True,
            "code": code,
            "message": "✅ Код сохранён"
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/auth/code/verify')
async def verify_code(data: dict, db: AsyncSession = Depends(get_db)):
    """✅ Проверяет валидность кода (для любого использования)"""
    try:
        code = data.get('code', '').strip().upper()

        if not code or len(code) < 4:
            raise HTTPException(status_code=400, detail='❌ Укажите код')

        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        reg_code = result.scalars().first()

        if not reg_code:
            return {"valid": False, "message": "❌ Код не найден"}

        return {
            "valid": True,
            "message": f"✅ Код верный!",
            "telegram_username": reg_code.telegram_username
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/auth/code/register')
async def register_with_code(data: dict, db: AsyncSession = Depends(get_db)):
    """✅ Регистрирует НОВЫХ пользователей по коду"""
    try:
        code = data.get('code', '').strip().upper()
        name = data.get('name', '').strip()

        if not code or not name:
            raise HTTPException(status_code=400, detail='❌ Укажите код и имя')

        # Ищем код
        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        reg_code = result.scalars().first()

        if not reg_code:
            raise HTTPException(status_code=404, detail='❌ Код не найден')

        # ✅ ПРОВЕРЯЕМ: уже ли этот пользователь зарегистрирован?
        existing_user_result = await db.execute(
            select(User).where(User.telegram_id == reg_code.telegram_id)
        )
        existing_user = existing_user_result.scalars().first()

        if existing_user:
            # Пользователь уже зарегистрирован - это вход, не регистрация
            return {
                "success": True,
                "message": "ℹ️ Вы уже зарегистрированы!",
                "email": existing_user.email,
                "name": existing_user.name,
                "status": "existing_user",
                "telegram_id": reg_code.telegram_id
            }

        # НОВАЯ РЕГИСТРАЦИЯ
        email = f"telegram_{reg_code.telegram_id}@playex.local"

        # Проверяем что такой email не существует
        email_check = await db.execute(
            select(User).where(User.email == email)
        )
        if email_check.scalars().first():
            raise HTTPException(status_code=400, detail='❌ Пользователь уже существует')

        # Создаём нового пользователя
        new_user = User(
            email=email,
            name=name,
            auth_type='telegram',
            telegram_id=reg_code.telegram_id,
            telegram_username=reg_code.telegram_username,
            password_hash=None,
            created_at=datetime.utcnow()
        )
        db.add(new_user)
        await db.flush()

        # ✅ ОТМЕЧАЕМ КОД КАК ИСПОЛЬЗОВАННЫЙ (ТОЛЬКО ДЛЯ НОВОЙ РЕГИСТРАЦИИ!)
        reg_code.is_used = True
        reg_code.used_at = datetime.utcnow()
        await db.commit()

        # Отправляем уведомление в Telegram
        await send_telegram_notification(reg_code.telegram_id, name, code, email)

        logger.info(f"✅ Новый пользователь {email} зарегистрирован")

        return {
            "success": True,
            "message": f"✓ Добро пожаловать, {name}!",
            "email": email,
            "name": name,
            "status": "new_user",
            "telegram_id": reg_code.telegram_id
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/auth/code/login')
async def login_with_code(data: dict, db: AsyncSession = Depends(get_db)):
    """✅ Вход СУЩЕСТВУЮЩЕГО пользователя по коду (НЕ отмечает как использованный)"""
    try:
        code = data.get('code', '').strip().upper()
        telegram_id = data.get('telegram_id')

        if not code or not telegram_id:
            raise HTTPException(status_code=400, detail='❌ Укажите код')

        # Проверяем существует ли код
        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        reg_code = result.scalars().first()

        if not reg_code:
            raise HTTPException(status_code=404, detail='❌ Код не найден')

        # ✅ НЕ ПРОВЕРЯЕМ is_used! Код можно использовать бесконечно для входа

        # Проверяем что код принадлежит этому пользователю
        if reg_code.telegram_id != telegram_id:
            raise HTTPException(status_code=403, detail='❌ Этот код не ваш')

        # Получаем пользователя
        user_result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден. Сначала зарегистрируйтесь.')

        logger.info(f"✅ Вход: {user.email}")

        return {
            "success": True,
            "message": f"✓ Добро пожаловать, {user.name}!",
            "email": user.email,
            "name": user.name,
            "status": "login_success"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/auth/code/mark-used')
async def mark_code_used(data: dict, db: AsyncSession = Depends(get_db)):
    """Отмечает код как использованный (опционально)"""
    try:
        code = data.get('code', '').strip().upper()

        if not code:
            raise HTTPException(status_code=400, detail='❌ Укажите код')

        result = await db.execute(
            select(RegistrationCode).where(RegistrationCode.code == code)
        )
        reg_code = result.scalars().first()

        if not reg_code:
            raise HTTPException(status_code=404, detail='❌ Код не найден')

        if not reg_code.is_used:
            reg_code.is_used = True
            reg_code.used_at = datetime.utcnow()
            await db.commit()

        logger.info(f"✅ Код отмечен")

        return {
            "success": True,
            "message": "✅ Код отмечен"
        }

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# ПРОВЕРКА РЕГИСТРАЦИИ И ПОЛУЧЕНИЕ КОДА (для бота)
# ============================================================================

@app.post('/api/auth/check-registration')
async def check_registration(data: dict, db: AsyncSession = Depends(get_db)):
    """Проверяет: зарегистрирован ли пользователь по Telegram ID"""
    try:
        telegram_id = data.get('telegram_id')

        if not telegram_id:
            raise HTTPException(status_code=400, detail='❌ Telegram ID не указан')

        result = await db.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalars().first()

        if user:
            return {
                "registered": True,
                "user_data": {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "telegram_id": user.telegram_id,
                    "created_at": user.created_at.isoformat() if user.created_at else None
                }
            }
        else:
            return {
                "registered": False,
                "user_data": {}
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/auth/code/get-user-code')
async def get_user_code(data: dict, db: AsyncSession = Depends(get_db)):
    """✅ Получает КОД ПОЛЬЗОВАТЕЛЯ (первый найденный, а не только использованный)"""
    try:
        telegram_id = data.get('telegram_id')

        if not telegram_id:
            raise HTTPException(status_code=400, detail='❌ Telegram ID не указан')

        # ✅ ИЩЕМ ЛЮБОЙ КОД, НЕЗАВИСИМО ОТ СТАТУСА is_used
        result = await db.execute(
            select(RegistrationCode)
            .where(RegistrationCode.telegram_id == telegram_id)
            .order_by(RegistrationCode.created_at.desc())
            .limit(1)
        )
        reg_code = result.scalars().first()

        if not reg_code:
            raise HTTPException(status_code=404, detail='❌ Код не найден')

        return {
            "code": reg_code.code,
            "telegram_id": telegram_id,
            "created_at": reg_code.created_at.isoformat() if reg_code.created_at else None,
            "message": "✅ Код найден"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ
# ============================================================================

@app.get('/api/profile/email/{email}')
async def get_profile_email(email: str, db: AsyncSession = Depends(get_db)):
    """Получить профиль пользователя"""
    try:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "level": user.level
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.put('/api/profile/update')
async def update_profile(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Обновить профиль пользователя"""
    try:
        email = request.headers.get('X-EMAIL')
        new_name = data.get('name')

        if not new_name or not email:
            raise HTTPException(status_code=400, detail='❌ Ошибка')

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        user.name = new_name
        await db.commit()
        await db.refresh(user)

        return {"id": user.id, "name": user.name, "message": "✅ Имя обновлено"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# СТАТИСТИКА
# ============================================================================

@app.get('/api/stats/email/{email}')
async def get_stats_email(email: str, db: AsyncSession = Depends(get_db)):
    """Получить статистику пользователя"""
    try:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        total_solved = await db.scalar(
            select(func.count(UserSolution.id)).where(
                and_(UserSolution.user_id == user.id, UserSolution.is_correct == True)
            )
        ) or 0

        math_solved = await db.scalar(
            select(func.count(UserSolution.id)).where(
                and_(UserSolution.user_id == user.id, UserSolution.is_correct == True,
                     UserSolution.subject == "math")
            )
        ) or 0

        informatics_solved = await db.scalar(
            select(func.count(UserSolution.id)).where(
                and_(UserSolution.user_id == user.id, UserSolution.is_correct == True,
                     UserSolution.subject == "informatics")
            )
        ) or 0

        return {
            "id": user.id,
            "level": user.level,
            "solved_count": int(total_solved),
            "math_solved": int(math_solved),
            "informatics_solved": int(informatics_solved),
            "solved_problems": []
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.get('/api/timed-stats/')
async def get_timed_stats(subject: str = None, request: Request = None, db: AsyncSession = Depends(get_db)):
    """Получить статистику по задачам с ограничением времени"""
    try:
        email = request.headers.get('X-EMAIL') if request else None

        if not email:
            return {
                "total_attempts": 0,
                "correct_answers": 0,
                "incorrect_answers": 0,
                "success_rate": 0,
                "avg_problems_per_minute": 0,
                "total_time_seconds": 0
            }

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            return {
                "total_attempts": 0,
                "correct_answers": 0,
                "incorrect_answers": 0,
                "success_rate": 0,
                "avg_problems_per_minute": 0,
                "total_time_seconds": 0
            }

        query = select(TimedAttempt).where(TimedAttempt.user_id == user.id)
        if subject:
            query = query.where(TimedAttempt.subject == subject)

        result = await db.execute(query)
        attempts = result.scalars().all()

        total_attempts = len(attempts)
        correct = sum(1 for a in attempts if a.is_correct)
        incorrect = total_attempts - correct
        total_time = sum(a.time_spent_seconds for a in attempts)
        success_rate = (correct / total_attempts * 100) if total_attempts > 0 else 0
        avg_per_minute = (total_attempts / (total_time / 60)) if total_time > 0 else 0

        return {
            "total_attempts": total_attempts,
            "correct_answers": correct,
            "incorrect_answers": incorrect,
            "success_rate": round(success_rate, 2),
            "avg_problems_per_minute": round(avg_per_minute, 2),
            "total_time_seconds": total_time
        }

    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# КАТЕГОРИИ
# ============================================================================

@app.get('/api/categories/')
async def get_categories(subject: str = None, db: AsyncSession = Depends(get_db)):
    """Получить категории задач"""
    try:
        query = select(Category)
        if subject:
            query = query.where(Category.subject == subject)

        result = await db.execute(query)
        categories = result.scalars().all()

        return [{"id": c.id, "name": c.name, "subject": c.subject} for c in categories]

    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# ЗАДАЧИ - ПОЛУЧЕНИЕ
# ============================================================================

@app.get('/api/problems/math/')
async def get_math_problems(difficulty: str = None, category_id: int = None, db: AsyncSession = Depends(get_db)):
    """Получить задачи по математике"""
    try:
        query = select(MathProblem)
        conditions = []

        if difficulty:
            conditions.append(MathProblem.difficulty == difficulty)
        if category_id:
            conditions.append(MathProblem.category_id == category_id)

        if conditions:
            query = query.where(and_(*conditions))

        result = await db.execute(query)
        problems = result.scalars().all()

        return [
            {
                "id": p.id,
                "title": p.title,
                "subject": "math",
                "difficulty": p.difficulty,
                "category_id": p.category_id,
                "solution": p.solution,
                "correct_answer": p.correct_answer,
                "points": p.points,
                "problem_image": p.problem_image,
                "problem_image_type": p.problem_image_type,
                "solution_image": p.solution_image,
                "solution_image_type": p.solution_image_type
            }
            for p in problems
        ]

    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.get('/api/problems/informatics/')
async def get_informatics_problems(difficulty: str = None, category_id: int = None, db: AsyncSession = Depends(get_db)):
    """Получить задачи по информатике"""
    try:
        query = select(InformaticsProblem)
        conditions = []

        if difficulty:
            conditions.append(InformaticsProblem.difficulty == difficulty)
        if category_id:
            conditions.append(InformaticsProblem.category_id == category_id)

        if conditions:
            query = query.where(and_(*conditions))

        result = await db.execute(query)
        problems = result.scalars().all()

        return [
            {
                "id": p.id,
                "title": p.title,
                "subject": "informatics",
                "difficulty": p.difficulty,
                "category_id": p.category_id,
                "solution": p.solution,
                "correct_answer": p.correct_answer,
                "points": p.points,
                "problem_image": p.problem_image,
                "problem_image_type": p.problem_image_type,
                "solution_image": p.solution_image,
                "solution_image_type": p.solution_image_type
            }
            for p in problems
        ]

    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# РЕШЕНИЕ ЗАДАЧ
# ============================================================================

@app.post('/api/solve/')
async def solve_problem(data: SolveProblemRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Решить задачу"""
    try:
        email = request.headers.get('X-EMAIL')

        if not email:
            raise HTTPException(status_code=400, detail='❌ Не авторизованы')

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        if data.subject == "math":
            result = await db.execute(select(MathProblem).where(MathProblem.id == data.problem_id))
        else:
            result = await db.execute(select(InformaticsProblem).where(InformaticsProblem.id == data.problem_id))

        problem = result.scalars().first()

        if not problem:
            raise HTTPException(status_code=404, detail='❌ Задача не найдена')

        # Проверяем что задача не решена
        result = await db.execute(
            select(UserSolution).where(
                and_(
                    UserSolution.user_id == user.id,
                    UserSolution.subject == data.subject,
                    UserSolution.problem_id == data.problem_id,
                    UserSolution.is_correct == True
                )
            )
        )

        if result.scalars().first():
            return {
                "correct": False,
                "already_solved": True,
                "message": "Вы уже решили эту задачу",
                "correct_answer": None
            }

        # Проверяем ответ
        correct_raw = problem.correct_answer or ""

        if re.search(r'[;,]', correct_raw):
            is_correct = _answer_to_set(data.user_answer) == _answer_to_set(correct_raw)
        else:
            is_correct = _normalize_answer(data.user_answer) == _normalize_answer(correct_raw)

        # Сохраняем решение
        solution = UserSolution(
            user_id=user.id,
            subject=data.subject,
            problem_id=data.problem_id,
            user_answer=data.user_answer,
            is_correct=is_correct
        )
        db.add(solution)
        await db.commit()

        return {
            "correct": is_correct,
            "correct_answer": None if is_correct else problem.correct_answer,
            "message": "✅ Верно!" if is_correct else "❌ Неверно"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/timed-attempt/')
async def save_timed_attempt(data: dict, request: Request, db: AsyncSession = Depends(get_db)):
    """Сохранить попытку решения задачи с ограничением времени"""
    try:
        email = request.headers.get('X-EMAIL')

        if not email:
            raise HTTPException(status_code=400, detail='❌ Не авторизованы')

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        attempt = TimedAttempt(
            user_id=user.id,
            subject=data.get('subject'),
            problem_id=data.get('problem_id'),
            user_answer=data.get('user_answer'),
            is_correct=data.get('is_correct', False),
            time_spent_seconds=data.get('time_spent_seconds', 0)
        )
        db.add(attempt)
        await db.commit()

        return {
            "success": True,
            "message": "✅ Попытка сохранена"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ============================================================================
# ЗАДАЧИ ПОЛЬЗОВАТЕЛЯ
# ============================================================================

@app.get('/api/tasks/')
async def get_tasks(request: Request, db: AsyncSession = Depends(get_db)):
    """Получить список задач пользователя"""
    try:
        email = request.headers.get('X-EMAIL')

        if not email:
            raise HTTPException(status_code=400, detail='❌ Не авторизованы')

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        result = await db.execute(select(Task).where(Task.user_id == user.id))
        tasks = result.scalars().all()

        return [
            {
                "id": t.id,
                "title": t.title,
                "is_completed": t.is_completed,
                "created_at": t.created_at
            }
            for t in tasks
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/tasks/')
async def create_task(data: TaskRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Создать новую задачу"""
    try:
        email = request.headers.get('X-EMAIL')

        if not email:
            raise HTTPException(status_code=400, detail='❌ Не авторизованы')

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail='❌ Пользователь не найден')

        task = Task(
            user_id=user.id,
            title=data.title,
            is_completed=False
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        return {
            "id": task.id,
            "title": task.title,
            "is_completed": task.is_completed,
            "message": "✅ Задача создана"
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.patch('/api/tasks/{task_id}/complete')
async def complete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Отметить задачу как выполненную"""
    try:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalars().first()

        if not task:
            raise HTTPException(status_code=404, detail='❌ Задача не найдена')

        task.is_completed = True
        await db.commit()

        return {"id": task.id, "is_completed": task.is_completed, "message": "✅ Задача отмечена"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.delete('/api/tasks/{task_id}')
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Удалить задачу"""
    try:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalars().first()

        if not task:
            raise HTTPException(status_code=404, detail='❌ Задача не найдена')

        await db.delete(task)
        await db.commit()

        return {"success": True, "message": "✅ Задача удалена"}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


import json
import uuid


@app.post('/api/variants/')
async def create_variant(data: dict, db: AsyncSession = Depends(get_db)):
    """Создать вариант с выбранными задачами"""
    try:
        subject = data.get('subject')
        config = data.get('config', [])

        if not subject or not config:
            raise HTTPException(status_code=400, detail='❌ Неверные параметры')

        # Собираем задачи согласно конфигу
        problems_list = []

        for cat_config in config:
            category_id = cat_config.get('category_id')
            count = cat_config.get('count', 0)
            difficulties = cat_config.get('difficulties', {})

            if count <= 0:
                continue

            # Строим список сложностей которые включены
            enabled_difficulties = []
            if difficulties.get('easy', True):
                enabled_difficulties.append('easy')
            if difficulties.get('medium', True):
                enabled_difficulties.append('medium')
            if difficulties.get('hard', True):
                enabled_difficulties.append('hard')

            if not enabled_difficulties:
                continue

            # Получаем все задачи с включёнными сложностями
            if subject == 'math':
                query = select(MathProblem).where(
                    and_(
                        MathProblem.category_id == category_id,
                        MathProblem.difficulty.in_(enabled_difficulties)
                    )
                )
            else:
                query = select(InformaticsProblem).where(
                    and_(
                        InformaticsProblem.category_id == category_id,
                        InformaticsProblem.difficulty.in_(enabled_difficulties)
                    )
                )

            result = await db.execute(query)
            all_problems = result.scalars().all()

            if not all_problems:
                logger.warning(f"⚠️ Нет задач в категории {category_id} с выбранными сложностями")
                continue

            # Выбираем случайно нужное количество
            import random
            selected_count = min(count, len(all_problems))
            selected = random.sample(list(all_problems), selected_count)
            problems_list.extend([p.id for p in selected])

        if not problems_list:
            raise HTTPException(status_code=400, detail='❌ Нет задач по выбранным критериям')

        # Создаём вариант
        variant_token = str(uuid.uuid4())[:12]
        variant = Variant(
            user_id=None,  # Гость
            subject=subject,
            variant_token=variant_token,
            problems_data=json.dumps(problems_list),
            completed=False
        )

        db.add(variant)
        await db.commit()
        await db.refresh(variant)

        return {
            "variant_id": variant.id,
            "variant_token": variant_token,
            "problems_count": len(problems_list)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.get('/api/variants/{variant_id}/')
async def get_variant(variant_id: int, db: AsyncSession = Depends(get_db)):
    """Получить вариант с задачами"""
    try:
        result = await db.execute(select(Variant).where(Variant.id == variant_id))
        variant = result.scalars().first()

        if not variant:
            raise HTTPException(status_code=404, detail='❌ Вариант не найден')

        # Получаем задачи
        problems_ids = json.loads(variant.problems_data)
        problems = []

        for problem_id in problems_ids:
            if variant.subject == 'math':
                result = await db.execute(select(MathProblem).where(MathProblem.id == problem_id))
                problem = result.scalars().first()
            else:
                result = await db.execute(select(InformaticsProblem).where(InformaticsProblem.id == problem_id))
                problem = result.scalars().first()

            if problem:
                problems.append({
                    "id": problem.id,
                    "title": problem.title,
                    "difficulty": problem.difficulty,
                    "solution": problem.solution,
                    "correct_answer": problem.correct_answer,
                    "points": problem.points,
                    "problem_image": problem.problem_image,
                    "problem_image_type": problem.problem_image_type,
                    "solution_image": problem.solution_image,
                    "solution_image_type": problem.solution_image_type
                })

        return {
            "id": variant.id,
            "subject": variant.subject,
            "problems": problems,
            "completed": variant.completed,
            "created_at": variant.created_at
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/variants/{variant_id}/submit/')
async def submit_variant_answer(variant_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """Отправить ответ на задачу варианта"""
    try:
        problem_id = data.get('problem_id')
        user_answer = data.get('user_answer', '').strip()

        # Получаем вариант и задачу
        result = await db.execute(select(Variant).where(Variant.id == variant_id))
        variant = result.scalars().first()

        if not variant:
            raise HTTPException(status_code=404, detail='❌ Вариант не найден')

        # Получаем задачу
        if variant.subject == 'math':
            result = await db.execute(select(MathProblem).where(MathProblem.id == problem_id))
            problem = result.scalars().first()
        else:
            result = await db.execute(select(InformaticsProblem).where(InformaticsProblem.id == problem_id))
            problem = result.scalars().first()

        if not problem:
            raise HTTPException(status_code=404, detail='❌ Задача не найдена')

        # Проверяем ответ
        is_correct = _normalize_answer(user_answer) == _normalize_answer(problem.correct_answer)

        # Сохраняем ответ
        answer = VariantAnswer(
            variant_id=variant_id,
            problem_id=problem_id,
            user_answer=user_answer,
            is_correct=is_correct
        )

        db.add(answer)
        await db.commit()

        return {
            "correct": is_correct,
            "correct_answer": problem.correct_answer if not is_correct else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.post('/api/variants/{variant_id}/complete/')
async def complete_variant(variant_id: int, db: AsyncSession = Depends(get_db)):
    """Завершить решение варианта"""
    try:
        result = await db.execute(select(Variant).where(Variant.id == variant_id))
        variant = result.scalars().first()

        if not variant:
            raise HTTPException(status_code=404, detail='❌ Вариант не найден')

        variant.completed = True
        await db.commit()

        return {"status": "ok", "message": "✅ Вариант завершён"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


@app.get('/api/variants/{variant_id}/results/')
async def get_variant_results(variant_id: int, db: AsyncSession = Depends(get_db)):
    """Получить результаты варианта"""
    try:
        # Получаем все ответы
        result = await db.execute(
            select(VariantAnswer).where(VariantAnswer.variant_id == variant_id)
        )
        answers = result.scalars().all()

        results = {}
        correct_count = 0

        for answer in answers:
            results[answer.problem_id] = {
                "user_answer": answer.user_answer,
                "correct": answer.is_correct
            }
            if answer.is_correct:
                correct_count += 1

        return {
            "results": results,
            "correct_count": correct_count,
            "incorrect_count": len(answers) - correct_count,
            "total_count": len(answers)
        }

    except Exception as e:
        logger.error(f"❌ Ошибка: {str(e)}")
        raise HTTPException(status_code=500, detail=f'❌ Ошибка: {str(e)}')


# ===== GITHUB DEPLOYMENT WEBHOOK =====

GITHUB_SECRET = os.getenv('GITHUB_SECRET', 'your-secret-here')

import subprocess
import hmac
import hashlib
import os

@app.post('/webhook')
async def github_webhook(request: Request):
    """GitHub webhook для автоматического deployment"""
    try:
        # Получи тело запроса
        body = await request.body()

        # Проверь подпись
        signature = request.headers.get('X-Hub-Signature-256', '')
        expected_signature = 'sha256=' + hmac.new(
            GITHUB_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            logger.error("❌ Invalid GitHub webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Распарси JSON
        payload = await request.json()
        event = request.headers.get('X-GitHub-Event', '')

        logger.info(f"🔔 GitHub webhook received: {event}")
        logger.info(f"   Ref: {payload.get('ref', 'unknown')}")

        # Запусти deployment только для push в main
        if event == 'push' and payload.get('ref') == 'refs/heads/main':
            logger.info("🚀 Triggering deployment...")

            # Запусти скрипт в фоне (не блокируем ответ)
            subprocess.Popen(['/bin/bash', '/home/artem/test2/deploy.sh'])

            return {
                "status": "deployment_triggered",
                "message": "✅ Deployment started",
                "event": event
            }
        else:
            logger.info("⏭️  Skipping deployment (not main branch push)")
            return {
                "status": "skipped",
                "message": "Event skipped",
                "event": event
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
