"""
Роутер наставников и домашних заданий (Simplified Concept).
Создание ДЗ, назначение ученикам, сдача учеником, проверка наставником.
"""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
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
from dependencies import get_db, get_current_user
from config import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["homework"])


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
    return {
        "students": [
            {"id": s.id, "name": s.name or "Пользователь", "email": s.email} for s in students
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
    return {
        "mentors": [
            {"id": m.id, "name": m.name or "Наставник", "email": m.email} for m in mentors
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
        exists = await db.scalar(
            select(func.count(StudentHomework.id)).where(
                and_(StudentHomework.homework_id == homework_id, StudentHomework.student_id == student_id)
            )
        )
        if exists:
            continue

        db.add(
            StudentHomework(
                homework_id=homework.id,
                student_id=student_id,
                status="pending",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        created += 1

    await db.commit()
    return {"success": True, "students_assigned": created}


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
        select(StudentHomework).where(
            and_(
                StudentHomework.id == student_homework_id,
                StudentHomework.student_id == current_user.id,
            )
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="Домашнее задание не найдено")

    item.student_comment = data.student_comment
    item.student_attachments = json.dumps(data.student_attachments)
    item.status = "completed"
    item.completed_at = datetime.now(timezone.utc)
    
    await db.commit()
    return {"success": True, "message": "Домашнее задание сдано"}


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
