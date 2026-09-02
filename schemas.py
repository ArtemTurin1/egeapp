"""
Pydantic схемы валидации и сериализации данных API КогдаУрок.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============================================================================
# АУТЕНТИФИКАЦИЯ И ПОЛЬЗОВАТЕЛЬ
# ============================================================================

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]
    message: Optional[str] = None


class UserProfileResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    is_mentor: bool = False
    auth_type: str = "email"
    telegram_id: Optional[int] = None
    telegram_username: Optional[str] = None
    created_at: Optional[datetime] = None


class UserUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


# ============================================================================
# РЕГИСТРАЦИЯ ПО КОДУ
# ============================================================================

class CodeVerifyRequest(BaseModel):
    code: str


class CodeRegisterRequest(BaseModel):
    code: str
    name: Optional[str] = ""


class CodeLoginRequest(BaseModel):
    code: str
    telegram_id: int


# ============================================================================
# НАСТАВНИКИ
# ============================================================================

class AddStudentRequest(BaseModel):
    student_id: int


class AddMentorRequest(BaseModel):
    mentor_id: int


# ============================================================================
# ДОМАШНИЕ ЗАДАНИЯ (НОВАЯ СТРУКТУРА)
# ============================================================================

class HomeworkCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: str = ""
    attachments: List[str] = []


class HomeworkAssignRequest(BaseModel):
    student_ids: List[int]


class StudentHomeworkSubmitRequest(BaseModel):
    student_comment: str = ""
    student_attachments: List[str] = []


class HomeworkReviewRequest(BaseModel):
    status: str = "completed"  # 'pending' or 'completed'
    mentor_feedback: str = ""


# ============================================================================
# АУТЕНТИФИКАЦИЯ EMAIL
# ============================================================================



class EmailRegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=256)
    password: str = Field(..., min_length=4, max_length=128)
    name: str = Field(..., min_length=1, max_length=128)
    is_mentor: bool = False


class EmailLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=256)
    password: str = Field(..., min_length=1, max_length=128)



class LinkTelegramRequest(BaseModel):
    code: str


# ============================================================================
# РАСПИСАНИЕ И УРОКИ
# ============================================================================

class LessonCreateRequest(BaseModel):
    student_id: int
    title: str = Field(..., min_length=1, max_length=256)
    subject: str = Field(default="Математика", max_length=64)
    start_time: datetime
    duration_minutes: int = 60
    lesson_link: str = ""
    notes: str = ""


class LessonUpdateRequest(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    start_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    lesson_link: Optional[str] = None
    notes: Optional[str] = None


class LessonResponse(BaseModel):
    id: int
    mentor_id: int
    mentor_name: Optional[str] = None
    student_id: int
    student_name: Optional[str] = None
    title: str
    subject: str
    start_time: datetime
    duration_minutes: int
    lesson_link: str
    notes: str
    created_at: datetime

