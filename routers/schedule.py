"""
Роутер расписания и управления уроками КогдаУрок.
Позволяет наставникам планировать занятия, а ученикам просматривать расписание.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from models import User, Lesson, MentorStudent
from schemas import LessonCreateRequest, LessonUpdateRequest, LessonResponse
from dependencies import get_db, get_current_user
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY, get_logger
from bot import to_msk

logger = get_logger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["schedule"])


async def send_tg_lesson_notification(
    telegram_id: int,
    title: str,
    subject: str,
    start_time: datetime,
    mentor_name: str,
    lesson_link: str,
    notes: str = "",
) -> bool:
    """Мгновенное уведомление в Telegram о новом назначенном уроке (время по МСК)."""
    if not TELEGRAM_BOT_TOKEN:
        return False

    time_str = to_msk(start_time)
    link_section = f"\n🔗 <b>Ссылка на урок:</b> <a href=\"{lesson_link}\">{lesson_link}</a>" if lesson_link else ""
    notes_section = f"\n📝 <b>Заметки:</b> {notes}" if notes else ""

    text = (
        f"📅 <b>Новое занятие в расписании!</b>\n\n"
        f"📚 <b>Тема:</b> {title} ({subject})\n"
        f"⏰ <b>Дата и время:</b> {time_str}\n"
        f"👨‍🏫 <b>Преподаватель:</b> {mentor_name}"
        f"{link_section}"
        f"{notes_section}\n\n"
        f"<i>Не забудьте подготовиться к уроку!</i> 🚀"
    )

    try:
        proxy_arg = TELEGRAM_PROXY if TELEGRAM_PROXY else None
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy_arg) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
            return resp.status_code == 200
    except Exception as e:
        logger.error("Ошибка отправки Telegram-уведомления об уроке: %s", e)
        return False


def format_lesson(lesson: Lesson, mentor_name: str, student_name: str) -> dict:
    return {
        "id": lesson.id,
        "mentor_id": lesson.mentor_id,
        "mentor_name": mentor_name,
        "student_id": lesson.student_id,
        "student_name": student_name,
        "title": lesson.title,
        "subject": lesson.subject,
        "start_time": lesson.start_time.isoformat() if lesson.start_time else None,
        "duration_minutes": lesson.duration_minutes,
        "lesson_link": lesson.lesson_link,
        "notes": lesson.notes,
        "created_at": lesson.created_at.isoformat() if lesson.created_at else None,
    }


@router.post("/lessons")
async def create_lesson(
    data: LessonCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать урок (доступно для наставников)."""
    if not current_user.is_mentor:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только наставники могут планировать уроки",
        )

    # Проверяем ученика
    student_res = await db.execute(select(User).where(User.id == data.student_id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(status_code=404, detail="Ученик не найден")

    lesson = Lesson(
        mentor_id=current_user.id,
        student_id=data.student_id,
        title=data.title.strip(),
        subject=data.subject.strip(),
        start_time=data.start_time,
        duration_minutes=data.duration_minutes,
        lesson_link=data.lesson_link.strip(),
        notes=data.notes.strip(),
        created_at=datetime.now(timezone.utc),
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)

    # Отправляем уведомление в Telegram ученику, если у него привязан TG
    if student.telegram_id:
        await send_tg_lesson_notification(
            telegram_id=student.telegram_id,
            title=lesson.title,
            subject=lesson.subject,
            start_time=lesson.start_time,
            mentor_name=current_user.name or "Наставник",
            lesson_link=lesson.lesson_link,
            notes=lesson.notes,
        )

    return {
        "success": True,
        "message": "Урок успешно добавлен в расписание",
        "lesson": format_lesson(lesson, current_user.name or "Наставник", student.name or "Ученик"),
    }


@router.get("/mentor")
async def get_mentor_lessons(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список всех уроков наставника."""
    stmt = (
        select(Lesson, User.name.label("student_name"))
        .join(User, Lesson.student_id == User.id)
        .where(Lesson.mentor_id == current_user.id)
        .order_by(Lesson.start_time.asc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    lessons = []
    for lesson, student_name in rows:
        lessons.append(format_lesson(lesson, current_user.name or "Наставник", student_name or "Ученик"))

    return {"lessons": lessons}


@router.get("/student")
async def get_student_lessons(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список всех уроков ученика."""
    stmt = (
        select(Lesson, User.name.label("mentor_name"))
        .join(User, Lesson.mentor_id == User.id)
        .where(Lesson.student_id == current_user.id)
        .order_by(Lesson.start_time.asc())
    )
    res = await db.execute(stmt)
    rows = res.all()

    lessons = []
    for lesson, mentor_name in rows:
        lessons.append(format_lesson(lesson, mentor_name or "Наставник", current_user.name or "Ученик"))

    return {"lessons": lessons}


@router.delete("/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить/отменить урок."""
    res = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = res.scalars().first()

    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    if lesson.mentor_id != current_user.id and lesson.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет прав на удаление этого урока")

    await db.delete(lesson)
    await db.commit()

    return {"success": True, "message": "Урок удален из расписания"}


@router.put("/lessons/{lesson_id}")
async def update_lesson(
    lesson_id: int,
    data: LessonUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Обновить информацию об уроке."""
    res = await db.execute(select(Lesson).where(Lesson.id == lesson_id))
    lesson = res.scalars().first()

    if not lesson:
        raise HTTPException(status_code=404, detail="Урок не найден")

    if lesson.mentor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Только наставник может редактировать урок")

    if data.title is not None:
        lesson.title = data.title.strip()
    if data.subject is not None:
        lesson.subject = data.subject.strip()
    if data.start_time is not None:
        lesson.start_time = data.start_time
        lesson.notified_1h = False
        lesson.notified_15m = False
    if data.duration_minutes is not None:
        lesson.duration_minutes = data.duration_minutes
    if data.lesson_link is not None:
        lesson.lesson_link = data.lesson_link.strip()
    if data.notes is not None:
        lesson.notes = data.notes.strip()

    await db.commit()
    await db.refresh(lesson)

    return {"success": True, "message": "Урок обновлен"}
