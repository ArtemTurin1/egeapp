from sqlalchemy import ForeignKey, String, Integer, Text, Boolean, DateTime, Float
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql+asyncpg://postgres:postgres@localhost:5432/app_bd')

engine = create_async_engine(url=DATABASE_URL, echo=False)
async_session = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=True)

    # OAuth поля
    auth_type: Mapped[str] = mapped_column(String(50), default='yandex')  # 'yandex', 'telegram'
    yandex_id: Mapped[str] = mapped_column(String(256), nullable=True, unique=True)
    telegram_id: Mapped[int] = mapped_column(Integer, nullable=True, unique=True)
    telegram_username: Mapped[str] = mapped_column(String(128), nullable=True)



class RegistrationCode(Base):
    __tablename__ = 'registration_codes'

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    telegram_id: Mapped[int] = mapped_column(Integer, nullable=False)
    telegram_username: Mapped[str] = mapped_column(String(128), nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    used_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Category(Base):
    __tablename__ = 'categories'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)


class MathProblem(Base):
    __tablename__ = 'math_problems'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=True)
    correct_answer: Mapped[str] = mapped_column(String(256), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=1)
    problem_image: Mapped[str] = mapped_column(Text, nullable=True)
    problem_image_type: Mapped[str] = mapped_column(String(50), default='image/jpeg')
    solution_image: Mapped[str] = mapped_column(Text, nullable=True)
    solution_image_type: Mapped[str] = mapped_column(String(50), default='image/jpeg')


class InformaticsProblem(Base):
    __tablename__ = 'informatics_problems'

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    solution: Mapped[str] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=True)
    correct_answer: Mapped[str] = mapped_column(String(256), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=1)
    problem_image: Mapped[str] = mapped_column(Text, nullable=True)
    problem_image_type: Mapped[str] = mapped_column(String(50), default='image/jpeg')
    solution_image: Mapped[str] = mapped_column(Text, nullable=True)
    solution_image_type: Mapped[str] = mapped_column(String(50), default='image/jpeg')


class UserSolution(Base):
    __tablename__ = 'user_solutions'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_answer: Mapped[str] = mapped_column(String(256), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    solved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TimedAttempt(Base):
    __tablename__ = 'timed_attempts'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_answer: Mapped[str] = mapped_column(String(256), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Task(Base):
    __tablename__ = 'tasks'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Variant(Base):
    __tablename__ = 'variants'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=True)  # Может быть null для гостей
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    variant_token: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # Уникальный токен варианта
    problems_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON с ID задач
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VariantAnswer(Base):
    __tablename__ = 'variant_answers'

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey('variants.id'), nullable=False)
    problem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_answer: Mapped[str] = mapped_column(String(256), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ===== PYDANTIC MODELS =====

class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class SolveProblemRequest(BaseModel):
    subject: str
    problem_id: int
    user_answer: str


class SolveProblemResponse(BaseModel):
    correct: bool
    correct_answer: Optional[str] = None
    message: str
    already_solved: Optional[bool] = False


class TaskRequest(BaseModel):
    title: str


class CreateProblemRequest(BaseModel):
    title: str
    solution: Optional[str] = None
    difficulty: str
    category_id: Optional[int] = None
    correct_answer: str
    points: int = 1
    problem_image: Optional[str] = None
    problem_image_type: Optional[str] = None
    solution_image: Optional[str] = None
    solution_image_type: Optional[str] = None
    solution_image_description: Optional[str] = None


async def init_db():
    """Создание всех таблиц"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ База данных инициализирована")