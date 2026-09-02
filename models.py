"""
SQLAlchemy ORM модели базы данных КогдаУрок (Teacher-Student Platform).
"""

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    ForeignKey,
    String,
    Integer,
    BigInteger,
    Text,
    Boolean,
    DateTime,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine

from config import DATABASE_URL

engine = create_async_engine(url=DATABASE_URL, echo=False)
async_session = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


# ============================================================================
# ПОЛЬЗОВАТЕЛИ И АУТЕНТИФИКАЦИЯ
# ============================================================================

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_mentor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    auth_type: Mapped[str] = mapped_column(String(50), default="email")
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class RegistrationCode(Base):
    __tablename__ = "registration_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ============================================================================
# НАСТАВНИКИ И ДОМАШНИЕ ЗАДАНИЯ
# ============================================================================

class MentorStudent(Base):
    __tablename__ = "mentor_students"
    __table_args__ = (UniqueConstraint("mentor_id", "student_id", name="uq_mentor_student"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    mentor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(primary_key=True)
    mentor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachments: Mapped[str] = mapped_column(Text, nullable=False, default="[]") # JSON list of URLs
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


class StudentHomework(Base):
    __tablename__ = "student_homeworks"

    id: Mapped[int] = mapped_column(primary_key=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("homeworks.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    student_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    student_attachments: Mapped[str] = mapped_column(Text, nullable=False, default="[]") # JSON list of URLs
    
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ============================================================================
# РАСПИСАНИЕ И УРОКИ
# ============================================================================

class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    mentor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False, default="Математика")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    lesson_link: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    
    notified_1h: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_15m: Mapped[bool] = mapped_column(Boolean, default=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


async def init_db():
    """Создание всех таблиц и авто-миграция схемы."""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Удаляем устаревшие колонки из существующих БД
        try:
            await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS level;"))
            # Удаляем старые таблицы если они остались
            await conn.execute(
                text("DROP TABLE IF EXISTS math_problems, informatics_problems, physics_problems, categories, variants, variant_problems, solved_problems, user_tasks, homework_cart CASCADE;")
            )
        except Exception:
            pass

