"""
Telegram-бот КогдаУрок.
Обеспечивает авторизацию и регистрацию пользователей по кодам,
проверку профиля и отправку сервисных сообщений и напоминаний об уроках.
"""

import asyncio
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy import select

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PROXY, FRONTEND_URL, get_logger
from models import async_session, User, RegistrationCode, Lesson

logger = get_logger("telegram_bot")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
MSK_TZ = timezone(timedelta(hours=3))


def to_msk(dt: datetime) -> str:
    """Конвертирует datetime в строку московского времени (МСК, UTC+3)."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_msk = dt.astimezone(MSK_TZ)
    return dt_msk.strftime("%d.%m.%Y в %H:%M МСК")


async def check_and_send_lesson_reminders(client: httpx.AsyncClient):
    """
    Проверяет ближайшие уроки и отправляет напоминания в Telegram (за 1 час и за 15 минут) по МСК.
    """
    try:
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            # Ищем предстоящие уроки в диапазоне следующих 2 часов
            stmt = (
                select(Lesson)
                .where(
                    Lesson.start_time > now,
                    (Lesson.notified_1h == False) | (Lesson.notified_15m == False),
                )
            )
            res = await db.execute(stmt)
            lessons = res.scalars().all()

            for lesson in lessons:
                diff_sec = (lesson.start_time - now).total_seconds()
                
                # Загружаем учителя и ученика
                mentor_res = await db.execute(select(User).where(User.id == lesson.mentor_id))
                mentor = mentor_res.scalars().first()
                student_res = await db.execute(select(User).where(User.id == lesson.student_id))
                student = student_res.scalars().first()

                time_str = to_msk(lesson.start_time)
                link_text = f"\n🔗 <b>Ссылка на урок:</b> {lesson.lesson_link}" if lesson.lesson_link else ""

                # 1. Напоминание за 1 час: срабатывает ТОЛЬКО в интервале от 30 до 60 минут!
                if 1800 < diff_sec <= 3600 and not lesson.notified_1h:
                    mins_left = max(1, int(diff_sec // 60))
                    text = (
                        f"⏰ <b>Напоминание: Урок начнется через ~{mins_left} мин!</b>\n\n"
                        f"📚 <b>Тема:</b> {lesson.title} ({lesson.subject})\n"
                        f"🕒 <b>Время:</b> {time_str}\n"
                        f"👨‍🏫 <b>Наставник:</b> {mentor.name if mentor else 'Преподаватель'}\n"
                        f"👨‍🎓 <b>Ученик:</b> {student.name if student else 'Ученик'}"
                        f"{link_text}\n\n"
                    )
                    if student and student.telegram_id:
                        await send_message(client, student.telegram_id, text)
                    if mentor and mentor.telegram_id:
                        await send_message(client, mentor.telegram_id, text)

                    lesson.notified_1h = True
                elif diff_sec <= 1800 and not lesson.notified_1h:
                    # Если урок создан менее чем за 30 мин до начала, помечаем, чтобы не отправлять ложное "через 1 час"
                    lesson.notified_1h = True

                # 2. Напоминание за 15 минут (<= 900 сек)
                if 0 < diff_sec <= 900 and not lesson.notified_15m:
                    mins_left = max(1, int(diff_sec // 60))
                    text_urgent = (
                        f"⚡ <b>Урок начнется через {mins_left} мин!</b>\n\n"
                        f"📚 <b>Тема:</b> {lesson.title} ({lesson.subject})\n"
                        f"🕒 <b>Время:</b> {time_str}"
                        f"{link_text}\n\n"
                    )
                    if student and student.telegram_id:
                        await send_message(client, student.telegram_id, text_urgent)
                    if mentor and mentor.telegram_id:
                        await send_message(client, mentor.telegram_id, text_urgent)

                    lesson.notified_15m = True

            await db.commit()
    except Exception as e:
        logger.error("Ошибка при проверке напоминаний уроков: %s", e)


def generate_random_code(length: int = 6) -> str:
    """Генерирует надежный 6-значный код из читаемых символов."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choices(alphabet, k=length))


