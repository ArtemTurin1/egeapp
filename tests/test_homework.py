"""
Тесты функционала наставничества и домашних заданий КогдаУрок.
"""

import pytest


@pytest.mark.asyncio
async def test_mentor_and_homework_flow(client, test_mentor_and_student):
    mentor = test_mentor_and_student["mentor"]
    student = test_mentor_and_student["student"]

    # 1. Проверяем список учеников у наставника
    students_resp = await client.get("/api/mentor/students", headers=mentor["headers"])
    assert students_resp.status_code == 200
    assert any(s["id"] == student["id"] for s in students_resp.json()["students"])

    # 2. Наставник создает ДЗ
    hw_create_resp = await client.post(
        "/api/homework/",
        headers=mentor["headers"],
        json={
            "title": "Домашняя работа №1: Алгебра",
            "description": "Решить задачи 1-5 и прикрепить фото решения.",
            "attachments": ["https://example.com/sheet.pdf"],
        },
    )
    assert hw_create_resp.status_code == 200
    hw_id = hw_create_resp.json()["homework_id"]

    # 3. Наставник назначает ДЗ ученику
    assign_resp = await client.post(
        f"/api/homework/{hw_id}/assign",
        headers=mentor["headers"],
        json={"student_ids": [student["id"]]},
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["students_assigned"] == 1

    # 4. Ученик видит свое ДЗ
    student_hw_resp = await client.get("/api/homework/student", headers=student["headers"])
    assert student_hw_resp.status_code == 200
    items = student_hw_resp.json()["items"]
    assert len(items) >= 1
    target_hw = items[0]
    assert target_hw["title"] == "Домашняя работа №1: Алгебра"
    assert target_hw["status"] == "pending"

    # 5. Ученик просматривает детали ДЗ
    details_resp = await client.get(
        f"/api/homework/student/{target_hw['student_homework_id']}",
        headers=student["headers"],
    )
    assert details_resp.status_code == 200
    assert details_resp.json()["title"] == "Домашняя работа №1: Алгебра"

    # 6. Ученик сдает выполненное ДЗ
    submit_resp = await client.post(
        f"/api/homework/student/{target_hw['student_homework_id']}/submit",
        headers=student["headers"],
        json={
            "student_comment": "Все задачи решены, ответы проверены.",
            "student_attachments": ["https://example.com/solution.png"],
        },
    )
    assert submit_resp.status_code == 200

    # 7. Наставник проверяет детали сданного ДЗ
    mentor_hw_details = await client.get(
        f"/api/homework/mentor/{hw_id}",
        headers=mentor["headers"],
    )
    assert mentor_hw_details.status_code == 200
    details_data = mentor_hw_details.json()
    assert details_data["homework"]["students_completed"] == 1
    assert details_data["students"][0]["status"] == "completed"
    assert details_data["students"][0]["student_comment"] == "Все задачи решены, ответы проверены."
