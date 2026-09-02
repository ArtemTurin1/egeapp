"""
Тесты модуля аутентификации и регистрации КогдаУрок.
"""

import pytest


@pytest.mark.asyncio
async def test_register_email_success(client):
    response = await client.post(
        "/api/auth/register-email",
        json={
            "email": "newuser@kogdaurok.test",
            "name": "Новый Пользователь",
            "password": "strongpassword123",
            "is_mentor": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "newuser@kogdaurok.test"
    assert data["user"]["name"] == "Новый Пользователь"
    assert "level" not in data["user"]


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    # Регистрируем повторно того же пользователя
    response = await client.post(
        "/api/auth/register-email",
        json={
            "email": "newuser@kogdaurok.test",
            "name": "Повторный Пользователь",
            "password": "strongpassword123",
        },
    )
    assert response.status_code == 400
    assert "уже зарегистрирован" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_email_success(client):
    response = await client.post(
        "/api/auth/login-email",
        json={
            "email": "newuser@kogdaurok.test",
            "password": "strongpassword123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "newuser@kogdaurok.test"
    assert "level" not in data["user"]


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    response = await client.post(
        "/api/auth/login-email",
        json={
            "email": "newuser@kogdaurok.test",
            "password": "wrong_password_xyz",
        },
    )
    assert response.status_code == 401
    assert "Неверный" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_current_user_profile(client, test_user):
    # Успешный запрос с JWT токеном
    response = await client.get("/api/auth/me", headers=test_user["headers"])
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == test_user["email"]
    assert data["id"] == test_user["id"]
    assert "level" not in data

    # Запрос без токена -> 401
    unauth_response = await client.get("/api/auth/me")
    assert unauth_response.status_code == 401


@pytest.mark.asyncio
async def test_registration_code_flow(client):
    # 1. Генерация кода
    gen_resp = await client.post(
        "/api/auth/code/generate",
        json={"telegram_id": 999888777, "telegram_username": "tg_tester", "code": "TGTEST1"},
    )
    assert gen_resp.status_code == 200

    # 2. Проверка кода
    verify_resp = await client.post(
        "/api/auth/code/verify",
        json={"code": "TGTEST1"},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True

    # 3. Регистрация по коду
    reg_resp = await client.post(
        "/api/auth/code/register",
        json={"code": "TGTEST1", "name": "Телеграм Юзер"},
    )
    assert reg_resp.status_code == 200
    data = reg_resp.json()
    assert "access_token" in data
    assert data["user"]["name"] == "Телеграм Юзер"
    assert "level" not in data["user"]


@pytest.mark.asyncio
async def test_update_profile(client, test_user):
    resp = await client.put(
        "/api/profile/update",
        headers=test_user["headers"],
        json={"name": "Обновленное Имя"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Обновленное Имя"
