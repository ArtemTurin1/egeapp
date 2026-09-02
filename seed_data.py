"""
Скрипт для заполнения базы тестовыми наставниками, учениками, кодами и домашними заданиями.
Запуск:
    cd beck/egeapp
    python seed_data.py
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from models import (
    async_session,
    init_db,
    User,
    RegistrationCode,
    MentorStudent,
    Homework,
    StudentHomework,
    Lesson,
)
from datetime import timedelta
from dependencies import hash_password


async def seed():
    await init_db()

    async with async_session() as db:
        print("🌱 Начинаем наполнение базы тестовыми данными...")

        # 1. Проверяем, есть ли уже тестовые пользователи
        res = await db.execute(select(User).where(User.email.in_([
            "teacher1@example.com",
            "teacher2@example.com",
            "student1@example.com",
            "student2@example.com",
            "student3@example.com",
        ])))
        existing_users = {u.email: u for u in res.scalars().all()}

        # 2. Создаем наставников
        teachers_data = [
            {
                "email": "teacher1@example.com",
                "name": "Иван Петров (Учитель)",
                "password_hash": hash_password("123456"),
                "is_mentor": True,
                "telegram_id": 100001,
                "telegram_username": "petrov_math",
                "auth_type": "email",
                "code": "TEACH1",
            },
            {
                "email": "teacher2@example.com",
                "name": "Анна Смирнова (Учитель)",
                "password_hash": hash_password("123456"),
                "is_mentor": True,
                "telegram_id": 100002,
                "telegram_username": "smirnova_phys",
                "auth_type": "email",
                "code": "TEACH2",
            },
        ]

        created_teachers = []
        for t_info in teachers_data:
            code = t_info.pop("code")
            if t_info["email"] in existing_users:
                user = existing_users[t_info["email"]]
            else:
                user = User(**t_info, created_at=datetime.now(timezone.utc))
                db.add(user)
                await db.flush()
                print(f"  ✅ Создан наставник: {user.name} ({user.email})")

            # Добавляем код регистрации/входа
            code_res = await db.execute(select(RegistrationCode).where(RegistrationCode.code == code))
            if not code_res.scalars().first():
                reg_code = RegistrationCode(
                    code=code,
                    telegram_id=user.telegram_id,
                    telegram_username=user.telegram_username,
                    is_used=True,
                    created_at=datetime.now(timezone.utc),
                    used_at=datetime.now(timezone.utc),
                )
                db.add(reg_code)

            created_teachers.append(user)

        # 3. Создаем учеников
        students_data = [
            {
                "email": "student1@example.com",
                "name": "Алексей Сидоров",
                "password_hash": hash_password("123456"),
                "is_mentor": False,
                "telegram_id": 200001,
                "telegram_username": "sidorov_alex",
                "auth_type": "email",
                "code": "STUD01",
            },
            {
                "email": "student2@example.com",
                "name": "Мария Кузнецова",
                "password_hash": hash_password("123456"),
                "is_mentor": False,
                "telegram_id": 200002,
                "telegram_username": "kuznetsova_m",
                "auth_type": "email",
                "code": "STUD02",
            },
            {
                "email": "student3@example.com",
                "name": "Дмитрий Васильев",
                "password_hash": hash_password("123456"),
                "is_mentor": False,
                "telegram_id": 200003,
                "telegram_username": "vasiliev_dima",
                "auth_type": "email",
                "code": "STUD03",
            },
        ]

        created_students = []
        for s_info in students_data:
            code = s_info.pop("code")
            if s_info["email"] in existing_users:
                user = existing_users[s_info["email"]]
            else:
                user = User(**s_info, created_at=datetime.now(timezone.utc))
                db.add(user)
                await db.flush()
                print(f"  ✅ Создан ученик: {user.name} ({user.email})")

            # Добавляем код регистрации/входа
            code_res = await db.execute(select(RegistrationCode).where(RegistrationCode.code == code))
            if not code_res.scalars().first():
                reg_code = RegistrationCode(
                    code=code,
                    telegram_id=user.telegram_id,
                    telegram_username=user.telegram_username,
                    is_used=True,
                    created_at=datetime.now(timezone.utc),
                    used_at=datetime.now(timezone.utc),
                )
                db.add(reg_code)

            created_students.append(user)

        # 4. Привязываем учеников к наставникам
        # Учитель 1 (Иван) -> Ученики 1 и 2
        # Учитель 2 (Анна) -> Ученик 3
        teacher_student_links = [
            (created_teachers[0].id, created_students[0].id),
            (created_teachers[0].id, created_students[1].id),
            (created_teachers[1].id, created_students[2].id),
        ]

        for mentor_id, student_id in teacher_student_links:
            check_link = await db.execute(
                select(MentorStudent).where(
                    MentorStudent.mentor_id == mentor_id,
                    MentorStudent.student_id == student_id,
                )
            )
            if not check_link.scalars().first():
                link = MentorStudent(
                    mentor_id=mentor_id,
                    student_id=student_id,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(link)

        # 5. Создаем тестовые домашние задания от Учителя 1
        t1_id = created_teachers[0].id
        s1_id = created_students[0].id
        s2_id = created_students[1].id

        hw_res = await db.execute(select(Homework).where(Homework.mentor_id == t1_id))
        if not hw_res.scalars().first():
            hw1 = Homework(
                mentor_id=t1_id,
                title="ДЗ №1: Профильная математика (Параметры и Тригонометрия)",
                description="Решить задачи №12 и №17 из демоверсии ЕГЭ. Прикрепить решения.",
                attachments='["https://example.com/math_hw1.pdf"]',
                created_at=datetime.now(timezone.utc),
            )
            db.add(hw1)
            await db.flush()

            # Назначаем обоим ученикам
            shw1 = StudentHomework(
                homework_id=hw1.id,
                student_id=s1_id,
                status="completed",
                student_comment="Решил все задачи, ответы в файле",
                student_attachments='["https://example.com/solution_alex.png"]',
                assigned_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            shw2 = StudentHomework(
                homework_id=hw1.id,
                student_id=s2_id,
                status="pending",
                student_comment="",
                student_attachments='[]',
                assigned_at=datetime.now(timezone.utc),
                completed_at=None,
            )
            db.add_all([shw1, shw2])
            print("  📚 Создано тестовое домашнее задание и назначено ученикам")

        # 6. Создаем тестовые уроки в расписании
        lesson_res = await db.execute(select(Lesson).where(Lesson.mentor_id == t1_id))
        if not lesson_res.scalars().first():
            now = datetime.now(timezone.utc)
            l1 = Lesson(
                mentor_id=t1_id,
                student_id=s1_id,
                title="Разбор сложных параметров (Задание №18 ЕГЭ)",
                subject="Математика",
                start_time=now + timedelta(hours=2),
                duration_minutes=60,
                lesson_link="https://meet.google.com/abc-defg-hij",
                notes="Повторить свойства квадратичной функции",
                created_at=now,
            )
            l2 = Lesson(
                mentor_id=t1_id,
                student_id=s2_id,
                title="Динамическое программирование (Задание №27 ЕГЭ)",
                subject="Информатика",
                start_time=now + timedelta(days=1, hours=4),
                duration_minutes=90,
                lesson_link="https://zoom.us/j/123456789",
                notes="Открыть среду разработки Python",
                created_at=now,
            )
            db.add_all([l1, l2])
            print("  📅 Созданы тестовые уроки в расписании")

        await db.commit()
        print("\n✨ Тестовые данные успешно загружены!")
        print("\n" + "=" * 50)
        print("Данные для входа (Пароль у всех: 123456):")
        print("=" * 50)
        print("👨‍🏫 Наставники:")
        print("  - Email: teacher1@example.com | Код: TEACH1 | Иван Петров")
        print("  - Email: teacher2@example.com | Код: TEACH2 | Анна Смирнова")
        print("\n👨‍🎓 Ученики:")
        print("  - Email: student1@example.com | Код: STUD01 | Алексей Сидоров (ученик teacher1)")
        print("  - Email: student2@example.com | Код: STUD02 | Мария Кузнецова (ученица teacher1)")
        print("  - Email: student3@example.com | Код: STUD03 | Дмитрий Васильев (ученик teacher2)")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(seed())
