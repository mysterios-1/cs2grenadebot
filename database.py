import asyncio
import os

import aiosqlite
from datetime import datetime, timedelta

import os

DB_PATH = "/data/smoke_bot.db"  # Абсолютный путь!

async def init_db():
    """Единая функция инициализации всех таблиц базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Таблица пользователей
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            access_until TEXT,
            referrer_id INTEGER,
            balance_days INTEGER DEFAULT 0,
            registered_at TEXT DEFAULT (datetime('now'))
        )''')
        
        # 2. Таблица платежей
        await db.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            days_purchased INTEGER,
            status TEXT,
            payment_id TEXT UNIQUE,
            created_at TEXT DEFAULT (datetime('now'))
        )''')
        
        # 3. Таблица раскидок гранат
        await db.execute("""
            CREATE TABLE IF NOT EXISTS throws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                map_name TEXT NOT NULL,
                grenade_type TEXT NOT NULL,
                title TEXT NOT NULL,
                photo_pos TEXT NOT NULL,
                photo_aim TEXT NOT NULL,
                photo_result TEXT DEFAULT NULL,
                description TEXT,
                throw_type TEXT NOT NULL,
                zone TEXT DEFAULT 'a',
                side TEXT DEFAULT 't',
                combo_id TEXT DEFAULT NULL
            )
        """)
        await db.commit()
        
        # 4. Таблица для хранения фото бота
        await db.execute('''CREATE TABLE IF NOT EXISTS bot_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            file_id TEXT
        )''')
        await db.commit()
        
        # Проверяем и добавляем недостающие колонки
        cursor = await db.execute("PRAGMA table_info(throws)")
        columns = [col[1] for col in await cursor.fetchall()]
        
        if 'photo_result' not in columns:
            await db.execute("ALTER TABLE throws ADD COLUMN photo_result TEXT DEFAULT NULL")
            await db.commit()
            
        if 'combo_id' not in columns:
            await db.execute("ALTER TABLE throws ADD COLUMN combo_id TEXT DEFAULT NULL")
            await db.commit()
            
        if 'side' not in columns:
            await db.execute("ALTER TABLE throws ADD COLUMN side TEXT DEFAULT 't'")
            await db.commit()
            
        if 'zone' not in columns:
            await db.execute("ALTER TABLE throws ADD COLUMN zone TEXT DEFAULT 'a'")
            await db.commit()
        
        # Создаем индексы для ускорения
        await db.execute("CREATE INDEX IF NOT EXISTS idx_throws_map_type ON throws(map_name, grenade_type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_throws_combo ON throws(combo_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users(referrer_id)")
        await db.commit()

        cursor = await db.execute("PRAGMA table_info(users)")
        user_columns = [col[1] for col in await cursor.fetchall()]

        if "expiry_notice_sent" not in user_columns:
            await db.execute(
                "ALTER TABLE users ADD COLUMN expiry_notice_sent INTEGER DEFAULT 0"
            )
            await db.commit()


# ==================== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ====================

async def add_user(user_id: int, username: str, full_name: str, referrer_id: int = None, bot = None) -> tuple:
    """
    Добавляет пользователя в БД, обрабатывает реферальную систему.
    Возвращает: (success, valid_referrer_id, referrer_name)
    """
    # Переменные, которые понадобятся вне блока работы с БД
    success = False
    valid_referrer = None
    referrer_name = None
    referrer_until = None

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Проверяем, существует ли пользователь
        async with db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)) as cursor:
            existing = await cursor.fetchone()
        
        if existing:
            return False, None, None

        now = datetime.now()
        access_until = now + timedelta(days=7)

        # 2. Проверяем реферера и сразу достаем все нужные данные ОДНИМ запросом
        if referrer_id and referrer_id != user_id:
            query_ref = "SELECT user_id, full_name, username, access_until FROM users WHERE user_id = ?"
            async with db.execute(query_ref, (referrer_id,)) as cursor:
                ref_row = await cursor.fetchone()

            if ref_row:
                valid_referrer = referrer_id
                ref_full_name = ref_row[1]
                ref_username = ref_row[2]
                ref_access_until_str = ref_row[3]

                # Формируем красивое имя реферера для возврата в хэндлер /start
                referrer_name = ref_full_name or ref_username or str(referrer_id)

                # Считаем новую дату подписки реферера
                referrer_until = now
                if ref_access_until_str:
                    try:
                        referrer_until = datetime.strptime(ref_access_until_str, "%Y-%m-%d %H:%M:%S")
                        if referrer_until < now:
                            referrer_until = now
                    except ValueError:
                        referrer_until = now

                referrer_until += timedelta(days=7)

                # Обновляем подписку рефереру
                await db.execute(
                    "UPDATE users SET access_until = ?, expiry_notice_sent = 0 WHERE user_id = ?",
                    (referrer_until.strftime("%Y-%m-%d %H:%M:%S"), referrer_id),
                )

        # 3. Создаём нового пользователя
        await db.execute(
            """
            INSERT INTO users (user_id, username, full_name, access_until, referrer_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                full_name,
                access_until.strftime("%Y-%m-%d %H:%M:%S"),
                valid_referrer,
            ),
        )
        await db.commit()
        success = True

    # 4. 🔥 ОТПРАВЛЯЕМ УВЕДОМЛЕНИЕ РЕФЕРЕРУ СТРОГО ПОСЛЕ ЗАКРЫТИЯ СОЕДИНЕНИЯ С БД
    if success and valid_referrer and bot:
        try:
            new_user_name = full_name or username or str(user_id)
            await bot.send_message(
                valid_referrer,
                f"🎉 <b>Новый реферал!</b>\n\n"
                f"По вашей ссылке зарегистрировался новый пользователь:\n"
                f"👤 {new_user_name}\n\n"
                f"✨ Вы получили <b>+7 дней</b> доступа!\n"
                f"📅 Теперь подписка действует до <b>{referrer_until.strftime('%d.%m.%Y %H:%M')}</b>"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление рефереру {valid_referrer}: {e}")

    return success, valid_referrer, referrer_name


async def check_access(user_id: int) -> bool:
    """
    Проверка доступа пользователя.
    Администраторы всегда имеют полный доступ.
    """
    ADMINS = [2129614624]
    
    # Администраторы всегда имеют доступ
    if user_id in ADMINS:
        return True
        
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем текущее время в нужном формате для сравнения строк в SQL
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Запрос проверяет: активны ли дни доступа ИЛИ не истекла ли дата окончания
        query = """
            SELECT 1 FROM users 
            WHERE user_id = ? AND (
                (balance_days IS NOT NULL AND balance_days > 0) OR 
                (access_until IS NOT NULL AND access_until > ?)
            )
            LIMIT 1
        """
        
        async with db.execute(query, (user_id, now_str)) as cursor:
            row = await cursor.fetchone()
            # Если строка найдена — доступ есть (True), если нет — доступа нет (False)
            return row is not None

async def add_days(user_id, days):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT access_until FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

        current = datetime.now()

        if row and row[0]:
            try:
                saved_date = datetime.strptime(
                    row[0], "%Y-%m-%d %H:%M:%S"
                )
                if saved_date > current:
                    current = saved_date
            except ValueError:
                pass

        new_until = current + timedelta(days=days)

        await db.execute(
            "UPDATE users SET access_until = ?, expiry_notice_sent = 0 WHERE user_id = ?",
            (new_until.strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        await db.commit()

        return new_until

async def get_user_info(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT access_until, balance_days, referrer_id FROM users WHERE user_id=?", (user_id,))
        return await cursor.fetchone()

async def get_referral_count(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

# ==================== ПЛАТЕЖИ И СТАТИСТИКА ====================

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        total = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM users WHERE access_until IS NOT NULL AND datetime(access_until) > datetime('now')")
        active = (await cursor.fetchone())[0]
        return total, active

async def save_payment(user_id, amount, days, payment_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO payments (user_id, amount, days_purchased, status, payment_id) VALUES (?,?,?,?,?)",
                        (user_id, amount, days, "pending", payment_id))
        await db.commit()

async def confirm_payment(payment_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, days_purchased FROM payments WHERE payment_id=? AND status='pending'", (payment_id,))
        row = await cursor.fetchone()
        if row:
            user_id, days = row
            await db.execute("UPDATE payments SET status='confirmed' WHERE payment_id=?", (payment_id,))
            await db.execute("UPDATE users SET access_until=datetime(COALESCE(access_until, 'now'), '+' || ? || ' days') WHERE user_id=?", (days, user_id))
            await db.commit()
            return user_id, days
        return None, None

async def get_pending_payments():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, amount, days_purchased, created_at, payment_id FROM payments WHERE status='pending'")
        return await cursor.fetchall()

# ==================== РАБОТА С РАСКИДКАМИ ====================

async def add_throw(map_name, grenade_type, title, photo_pos, photo_aim, photo_result, description, throw_type, zone="a", side="t", combo_id=None):
    """Добавление раскидки с поддержкой фото результата и комбо-связок"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO throws (map_name, grenade_type, title, photo_pos, photo_aim, photo_result, description, throw_type, zone, side, combo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (map_name, grenade_type, title, photo_pos, photo_aim, photo_result, description, throw_type, zone, side, combo_id))
        await db.commit()



async def get_throws(map_name, grenade_type, zone="a", side="t", limit: int = 5, offset: int = 0):
    """Возвращает сгруппированные раскидки"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Если зона "situational" — игнорируем сторону
        if zone == "situational":
            query = """
                SELECT id, title FROM throws 
                WHERE map_name = ? AND grenade_type = ? AND zone = ?
                GROUP BY COALESCE(combo_id, id)
                ORDER BY COALESCE(combo_id, id)
                LIMIT ? OFFSET ?
            """
            params = (map_name, grenade_type, zone, limit, offset)
        else:
            query = """
                SELECT id, title FROM throws 
                WHERE map_name = ? AND grenade_type = ? AND zone = ? AND side = ?
                GROUP BY COALESCE(combo_id, id)
                ORDER BY COALESCE(combo_id, id)
                LIMIT ? OFFSET ?
            """
            params = (map_name, grenade_type, zone, side, limit, offset)
        
        async with db.execute(query, params) as cursor:
            return await cursor.fetchall()

async def get_throws_count(map_name, grenade_type, zone="a", side="t") -> int:
    """Возвращает количество уникальных раскидок"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Если зона "situational" — игнорируем сторону
        if zone == "situational":
            query = """
                SELECT COUNT(DISTINCT COALESCE(combo_id, id)) FROM throws 
                WHERE map_name = ? AND grenade_type = ? AND zone = ?
            """
            params = (map_name, grenade_type, zone)
        else:
            query = """
                SELECT COUNT(DISTINCT COALESCE(combo_id, id)) FROM throws 
                WHERE map_name = ? AND grenade_type = ? AND zone = ? AND side = ?
            """
            params = (map_name, grenade_type, zone, side)
        
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_throw_detail(throw_id):
    """Получить полную информацию о конкретном броске (все 12 полей)"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM throws WHERE id = ?", (throw_id,)) as cursor:
            return await cursor.fetchone()

async def get_combo_throws(combo_id: str):
    """Возвращает все гранаты одной комбо-связки в порядке добавления"""
    if not combo_id:
        return []

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, title, photo_aim, photo_result, throw_type
            FROM throws
            WHERE combo_id = ?
            ORDER BY id
        """, (combo_id,)) as cursor:
            return await cursor.fetchall()

async def save_bot_photo(key: str, file_id: str):
    """Сохраняет file_id фото в БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO bot_photos (key, file_id) VALUES (?, ?)",
            (key, file_id)
        )
        await db.commit()

async def get_bot_photo(key: str) -> str:
    """Получает file_id фото из БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT file_id FROM bot_photos WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def get_subscription_text(user_id):
    if user_id == 2129614624:
        return "Бессрочно"

    user_info = await get_user_info(user_id)
    if not user_info or not user_info[0]:
        return "Нет доступа"

    try:
        access_until = datetime.strptime(
            user_info[0], "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        return "Нет доступа"

    if access_until <= datetime.now():
        return "Истёк"

    return f"до {access_until.strftime('%d.%m.%Y %H:%M')}"

async def get_expiring_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT user_id, access_until
            FROM users
            WHERE access_until IS NOT NULL
              AND datetime(access_until) > datetime('now')
              AND datetime(access_until) <= datetime('now', '+1 day')
              AND expiry_notice_sent = 0
            """
        )
        return await cursor.fetchall()


async def mark_expiry_notice_sent(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET expiry_notice_sent = 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()





