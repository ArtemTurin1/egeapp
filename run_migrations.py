#!/usr/bin/env python3
"""Script to run migrations synchronously"""

import os
import sys
from alembic import command
from alembic.config import Config


def run_migrations():
    """Run database migrations"""
    try:
        # Инициализируй конфиг алембика
        alembic_cfg = Config("alembic.ini")

        # Используй переменную окружения для синхронного подключения
        db_url = os.getenv("DATABASE_URL_SYNC")
        if not db_url:
            # Fallback на асинхронный если синхронный не установлен
            # но замени asyncpg на psycopg2
            async_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/test2_db")
            db_url = async_url.replace("postgresql+asyncpg://", "postgresql://")

        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        # Запусти миграции
        print(f"🔄 Running migrations with URL: {db_url.split('@')[1] if '@' in db_url else 'unknown'}")
        command.upgrade(alembic_cfg, "head")
        print("✅ Migrations completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_migrations()
    sys.exit(0 if success else 1)
