"""
Роутер наставников и домашних заданий (Simplified Concept).
Создание ДЗ, назначение ученикам, сдача учеником, проверка наставником.
"""

import json
import html
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, delete
from datetime import datetime, timezone

from models import (
    User,
    MentorStudent,
    Homework,
    StudentHomework,
)
from schemas import (
    AddStudentRequest,
    AddMentorRequest,
    HomeworkCreateRequest,
    HomeworkAssignRequest,
    StudentHomeworkSubmitRequest,
    HomeworkReviewRequest
)
import httpx
from dependencies import get_db, get_current_user
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY, FRONTEND_URL, get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["homework"])


async def send_tg_homework_notification(
    telegram_id: int,
    homework_title: str,
    mentor_name: str,
    description: str = "",
) -> bool:
    """Отправка уведомления ученику в Telegram о новом назначенном ДЗ."""
    if not TELEGRAM_BOT_TOKEN or not telegram_id:
        return False

    title_safe = html.escape(homework_title or "Без названия")
    mentor_safe = html.escape(mentor_name or "Преподаватель")

    desc_clean = (description or "").strip()
    if len(desc_clean) > 250:
        desc_clean = desc_clean[:250] + "..."
    desc_safe = html.escape(desc_clean)
    desc_section = f"\n\n📝 <b>Задание:</b>\n<i>{desc_safe}</i>" if desc_safe else ""

    text = (
        f"📚 <b>Вам назначено новое домашнее задание!</b>\n\n"
        f"📌 <b>Тема:</b> {title_safe}\n"
        f"👨‍🏫 <b>Преподаватель:</b> {mentor_safe}"
        f"{desc_section}\n\n"
        f"👉 <i>Зайдите на платформу, чтобы посмотреть материалы и сдать работу!</i> 🚀"
    )

    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if FRONTEND_URL:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": "📖 Открыть ДЗ на платформе", "url": f"{FRONTEND_URL}/homework"}]
            ]
        }

    try:
        proxy_arg = TELEGRAM_PROXY if TELEGRAM_PROXY else None
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy_arg) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
            )
            if resp.status_code != 200:
                logger.error("Ошибка Telegram API (ученик %s): status=%s body=%s", telegram_id, resp.status_code, resp.text)
                return False
            return True
    except Exception as e:
        logger.error("Ошибка отправки Telegram-уведомления о ДЗ (ученик %s): %s", telegram_id, e)
        return False


async def send_tg_homework_submitted_notification(
    telegram_id: int,
    homework_title: str,
    student_name: str,
    student_comment: str = "",
    attachments_count: int = 0,
) -> bool:
    """Отправка уведомления учителю в Telegram о том, что ученик сдал ДЗ."""
    if not TELEGRAM_BOT_TOKEN or not telegram_id:
        return False

    title_safe = html.escape(homework_title or "Без названия")
    student_safe = html.escape(student_name or "Ученик")

    comment_clean = (student_comment or "").strip()
    if len(comment_clean) > 250:
        comment_clean = comment_clean[:250] + "..."
    comment_safe = html.escape(comment_clean)
    comment_section = f"\n\n💬 <b>Комментарий ученика:</b>\n<i>{comment_safe}</i>" if comment_safe else ""

    attach_text = f"\n📎 <b>Прикреплено файлов / фото:</b> {attachments_count}" if attachments_count > 0 else ""

    text = (
        f"✅ <b>Ученик сдал домашнее задание!</b>\n\n"
        f"👤 <b>Ученик:</b> {student_safe}\n"
        f"📌 <b>Тема задания:</b> {title_safe}"
        f"{comment_section}"
        f"{attach_text}\n\n"
        f"👉 <i>Проверьте работу ученика на платформе!</i> 🎯"
    )

    payload = {
        "chat_id": telegram_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if FRONTEND_URL:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": "👀 Посмотреть работу на платформе", "url": f"{FRONTEND_URL}/homework"}]
            ]
        }

    try:
        proxy_arg = TELEGRAM_PROXY if TELEGRAM_PROXY else None
        async with httpx.AsyncClient(timeout=10.0, proxy=proxy_arg) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
            )
            if resp.status_code != 200:
                logger.error("Ошибка Telegram API (учитель %s): status=%s body=%s", telegram_id, resp.status_code, resp.text)
                return False
            return True
    except Exception as e:
        logger.error("Ошибка отправки Telegram-уведомления учителю (учитель %s): %s", telegram_id, e)
        return False


