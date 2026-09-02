"""
Тестовая конфигурация и фикстуры для pytest.
Использует in-memory SQLite базу данных для быстрых изолированных тестов.
"""

import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

import sys
from pathlib import Path

# Добавляем корневую директорию бэкенда в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Base, User, Lesson, Homework, StudentHomework, MentorStudent, RegistrationCode
from dependencies import get_db, hash_password, create_access_token
from main import app

# In-memory SQLite для асинхронных тестов
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_db():
    """Создает таблицы базы данных для сессии тестирования."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    """Асинхронный HTTP-клиент для вызова эндпоинтов FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def test_user():
    """Создает тестового пользователя с уникальным email."""
    uid = uuid.uuid4().hex[:8]
    async with TestingSessionLocal() as session:
        user = User(
            email=f"testuser_{uid}@kogdaurok.test",
            name="Тестовый Пользователь",
            password_hash=hash_password("password123"),
            is_mentor=False,
            auth_type="email",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        token = create_access_token({"sub": str(user.id), "email": user.email})
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }


@pytest_asyncio.fixture
async def test_mentor_and_student():
    """Создает наставника и ученика со связанными записями."""
    uid = uuid.uuid4().hex[:8]
    async with TestingSessionLocal() as session:
        mentor = User(
            email=f"mentor_{uid}@kogdaurok.test",
            name="Учитель Иван",
            password_hash=hash_password("mentor123"),
            is_mentor=True,
            auth_type="email",
        )
        student = User(
            email=f"student_{uid}@kogdaurok.test",
            name="Ученик Петр",
            password_hash=hash_password("student123"),
            is_mentor=False,
            auth_type="email",
        )
        session.add_all([mentor, student])
        await session.commit()
        await session.refresh(mentor)
        await session.refresh(student)

        # Связываем наставника и ученика
        link = MentorStudent(mentor_id=mentor.id, student_id=student.id)
        session.add(link)
        await session.commit()

        m_token = create_access_token({"sub": str(mentor.id), "email": mentor.email})
        s_token = create_access_token({"sub": str(student.id), "email": student.email})

        return {
            "mentor": {
                "id": mentor.id,
                "email": mentor.email,
                "token": m_token,
                "headers": {"Authorization": f"Bearer {m_token}"},
            },
            "student": {
                "id": student.id,
                "email": student.email,
                "token": s_token,
                "headers": {"Authorization": f"Bearer {s_token}"},
            },
        }
