"""
КогдаУрок API — точка входа приложения.
Модульная архитектура, строгая валидация, JWT-аутентификация и CORS.
"""

import time
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_logger, FRONTEND_URL
from models import (
    async_session,
    init_db,
)
from bot import run_bot_polling
from routers import auth, profile, homework, upload, webhook, schedule
import os
from pathlib import Path

logger = get_logger(__name__)

# Директория со статическими файлами
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# LIFESPAN
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте и завершение работы."""
    bot_task = None
    try:
        await init_db()
        logger.info("✅ База данных инициализирована")
        
        # Создаем директорию для загрузок, если её нет
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        # Запуск Telegram-бота в фоне
        bot_task = asyncio.create_task(run_bot_polling())
        
        logger.info("✅ КогдаУрок API успешно запущен")
    except Exception as e:
        logger.warning("⚠️ Предупреждение при авто-инициализации БД: %s", e)

    yield

    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    logger.info("🛑 КогдаУрок API завершает работу")


# ============================================================================
# ПРИЛОЖЕНИЕ
# ============================================================================

app = FastAPI(
    title="КогдаУрок API",
    description="Образовательная платформа для занятий с наставниками и управления расписанием.",
    version="2.0.0",
    lifespan=lifespan,
)

# ---------- Официальный CORS Middleware ----------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        FRONTEND_URL,
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Статические файлы ----------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------- Request Logging Middleware ----------

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


# ---------- Health Check ----------

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "КогдаУрок API", "version": "2.0.0"}


# ---------- Подключение роутеров ----------

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(homework.router)
app.include_router(upload.router)
app.include_router(webhook.router)
app.include_router(schedule.router)