# ---------- Наставники и ученики ----------

@router.post("/api/mentor/become")
async def become_mentor(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Включить режим наставника."""
    current_user.is_mentor = True
    await db.commit()
    logger.info("mentor.enabled user_id=%s", current_user.id)
    return {"success": True, "is_mentor": True, "message": "Режим наставника включен"}


@router.post("/api/mentor/add-student")
async def add_student(
    data: AddStudentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Наставник добавляет ученика по ID."""
    if not current_user.is_mentor:
        current_user.is_mentor = True

    if data.student_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя в качестве ученика")

    result = await db.execute(select(User).where(User.id == data.student_id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(status_code=404, detail="Ученик с таким ID не найден")

    exists = await db.scalar(
        select(func.count(MentorStudent.id)).where(
            and_(
                MentorStudent.mentor_id == current_user.id,
                MentorStudent.student_id == student.id,
            )
        )
    )
    if not exists:
        db.add(MentorStudent(mentor_id=current_user.id, student_id=student.id))

    await db.commit()
    return {"success": True, "message": f"Ученик {student.name or student.email} добавлен"}


@router.post("/api/student/add-mentor")
async def add_mentor(
    data: AddMentorRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ученик добавляет наставника по ID."""
    if data.mentor_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя добавить самого себя в качестве наставника")

    result = await db.execute(select(User).where(User.id == data.mentor_id))
    mentor = result.scalars().first()
    if not mentor:
        raise HTTPException(status_code=404, detail="Наставник с таким ID не найден")

    mentor.is_mentor = True

    exists = await db.scalar(
        select(func.count(MentorStudent.id)).where(
            and_(
                MentorStudent.mentor_id == mentor.id,
                MentorStudent.student_id == current_user.id,
            )
        )
    )
    if not exists:
        db.add(MentorStudent(mentor_id=mentor.id, student_id=current_user.id))

    await db.commit()
    return {"success": True, "message": f"Наставник {mentor.name or mentor.email} добавлен"}


@router.get("/api/mentor/students")
async def get_my_students(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список учеников текущего наставника."""
    result = await db.execute(
        select(User)
        .join(MentorStudent, MentorStudent.student_id == User.id)
        .where(MentorStudent.mentor_id == current_user.id)
    )
    students = result.scalars().all()
    def clean_email(u: User):
        if u.auth_type == "telegram" or (u.email and (u.email.endswith("@kogdaurok.local") or u.email.startswith("telegram_"))):
            return None
        return u.email

    return {
        "students": [
            {
                "id": s.id,
                "name": s.name or "Пользователь",
                "email": clean_email(s),
                "telegram_username": s.telegram_username,
                "has_telegram": bool(s.telegram_id),
                "auth_type": s.auth_type,
            }
            for s in students
        ]
    }


@router.get("/api/student/mentors")
async def get_my_mentors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список наставников текущего ученика."""
    result = await db.execute(
        select(User)
        .join(MentorStudent, MentorStudent.mentor_id == User.id)
        .where(MentorStudent.student_id == current_user.id)
    )
    mentors = result.scalars().all()

    def clean_email(u: User):
        if u.auth_type == "telegram" or (u.email and (u.email.endswith("@kogdaurok.local") or u.email.startswith("telegram_"))):
            return None
        return u.email

    return {
        "mentors": [
            {
                "id": m.id,
                "name": m.name or "Наставник",
                "email": clean_email(m),
                "telegram_username": m.telegram_username,
                "auth_type": m.auth_type,
            }
            for m in mentors
        ]
    }


# ---------- Создание и назначение ДЗ ----------

@router.post("/api/homework/")
async def create_homework(
    data: HomeworkCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать ДЗ (для наставника)."""
    if not current_user.is_mentor:
        raise HTTPException(status_code=403, detail="Доступно только наставнику")

    homework = Homework(
        mentor_id=current_user.id,
        title=data.title,
        description=data.description,
        attachments=json.dumps(data.attachments),
        created_at=datetime.now(timezone.utc),
    )
    db.add(homework)
    await db.commit()
    await db.refresh(homework)

    return {"success": True, "homework_id": homework.id, "message": "ДЗ создано"}


@router.post("/api/homework/{homework_id}/assign")
async def assign_homework(
    homework_id: int,
    data: HomeworkAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Назначить ДЗ ученикам."""
    if not current_user.is_mentor:
        raise HTTPException(status_code=403, detail="Доступно только наставнику")

    if not data.student_ids:
        raise HTTPException(status_code=400, detail="Выберите учеников")

    result = await db.execute(select(Homework).where(and_(Homework.id == homework_id, Homework.mentor_id == current_user.id)))
    homework = result.scalars().first()
    if not homework:
        raise HTTPException(status_code=404, detail="ДЗ не найдено")

    created = 0
    notified_count = 0
    no_tg_count = 0
    mentor_display_name = current_user.name or (current_user.telegram_username and f"@{current_user.telegram_username}") or "Преподаватель"

    for student_id in data.student_ids:
        # Проверяем что он ученик этого ментора
        relation = await db.scalar(
            select(func.count(MentorStudent.id)).where(
                and_(MentorStudent.mentor_id == current_user.id, MentorStudent.student_id == student_id)
            )
        )
        if not relation:
            continue

        # Проверяем нет ли уже назначенного
        existing_sh = await db.scalar(
            select(StudentHomework).where(
                and_(StudentHomework.homework_id == homework_id, StudentHomework.student_id == student_id)
            )
        )
        if not existing_sh:
            db.add(
                StudentHomework(
                    homework_id=homework.id,
                    student_id=student_id,
                    status="pending",
                    assigned_at=datetime.now(timezone.utc),
                )
            )
            created += 1

        # Отправляем уведомление в Telegram ученику, если у него привязан Telegram
        try:
            student_res = await db.execute(select(User).where(User.id == student_id))
            student_user = student_res.scalars().first()
            if student_user and student_user.telegram_id:
                notified = await send_tg_homework_notification(
                    telegram_id=student_user.telegram_id,
                    homework_title=homework.title,
                    mentor_name=mentor_display_name,
                    description=homework.description or "",
                )
                if notified:
                    notified_count += 1
            else:
                no_tg_count += 1
        except Exception as e:
            logger.error("Не удалось отправить TG-уведомление ученику %s: %s", student_id, e)

    await db.commit()
    return {
        "success": True,
        "students_assigned": created,
        "notified_count": notified_count,
        "no_tg_count": no_tg_count,
    }


# ---------- Просмотр ДЗ ----------

@router.get("/api/homework/mentor")
async def get_mentor_homework_list(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список созданных наставником заданий."""
    result = await db.execute(
        select(Homework)
        .where(Homework.mentor_id == current_user.id)
        .order_by(Homework.created_at.desc())
    )
    items = []
    for homework in result.scalars().all():
        total = await db.scalar(select(func.count(StudentHomework.id)).where(StudentHomework.homework_id == homework.id)) or 0
        completed = await db.scalar(select(func.count(StudentHomework.id)).where(and_(StudentHomework.homework_id == homework.id, StudentHomework.status == "completed"))) or 0
        
        items.append({
            "homework_id": homework.id,
            "title": homework.title,
            "students_total": int(total),
            "students_completed": int(completed),
            "created_at": homework.created_at.isoformat() if homework.created_at else None,
        })
    return {"items": items}


@router.get("/api/homework/mentor/{homework_id}")
async def get_mentor_homework_details(
    homework_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить детализацию выполнения ДЗ учениками."""
    result = await db.execute(
        select(Homework).where(
            and_(Homework.id == homework_id, Homework.mentor_id == current_user.id)
        )
    )
    homework = result.scalars().first()
    if not homework:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    result = await db.execute(
        select(StudentHomework, User)
        .join(User, User.id == StudentHomework.student_id)
        .where(StudentHomework.homework_id == homework.id)
    )
    
    students = []
    completed = 0
    for student_homework, student in result.all():
        if student_homework.status == "completed":
            completed += 1
        students.append(
            {
                "student_homework_id": student_homework.id,
                "student_id": student.id,
                "student_name": student.name or student.email,
                "status": student_homework.status,
                "student_comment": student_homework.student_comment,
                "student_attachments": json.loads(student_homework.student_attachments),
                "completed_at": student_homework.completed_at.isoformat() if student_homework.completed_at else None,
                "assigned_at": student_homework.assigned_at.isoformat() if student_homework.assigned_at else None,
            }
        )

    return {
        "homework": {
            "homework_id": homework.id,
            "title": homework.title,
            "description": homework.description,
            "attachments": json.loads(homework.attachments),
            "students_total": len(students),
            "students_completed": completed,
            "created_at": homework.created_at.isoformat() if homework.created_at else None,
        },
        "students": students,
    }


@router.get("/api/homework/student")
async def get_student_homework_list(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить список домашних заданий текущего ученика."""
    result = await db.execute(
        select(StudentHomework, Homework, User)
        .join(Homework, Homework.id == StudentHomework.homework_id)
        .join(User, User.id == Homework.mentor_id)
        .where(StudentHomework.student_id == current_user.id)
        .order_by(StudentHomework.assigned_at.desc())
    )
    
    items = []
    for student_homework, homework, mentor in result.all():
        items.append({
            "student_homework_id": student_homework.id,
            "homework_id": homework.id,
            "title": homework.title,
            "mentor_name": mentor.name or mentor.email,
            "status": student_homework.status,
            "assigned_at": student_homework.assigned_at.isoformat() if student_homework.assigned_at else None,
            "completed_at": student_homework.completed_at.isoformat() if student_homework.completed_at else None,
        })
    return {"items": items}


@router.get("/api/homework/student/{student_homework_id}")
async def get_student_homework_details(
    student_homework_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить детали задания для ученика."""
    result = await db.execute(
        select(StudentHomework, Homework, User)
        .join(Homework, Homework.id == StudentHomework.homework_id)
        .join(User, User.id == Homework.mentor_id)
        .where(and_(StudentHomework.id == student_homework_id, StudentHomework.student_id == current_user.id))
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Задание не найдено")
        
    student_homework, homework, mentor = row
    
    return {
        "student_homework_id": student_homework.id,
        "homework_id": homework.id,
        "title": homework.title,
        "description": homework.description,
        "attachments": json.loads(homework.attachments),
        "mentor_name": mentor.name or mentor.email,
        "status": student_homework.status,
        "student_comment": student_homework.student_comment,
        "student_attachments": json.loads(student_homework.student_attachments),
        "assigned_at": student_homework.assigned_at.isoformat() if student_homework.assigned_at else None,
        "completed_at": student_homework.completed_at.isoformat() if student_homework.completed_at else None,
    }


@router.post("/api/homework/student/{student_homework_id}/submit")
async def submit_student_homework(
    student_homework_id: int,
    data: StudentHomeworkSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сдача домашнего задания учеником."""
    result = await db.execute(
        select(StudentHomework, Homework, User)
        .join(Homework, Homework.id == StudentHomework.homework_id)
        .join(User, User.id == Homework.mentor_id)
        .where(
            and_(
                StudentHomework.id == student_homework_id,
                StudentHomework.student_id == current_user.id,
            )
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    item, homework, mentor = row

    item.student_comment = data.student_comment
    item.student_attachments = json.dumps(data.student_attachments)
    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    
    await db.commit()

    # Отправляем уведомление наставнику в Telegram
    notified_mentor = False
    if mentor and mentor.telegram_id:
        try:
            student_display_name = (
                current_user.name
                or (current_user.telegram_username and f"@{current_user.telegram_username}")
                or current_user.email
                or "Ученик"
            )
            attachments_count = len(data.student_attachments) if data.student_attachments else 0
            notified_mentor = await send_tg_homework_submitted_notification(
                telegram_id=mentor.telegram_id,
                homework_title=homework.title,
                student_name=student_display_name,
                student_comment=data.student_comment or "",
                attachments_count=attachments_count,
            )
            logger.info("Уведомление наставнику %s отправлено: %s", mentor.id, notified_mentor)
        except Exception as e:
            logger.error("Ошибка при отправке TG-уведомления наставнику %s: %s", mentor.id, e)

    return {
        "success": True,
        "message": "Домашнее задание сдано",
        "mentor_notified": notified_mentor,
    }


@router.post("/api/homework/review/{student_homework_id}")
async def review_homework(
    student_homework_id: int,
    data: HomeworkReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Учитель смотрит/комментирует (опционально) ДЗ ученика."""
    if not current_user.is_mentor:
        raise HTTPException(status_code=403, detail="Доступно только наставнику")

    # Проверяем, что это задание ученика принадлежит ДЗ, которое создал этот ментор
    result = await db.execute(
        select(StudentHomework, Homework)
        .join(Homework, Homework.id == StudentHomework.homework_id)
        .where(
            and_(
                StudentHomework.id == student_homework_id,
                Homework.mentor_id == current_user.id
            )
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Сдача ученика не найдена или нет доступа")
        
    student_homework, _ = row
    
    student_homework.status = data.status
    # Опционально можно добавить поле mentor_feedback в StudentHomework если надо,
    # Но в текущей модели мы его не добавляли. Если нужно, добавлю.
    # В requirements юзер сказал "Учитель может посмотреть что получилось но оценки ставить нет".
    # Текстовый фидбек от учителя не упомянут явно, но я добавил mentor_feedback в план.
    # Ок, давайте пока просто обновим статус (например вернуть в pending).
    
    await db.commit()
    return {"success": True, "message": "Статус обновлен"}


# ---------- Удаление ДЗ и отмена назначения ученика ----------

@router.delete("/api/homework/{homework_id}")
async def delete_homework(
    homework_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Удалить домашнее задание (для наставника)."""
    if not current_user.is_mentor:
        raise HTTPException(status_code=403, detail="Доступно только наставнику")

    result = await db.execute(
        select(Homework).where(
            and_(Homework.id == homework_id, Homework.mentor_id == current_user.id)
        )
    )
    homework = result.scalars().first()
    if not homework:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    # Удаляем все назначения данного ДЗ ученикам
    await db.execute(
        delete(StudentHomework).where(StudentHomework.homework_id == homework_id)
    )
    # Удаляем само ДЗ
    await db.delete(homework)
    await db.commit()

    return {"success": True, "message": "Домашнее задание удалено"}


@router.delete("/api/homework/{homework_id}/assign/{student_id}")
async def unassign_student_homework(
    homework_id: int,
    student_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отменить назначение ДЗ конкретному ученику."""
    if not current_user.is_mentor:
        raise HTTPException(status_code=403, detail="Доступно только наставнику")

    result = await db.execute(
        select(Homework).where(
            and_(Homework.id == homework_id, Homework.mentor_id == current_user.id)
        )
    )
    homework = result.scalars().first()
    if not homework:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    sh_result = await db.execute(
        select(StudentHomework).where(
            and_(
                StudentHomework.homework_id == homework_id,
                StudentHomework.student_id == student_id,
            )
        )
    )
    student_homework = sh_result.scalars().first()
    if not student_homework:
        raise HTTPException(status_code=404, detail="Назначение ученика не найдено")

    await db.delete(student_homework)
    await db.commit()

    return {"success": True, "message": "Назначение ученика отменено"}