async def get_or_create_code_for_user(
    telegram_id: int,
    first_name: str = "",
    username: Optional[str] = None,
    last_name: str = "",
) -> tuple[str, bool]:
    """
    Возвращает (code, is_new).
    Если есть свежий неиспользованный код — возвращает его, иначе генерирует новый.
    """
    full_name = f"{first_name} {last_name}".strip() if last_name else (first_name or username or f"User_{telegram_id}")

    async with async_session() as db:
        # Проверяем неиспользованный код
        stmt = (
            select(RegistrationCode)
            .where(
                RegistrationCode.telegram_id == telegram_id,
                RegistrationCode.is_used == False,
            )
            .order_by(RegistrationCode.created_at.desc())
        )
        result = await db.execute(stmt)
        existing = result.scalars().first()
        if existing:
            # Обновляем имя, если оно изменилось
            existing.telegram_username = full_name
            await db.commit()
            return existing.code, False

        # Генерируем уникальный код
        for _ in range(10):
            code = generate_random_code(6)
            check_stmt = select(RegistrationCode).where(RegistrationCode.code == code)
            check_res = await db.execute(check_stmt)
            if not check_res.scalars().first():
                break

        reg_code = RegistrationCode(
            code=code,
            telegram_id=telegram_id,
            telegram_username=full_name,
            is_used=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(reg_code)
        await db.commit()
        return code, True


async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Получает пользователя по его Telegram ID."""
    async with async_session() as db:
        stmt = select(User).where(User.telegram_id == telegram_id)
        res = await db.execute(stmt)
        return res.scalars().first()


async def send_message(
    client: httpx.AsyncClient,
    chat_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Отправляет текстовое сообщение пользователю Telegram."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = await client.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        if resp.status_code != 200:
            logger.error("Ошибка отправки сообщения: %s %s", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        logger.error("Исключение при отправке сообщения в Telegram: %s", e)
        return False


def get_main_keyboard() -> dict:
    """Клавиатура с основными кнопками."""
    return {
        "keyboard": [
            [{"text": "📝 Получить код"}, {"text": "👤 Мой профиль"}],
            [{"text": "🔄 Сменить роль"}, {"text": "❓ Помощь"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def get_web_button_markup() -> dict:
    """Инлайн-кнопка для быстрого перехода на платформу."""
    url = FRONTEND_URL.rstrip("/")
    return {
        "inline_keyboard": [
            [{"text": "🌐 Открыть КогдаУрок", "url": f"{url}/register"}],
        ]
    }


async def handle_start_or_code(
    client: httpx.AsyncClient,
    chat_id: int,
    first_name: str,
    username: Optional[str],
    last_name: str = "",
):
    """Обработка команды /start, /code или нажатия «📝 Получить код»."""
    user = await get_user_by_telegram_id(chat_id)
    full_name = f"{first_name} {last_name}".strip() if last_name else (first_name or username or "Пользователь")
    code, is_new = await get_or_create_code_for_user(chat_id, first_name=first_name, username=username, last_name=last_name)
    url = FRONTEND_URL.rstrip("/")

    if user:
        role = "👨‍🏫 Наставник" if user.is_mentor else "👨‍🎓 Ученик"
        text = (
            f"👋 С возвращением, <b>{user.name or full_name}</b>!\n\n"
            f"✅ Вы зарегистрированы в <b>КогдаУрок</b> ({role}).\n\n"
            f"🔐 <b>Ваш код для входа:</b> <code>{code}</code>\n"
            f"<i>(нажмите на код, чтобы скопировать)</i>\n\n"
            f"🌐 <b>Сайт платформы:</b> <a href=\"{url}\">{url}</a>\n\n"
            f"Используйте этот код для мгновенного входа."
        )
    else:
        text = (
            f"👋 Привет, <b>{first_name}</b>!\n\n"
            f"Добро пожаловать в <b>КогдаУрок</b> — единую платформу для занятий с наставниками и управления расписанием! 🚀\n\n"
            f"🔐 <b>Ваш код для входа / регистрации:</b> <code>{code}</code>\n"
            f"<i>(нажмите на код, чтобы скопировать)</i>\n\n"
            f"📋 <b>Как войти на сайт:</b>\n"
            f"1. Откройте сайт: <a href=\"{url}/register\">КогдаУрок Вход</a>\n"
            f"2. Выберите вкладку <b>«Telegram»</b> и вставьте код <code>{code}</code>\n"
            f"3. Вы сразу войдете под своим именем <b>{full_name}</b>!\n\n"
            f"Успешных занятий! 📚✨"
        )

    await send_message(client, chat_id, text, reply_markup=get_main_keyboard())


async def handle_role_switch(client: httpx.AsyncClient, chat_id: int):
    """Смена роли пользователя (Учитель <-> Ученик)."""
    async with async_session() as db:
        stmt = select(User).where(User.telegram_id == chat_id)
        res = await db.execute(stmt)
        user = res.scalars().first()

        if not user:
            code, _ = await get_or_create_code_for_user(chat_id)
            url = FRONTEND_URL.rstrip("/")
            text = (
                f"❌ <b>Аккаунт не найден</b>\n\n"
                f"Сначала войдите на сайт с кодом: <code>{code}</code>\n"
                f"👉 Ссылка: <a href=\"{url}/register\">{url}/register</a>"
            )
            await send_message(client, chat_id, text, reply_markup=get_main_keyboard())
            return

        # Переключаем роль
        user.is_mentor = not user.is_mentor
        await db.commit()
        await db.refresh(user)

        new_role = "👨‍🏫 <b>Наставник (Учитель)</b>" if user.is_mentor else "👨‍🎓 <b>Ученик</b>"
        extra_info = "Теперь вам доступны функции создания уроков и выдачи ДЗ." if user.is_mentor else "Теперь вам доступен просмотр расписания и сдача ДЗ."

        text = (
            f"🔄 <b>Роль успешно изменена!</b>\n\n"
            f"Ваша новая роль: {new_role}\n"
            f"{extra_info}\n\n"
            f"💡 <i>Обновите страницу на сайте, чтобы увидеть изменения интерфейса.</i>"
        )
        await send_message(client, chat_id, text, reply_markup=get_main_keyboard())


async def handle_profile(client: httpx.AsyncClient, chat_id: int, first_name: str):
    """Обработка кнопки «👤 Мой профиль» или команды /profile."""
    user = await get_user_by_telegram_id(chat_id)
    url = FRONTEND_URL.rstrip("/")

    if user:
        role = "👨‍🏫 Наставник (Учитель)" if user.is_mentor else "👨‍🎓 Ученик"
        reg_date = user.created_at.strftime("%d.%m.%Y") if user.created_at else "—"
        text = (
            f"👤 <b>Ваш профиль в КогдаУрок:</b>\n\n"
            f"🏷 <b>Имя:</b> {user.name or 'Не указано'}\n"
            f"📧 <b>Email:</b> {user.email}\n"
            f"🎭 <b>Роль:</b> {role}\n"
            f"📅 <b>Дата регистрации:</b> {reg_date}\n\n"
            f"💡 <i>Чтобы сменить роль на {'Ученика' if user.is_mentor else 'Наставника'}, нажмите кнопку «🔄 Сменить роль».</i>\n\n"
            f"🌐 <b>Перейти в личный кабинет:</b> <a href=\"{url}/profile\">{url}/profile</a>"
        )
    else:
        code, _ = await get_or_create_code_for_user(chat_id)
        text = (
            f"❌ <b>Аккаунт не найден</b>\n\n"
            f"Вы еще не завершили регистрацию на сайте.\n\n"
            f"🔐 <b>Ваш код регистрации:</b> <code>{code}</code>\n"
            f"👉 Завершите регистрацию на <a href=\"{url}/register\">{url}/register</a>"
        )

    await send_message(client, chat_id, text, reply_markup=get_main_keyboard())


async def handle_help(client: httpx.AsyncClient, chat_id: int):
    """Обработка кнопки «❓ Помощь» или команды /help."""
    url = FRONTEND_URL.rstrip("/")
    text = (
        f"📖 <b>Справка КогдаУрок:</b>\n\n"
        f"🤖 <b>Зачем нужен этот бот?</b>\n"
        f"Бот генерирует безопасные одноразовые коды для быстрой регистрации и авторизации на сайте без сложных паролей, позволяет переключать роль между Учителем и Учеником, а также отправляет напоминания об уроках за 1 час и за 15 минут до начала.\n\n"
        f"📌 <b>Основные команды:</b>\n"
        f"• <b>📝 Получить код</b> — выдает новый код доступа\n"
        f"• <b>👤 Мой профиль</b> — показывает данные вашего аккаунта\n"
        f"• <b>🔄 Сменить роль</b> — переключение роли Учитель / Ученик\n"
        f"• <b>❓ Помощь</b> — эта подсказка\n\n"
        f"🌐 <b>Сайт КогдаУрок:</b> <a href=\"{url}\">{url}</a>"
    )
    await send_message(client, chat_id, text, reply_markup=get_main_keyboard())


async def process_update(client: httpx.AsyncClient, update: dict):
    """Обработка входящего события от Telegram."""
    message = update.get("message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return

    from_user = message.get("from", {})
    first_name = from_user.get("first_name", "Пользователь")
    last_name = from_user.get("last_name", "")
    username = from_user.get("username")
    text = (message.get("text") or "").strip()

    logger.info("📩 Сообщение от %s %s (@%s, id=%s): %s", first_name, last_name, username, chat_id, text)

    if text in ("/start", "/code", "📝 Получить код", "🔑 Новый код", "Получить код"):
        await handle_start_or_code(client, chat_id, first_name, username, last_name)
    elif text in ("/role", "/mentor", "🔄 Сменить роль", "Сменить роль", "Стать наставником", "Стать учеником"):
        await handle_role_switch(client, chat_id)
    elif text in ("/profile", "/status", "👤 Мой профиль", "Мой профиль", "🔑 Мой статус"):
        await handle_profile(client, chat_id, first_name)
    elif text in ("/help", "❓ Помощь", "Помощь", "Инструкция"):
        await handle_help(client, chat_id)
    else:
        # Любой другой текст — генерируем код или подсказываем
        await handle_start_or_code(client, chat_id, first_name, username, last_name)



async def run_bot_polling():
    """
    Фоновый цикл long-polling для Telegram бота.
    Автоматически восстанавливается при сетевых сбоях.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN не задан. Telegram-бот не будет запущен.")
        return

    logger.info("🤖 Запуск Telegram-бота КогдаУрок...")
    offset = 0

    proxy_arg = TELEGRAM_PROXY if TELEGRAM_PROXY else None
    async with httpx.AsyncClient(timeout=45.0, proxy=proxy_arg) as client:
        # Проверяем доступность токена
        try:
            me_resp = await client.get(f"{TELEGRAM_API_URL}/getMe")
            if me_resp.status_code == 200:
                bot_info = me_resp.json().get("result", {})
                logger.info(
                    "✅ Telegram-бот успешно авторизован: @%s (%s)",
                    bot_info.get("username"),
                    bot_info.get("first_name"),
                )
            else:
                logger.error("❌ Ошибка авторизации бота в Telegram: %s", me_resp.text)
                return
        except Exception as e:
            logger.warning("⚠️ Не удалось проверить токен бота при старте: %s", e)

        last_reminder_check = 0.0

        while True:
            try:
                # Периодическая проверка напоминаний (каждые 30 секунд)
                current_time = asyncio.get_event_loop().time()
                if current_time - last_reminder_check > 30:
                    last_reminder_check = current_time
                    asyncio.create_task(check_and_send_lesson_reminders(client))

                resp = await client.get(
                    f"{TELEGRAM_API_URL}/getUpdates",
                    params={"offset": offset, "timeout": 25},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    updates = data.get("result", [])
                    for update in updates:
                        offset = max(offset, update["update_id"] + 1)
                        try:
                            await process_update(client, update)
                        except Exception as update_err:
                            logger.error("Ошибка при обработке update %s: %s", update.get("update_id"), update_err)
                elif resp.status_code == 409:
                    logger.warning("Конфликт getUpdates (другой экземпляр бота запущен). Ожидание 5 сек...")
                    await asyncio.sleep(5)
                else:
                    logger.warning("getUpdates вернул статус %s: %s", resp.status_code, resp.text)
                    await asyncio.sleep(3)
            except asyncio.CancelledError:
                logger.info("🛑 Telegram-бот останавливается...")
                break
            except Exception as e:
                logger.warning("Ошибка соединения Telegram polling: %s. Повтор через 3 сек...", e)
                await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(run_bot_polling())

