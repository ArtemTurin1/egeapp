-- ============================================================================
-- SQL Скрипт создания тестовых наставников, учеников, кодов и ДЗ
-- Пароль у всех пользователей: 123456
-- ============================================================================

-- 1. Добавление наставников (Учителей)
INSERT INTO users (email, name, password_hash, is_mentor, created_at, auth_type, telegram_id, telegram_username)
VALUES 
  ('teacher1@example.com', 'Иван Петров (Учитель)', 'f187a74794e7fa615baae8a3622416f5c88c03e351ff70c57173b22e1b15d2a9', true, NOW(), 'email', 100001, 'petrov_math'),
  ('teacher2@example.com', 'Анна Смирнова (Учитель)', 'f187a74794e7fa615baae8a3622416f5c88c03e351ff70c57173b22e1b15d2a9', true, NOW(), 'email', 100002, 'smirnova_phys')
ON CONFLICT (email) DO NOTHING;

-- 2. Добавление учеников
INSERT INTO users (email, name, password_hash, is_mentor, created_at, auth_type, telegram_id, telegram_username)
VALUES 
  ('student1@example.com', 'Алексей Сидоров', 'f187a74794e7fa615baae8a3622416f5c88c03e351ff70c57173b22e1b15d2a9', false, NOW(), 'email', 200001, 'sidorov_alex'),
  ('student2@example.com', 'Мария Кузнецова', 'f187a74794e7fa615baae8a3622416f5c88c03e351ff70c57173b22e1b15d2a9', false, NOW(), 'email', 200002, 'kuznetsova_m'),
  ('student3@example.com', 'Дмитрий Васильев', 'f187a74794e7fa615baae8a3622416f5c88c03e351ff70c57173b22e1b15d2a9', false, NOW(), 'email', 200003, 'vasiliev_dima')
ON CONFLICT (email) DO NOTHING;

-- 3. Добавление кодов авторизации/регистрации
INSERT INTO registration_codes (code, telegram_id, telegram_username, is_used, created_at, used_at)
VALUES 
  ('TEACH1', 100001, 'petrov_math', true, NOW(), NOW()),
  ('TEACH2', 100002, 'smirnova_phys', true, NOW(), NOW()),
  ('STUD01', 200001, 'sidorov_alex', true, NOW(), NOW()),
  ('STUD02', 200002, 'kuznetsova_m', true, NOW(), NOW()),
  ('STUD03', 200003, 'vasiliev_dima', true, NOW(), NOW())
ON CONFLICT (code) DO NOTHING;

-- 4. Привязка учеников к наставникам (mentor_students)
-- Связываем Учителя 1 (teacher1@example.com) с Алексеем и Марией
INSERT INTO mentor_students (mentor_id, student_id, created_at)
SELECT m.id, s.id, NOW()
FROM users m, users s
WHERE m.email = 'teacher1@example.com' AND s.email IN ('student1@example.com', 'student2@example.com')
ON CONFLICT (mentor_id, student_id) DO NOTHING;

-- Связываем Учителя 2 (teacher2@example.com) с Дмитрием
INSERT INTO mentor_students (mentor_id, student_id, created_at)
SELECT m.id, s.id, NOW()
FROM users m, users s
WHERE m.email = 'teacher2@example.com' AND s.email = 'student3@example.com'
ON CONFLICT (mentor_id, student_id) DO NOTHING;

-- 5. Домашнее задание от teacher1@example.com
INSERT INTO homeworks (mentor_id, title, description, attachments, created_at)
SELECT id, 'ДЗ №1: Профильная математика (Параметры и Тригонометрия)', 'Решить задачи №12 и №17 из демоверсии ЕГЭ. Прикрепить решения.', '["https://example.com/math_hw1.pdf"]', NOW()
FROM users WHERE email = 'teacher1@example.com'
LIMIT 1;

-- 6. Назначение ДЗ ученикам
INSERT INTO student_homeworks (homework_id, student_id, status, student_comment, student_attachments, assigned_at, completed_at)
SELECT h.id, s.id, 'completed', 'Решил все задачи, ответы в файле', '["https://example.com/solution_alex.png"]', NOW(), NOW()
FROM homeworks h
JOIN users m ON h.mentor_id = m.id AND m.email = 'teacher1@example.com'
JOIN users s ON s.email = 'student1@example.com'
LIMIT 1;

INSERT INTO student_homeworks (homework_id, student_id, status, student_comment, student_attachments, assigned_at, completed_at)
SELECT h.id, s.id, 'pending', '', '[]', NOW(), NULL
FROM homeworks h
JOIN users m ON h.mentor_id = m.id AND m.email = 'teacher1@example.com'
JOIN users s ON s.email = 'student2@example.com'
LIMIT 1;

-- 7. Расписание уроков
INSERT INTO lessons (mentor_id, student_id, title, subject, start_time, duration_minutes, lesson_link, notes, notified_1h, notified_15m, created_at)
SELECT m.id, s.id, 'Разбор сложных параметров (Задание №18 ЕГЭ)', 'Математика', NOW() + INTERVAL '2 hours', 60, 'https://meet.google.com/abc-defg-hij', 'Повторить свойства квадратичной функции', false, false, NOW()
FROM users m, users s
WHERE m.email = 'teacher1@example.com' AND s.email = 'student1@example.com'
LIMIT 1;

INSERT INTO lessons (mentor_id, student_id, title, subject, start_time, duration_minutes, lesson_link, notes, notified_1h, notified_15m, created_at)
SELECT m.id, s.id, 'Динамическое программирование (Задание №27 ЕГЭ)', 'Информатика', NOW() + INTERVAL '1 day 4 hours', 90, 'https://zoom.us/j/123456789', 'Открыть среду разработки Python', false, false, NOW()
FROM users m, users s
WHERE m.email = 'teacher1@example.com' AND s.email = 'student2@example.com'
LIMIT 1;

