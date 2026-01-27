from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
import os
import sys
from pathlib import Path

# Добавь путь к проекту
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_url():
    """Получи URL из DATABASE_URL или используй дефолт"""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    return "postgresql://postgres:12345678@localhost:5432/app_bd"

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_url()

    # Если URL содержит asyncpg, замени на psycopg2 для миграций
    if "asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")

    connectable = create_engine(
        url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
