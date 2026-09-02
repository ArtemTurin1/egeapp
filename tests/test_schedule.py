"""
Тесты модуля расписания уроков КогдаУрок.
"""

import pytest
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_schedule_flow(client, test_mentor_and_student):
    mentor = test_mentor_and_student["mentor"]
    student = test_mentor_and_student["student"]

    start_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

    # 1. Наставник планирует урок
    create_resp = await client.post(
        "/api/schedule/lessons",
        headers=mentor["headers"],
        json={
            "student_id": student["id"],
            "title": "Теория вероятностей (Задание №4 ЕГЭ)",
            "subject": "Математика",
            "start_time": start_time,
            "duration_minutes": 90,
            "lesson_link": "https://meet.google.com/test-room",
            "notes": "Повторить формулу Бернулли",
        },
    )
    assert create_resp.status_code == 200
    lesson_data = create_resp.json()["lesson"]
    lesson_id = lesson_data["id"]
    assert lesson_data["title"] == "Теория вероятностей (Задание №4 ЕГЭ)"
    assert lesson_data["duration_minutes"] == 90

    # 2. Наставник видит запланированный урок в своем расписании
    mentor_schedule_resp = await client.get("/api/schedule/mentor", headers=mentor["headers"])
    assert mentor_schedule_resp.status_code == 200
    lessons = mentor_schedule_resp.json()["lessons"]
    assert any(l["id"] == lesson_id for l in lessons)

    # 3. Ученик видит запланированный урок в своем расписании
    student_schedule_resp = await client.get("/api/schedule/student", headers=student["headers"])
    assert student_schedule_resp.status_code == 200
    s_lessons = student_schedule_resp.json()["lessons"]
    assert any(l["id"] == lesson_id for l in s_lessons)

    # 4. Наставник обновляет урок
    update_resp = await client.put(
        f"/api/schedule/lessons/{lesson_id}",
        headers=mentor["headers"],
        json={
            "title": "Теория вероятностей: Углубленный уровень",
            "duration_minutes": 60,
        },
    )
    assert update_resp.status_code == 200

    # 5. Наставник удаляет урок
    delete_resp = await client.delete(
        f"/api/schedule/lessons/{lesson_id}",
        headers=mentor["headers"],
    )
    assert delete_resp.status_code == 200

    # 6. Проверяем, что урок удален
    after_del_resp = await client.get("/api/schedule/mentor", headers=mentor["headers"])
    assert after_del_resp.status_code == 200
    assert not any(l["id"] == lesson_id for l in after_del_resp.json()["lessons"])
