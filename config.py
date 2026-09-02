"""
Конфигурация приложения КогдаУрок.
Все переменные окружения загружаются здесь.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# --- База данных ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/app_bd",
)

# --- JWT Аутентификация ---
JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    "kogdaurok_super_secret_jwt_key_change_in_production_2026_x99",
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200"))  # 30 days



# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY", os.getenv("HTTPS_PROXY", ""))

# --- Frontend ---
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# --- GitHub Webhook ---
GITHUB_SECRET = os.getenv("GITHUB_SECRET", "")

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
