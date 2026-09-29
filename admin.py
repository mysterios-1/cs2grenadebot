import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import aiosqlite
import database as db
import keyboards as kb
from aiogram.filters import Command, CommandStart
from PIL import Image, ImageDraw
import io
import aiosqlite

admin_router = Router()
ADMINS = [2129614624]  # 👈 Твой Telegram ID здесь
result_media_groups = {}

class AddThrowState(StatesGroup):
    is_combo = State()
    combo_id = State()
    map_name = State()
    grenade_type = State()
    side = State()
    zone = State()
    description = State()
    photo_pos = State()
    title = State()
    photo_aim = State()
    photo_result = State()  # НОВЫЙ ШАГ ДЛЯ ФОТО РЕЗУЛЬТАТА
    throw_type = State()
    loop_choice = State()

class EditThrowState(StatesGroup):
    throw_id = State()
    title = State()
    description = State()
    throw_type = State()

def get_cancel_kb():
    return InlineKeyboardBuilder().row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel")).as_markup()

def get_combo_choice_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Одиночная", callback_data="iscombo_no"),
        InlineKeyboardButton(text="📦 Комбо-связка (1 позиция)", callback_data="iscombo_yes")
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel"))
    return builder.as_markup()

def get_loop_choice_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить еще прицел", callback_data="loop_more"),
        InlineKeyboardButton(text="✅ Завершить связку", callback_data="loop_stop")
    )
    return builder.as_markup()

def get_admin_sides_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🛑 За Т (Атака)", callback_data="adm_side_t"), InlineKeyboardButton(text="🔷 За СТ (Защита)", callback_data="adm_side_ct"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel"))
    return builder.adjust(2, 1).as_markup()

def get_admin_zones_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Плент А", callback_data="adm_zone_a"), InlineKeyboardButton(text="Плент Б", callback_data="adm_zone_b"))
    builder.row(InlineKeyboardButton(text="Мид", callback_data="adm_zone_mid"), InlineKeyboardButton(text="Ситуация / Разное", callback_data="adm_zone_situational"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel"))
    return builder.adjust(2, 2, 1).as_markup()

def get_side_name(side_code: str) -> str:
    return "За Т" if side_code == "t" else "За СТ"

def get_zone_name(zone_code: str) -> str:
    zones = {"a": "Плент А", "b": "Плент Б", "mid": "Мид", "situational": "Ситуация"}
    return zones.get(zone_code, zone_code.upper())

@admin_router.callback_query(F.data == "adm_cancel")
async def cancel_admin_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("❌ Добавление раскидки прервано.", show_alert=True)
    await callback.message.delete()

@admin_router.message(F.text == "/add")
async def start_add_throw(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS: return
    await message.answer("Шаг 1: Какую раскидку создаем?", reply_markup=get_combo_choice_kb())
    await state.set_state(AddThrowState.is_combo)

@admin_router.callback_query(AddThrowState.is_combo, F.data.startswith("iscombo_"))
async def process_combo_choice(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split("_")[-1]
    if choice == "yes":
        await state.update_data(is_combo=True)
        await callback.message.edit_text("Шаг 2: Введите уникальный ID связки (English):\n(Например: <code>mirage_stairs_combo</code>):", parse_mode="HTML", reply_markup=get_cancel_kb())
        await state.set_state(AddThrowState.combo_id)
    else:
        await state.update_data(is_combo=False, combo_id=None)
        await callback.message.edit_text("Шаг 3: Выберите карту:", reply_markup=kb.get_admin_maps_kb())
        await state.set_state(AddThrowState.map_name)

@admin_router.message(AddThrowState.combo_id, F.text)
async def process_combo_id(message: Message, state: FSMContext):
    await state.update_data(combo_id=message.text.strip())
    builder = InlineKeyboardBuilder.from_markup(kb.get_admin_maps_kb())
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel"))
    await message.answer("Шаг 3: Выберите карту:", reply_markup=builder.as_markup())
    await state.set_state(AddThrowState.map_name)

@admin_router.callback_query(AddThrowState.map_name, F.data.startswith("adm_map_"))
async def process_admin_map(callback: CallbackQuery, state: FSMContext):
    chosen_map = callback.data.replace("adm_map_", "")
    await state.update_data(map_name=chosen_map)
    
    # Добавляем кнопку отмены к клавиатуре типов гранат
    builder = InlineKeyboardBuilder.from_markup(kb.get_admin_grenades_kb())
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel"))
    
    await callback.message.edit_text(
        text=f"Карта: <b>{chosen_map.upper()}</b>\n\nШаг 4/11: Выберите тип гранаты:",
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AddThrowState.grenade_type)

# Шаг 4: Обработка типа гранаты -> Переход к выбору стороны (Т/СТ)
@admin_router.callback_query(AddThrowState.grenade_type, F.data.startswith("adm_type_"))
async def process_admin_type(callback: CallbackQuery, state: FSMContext):
    chosen_type = callback.data.replace("adm_type_", "")
    await state.update_data(grenade_type=chosen_type)  # 🌟 ТЕПЕРЬ ОН ТОЧНО СОХРАНЯЕТСЯ В FSM!
    
    await callback.message.edit_text(
        text="Шаг 5/11: Выберите СТОРОНУ применения гранаты:",
        reply_markup=get_admin_sides_kb()
    )
    await state.set_state(AddThrowState.side)

# Шаг 5: Обработка стороны -> Переход к выбору зоны (Плента)
@admin_router.callback_query(AddThrowState.side, F.data.startswith("adm_side_"))
async def process_admin_side(callback: CallbackQuery, state: FSMContext):
    chosen_side = callback.data.replace("adm_side_", "")
    await state.update_data(side=chosen_side)
    
    await callback.message.edit_text(
        text="Шаг 6/11: Выберите ЗОНУ падения гранаты:",
        reply_markup=get_admin_zones_kb()
    )
    await state.set_state(AddThrowState.zone)

@admin_router.callback_query(AddThrowState.zone, F.data.startswith("adm_zone_"))
async def process_admin_zone(callback: CallbackQuery, state: FSMContext):
    chosen_zone = callback.data.replace("adm_zone_", "")
    await state.update_data(zone=chosen_zone)
    await callback.message.edit_text("Шаг 6: Напишите описание для ПОЗИЦИИ\n(Где стоять, во что упереться):", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.description)

@admin_router.message(AddThrowState.description, F.text)
async def process_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Шаг 7: Отправьте ФОТО ПОЗИЦИИ (оно будет общим):", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.photo_pos)

@admin_router.message(AddThrowState.photo_pos, F.photo)
async def process_photo_pos(message: Message, state: FSMContext):
    await state.update_data(photo_pos=message.photo[-1].file_id)
    await message.answer("Шаг 8: Введите НАЗВАНИЕ для этой конкретной гранаты\n(Например: <i>'Смок в Окно'</i>):", parse_mode="HTML", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.title)

@admin_router.message(AddThrowState.title, F.text)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Шаг 9: Отправьте ФОТО ПРИЦЕЛА для этой гранаты:", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.photo_aim)

@admin_router.message(AddThrowState.photo_aim, F.photo)
async def process_photo_aim(message: Message, state: FSMContext):
    await state.update_data(photo_aim=message.photo[-1].file_id)
    await message.answer("Шаг 10/12: Отправьте ФОТО РЕЗУЛЬТАТА (как падает граната):", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.photo_result)

@admin_router.message(AddThrowState.photo_result, F.photo)
async def process_photo_result(message: Message, state: FSMContext):
    await state.update_data(photo_result=message.photo[-1].file_id)
    await message.answer("Шаг 11/12: Напишите МЕХАНИКУ броска (например: <code>Jumpthrow</code>):", parse_mode="HTML", reply_markup=get_cancel_kb())
    await state.set_state(AddThrowState.throw_type)

@admin_router.message(AddThrowState.throw_type, F.text)
async def process_throw_type_and_loop(message: Message, state: FSMContext):
    await state.update_data(throw_type=message.text)
    data = await state.get_data()
    
    await db.add_throw(
        map_name=data['map_name'],
        grenade_type=data['grenade_type'],
        title=data['title'],
        photo_pos=data['photo_pos'],
        photo_aim=data['photo_aim'],
        photo_result=data['photo_result'],
        description=data['description'],
        throw_type=message.text,
        zone=data['zone'],
        side=data['side'],
        combo_id=data['combo_id']
    )
    
    if data['is_combo']:
        await message.answer(
            f"✅ Граната '{data['title']}' сохранена в связку!\n\n"
            f"Хотите добавить к этой ЖЕ позиции еще одну гранату?", reply_markup=get_loop_choice_kb()
        )
        await state.set_state(AddThrowState.loop_choice)
    else:
        await message.answer(f"✅ Одиночная раскидка <b>{data['title']}</b> создана!", parse_mode="HTML")
        await state.clear()

@admin_router.callback_query(AddThrowState.loop_choice, F.data.startswith("loop_"))
async def process_loop_decision(callback: CallbackQuery, state: FSMContext):
    decision = callback.data.split("_")[-1]
    if decision == "more":
        await state.update_data(title=None, photo_aim=None, throw_type=None)
        await callback.message.edit_text(
            "📝 <b>Добавление следующего прицела с этой же точки</b>\n\n"
            "Введите НАЗВАНИЕ для нового прицела (Например: <i>'Смок на Шорт'</i>):", parse_mode="HTML"
        )
        await state.set_state(AddThrowState.title)
    else:
        data = await state.get_data()
        await callback.message.edit_text(f"🏁 <b>Все гранаты связки успешно сохранены!</b>\nID комбо: <code>{data['combo_id']}</code>", parse_mode="HTML")
        await state.clear()

# ЧИСТЫЙ ХВОСТ ДЛЯ ЗАМЕНЫ В КОНЦЕ ФАЙЛА admin.py

@admin_router.message(EditThrowState.title)
async def edit_title(message: Message, state: FSMContext):
    if message.text != "/skip": 
        await state.update_data(title=message.text)
    await message.answer("Введите новое ОПИСАНИЕ или отправьте /skip:")
    await state.set_state(EditThrowState.description)

@admin_router.message(EditThrowState.description)
async def edit_description(message: Message, state: FSMContext):
    if message.text != "/skip": 
        await state.update_data(description=message.text)
    await message.answer("Введите новый ТИП БРОСКА или отправьте /skip:")
    await state.set_state(EditThrowState.throw_type)

@admin_router.message(EditThrowState.throw_type)
async def edit_throw_type_final(message: Message, state: FSMContext):
    data = await state.get_data()
    throw_id = data["throw_id"]
    updates, params = [], []
    
    if "title" in data: 
        updates.append("title = ?")
        params.append(data["title"])
    if "description" in data: 
        updates.append("description = ?")
        params.append(data["description"])
    if message.text != "/skip": 
        updates.append("throw_type = ?")
        params.append(message.text)
        
    if updates:
        params.append(throw_id)
        # ИСПРАВЛЕНО: используем db.DB_PATH через импорт database
        import database as db
        async with aiosqlite.connect(db.DB_PATH) as conn:
            await conn.execute(f"UPDATE throws SET {', '.join(updates)} WHERE id = ?", params)
            await conn.commit()
        await message.answer("✅ Данные раскидки успешно обновлены!")
    else:
        await message.answer("⏸ Изменений не внесено.")
        
    await state.clear()



@admin_router.message(Command("checkphoto"))
async def check_photo(message: Message):
    if message.from_user.id not in ADMINS:
        return
    file_id = await db.get_bot_photo("mirage_resp")
    if file_id:
        await message.answer_photo(photo=file_id, caption="✅ Фото респов для Mirage найдено!")
    else:
        await message.answer("❌ Фото респов для Mirage не найдено в БД")

@admin_router.message(Command("listphotos"))
async def list_photos(message: Message):
    if message.from_user.id not in ADMINS:
        return
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cursor = await conn.execute("SELECT key, file_id FROM bot_photos")
        rows = await cursor.fetchall()
        if rows:
            text = "📸 Фото в БД:\n\n"
            for key, file_id in rows:
                text += f"🔑 {key}: {file_id[:20]}...\n"
            await message.answer(text)
        else:
            await message.answer("❌ В БД нет сохраненных фото")

@admin_router.message(Command("checkdb"))
async def check_db(message: Message):
    if message.from_user.id not in ADMINS:
        return
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cursor = await conn.execute("SELECT id, map_name, grenade_type, title, zone, side FROM throws")
        rows = await cursor.fetchall()
        if rows:
            text = "📊 Данные в БД:\n\n"
            for row in rows:
                text += f"ID:{row[0]} | Карта:{row[1]} | Тип:{row[2]} | Название:{row[3]} | Зона:{row[4]} | Сторона:{row[5]}\n"
            await message.answer(text)
        else:
            await message.answer("❌ В БД нет ни одной раскидки!")

@admin_router.message(F.photo)
async def save_photo(message: Message):
    if message.from_user.id not in ADMINS:
        return
    
    caption = message.caption.strip() if message.caption else ""
    
    if caption.startswith("/setresp_"):
        params = caption.replace("/setresp_", "").split("_")
        
        # Проверяем формат: команда_карта_сторона (например /setresp_mirage_t)
        if len(params) < 2:
            await message.answer(
                "❌ Неверный формат команды!\n\n"
                "Используйте:\n"
                "<code>/setresp_мираж_t</code> — респы Т\n"
                "<code>/setresp_мираж_ct</code> — респы СТ\n\n"
                "Доступные карты: mirage, dust2, inferno, nuke, anubis, ancient"
            )
            return
            
        map_name = params[0].lower()
        side = params[1].lower() if len(params) > 1 else None
        
        # Доступные карты
        available_maps = ["mirage", "dust2", "inferno", "nuke", "anubis", "ancient"]
        
        if map_name not in available_maps:
            await message.answer(f"❌ Карта {map_name} не найдена. Доступные: mirage, dust2, inferno, nuke, anubis, ancient")
            return
            
        if side not in ["t", "ct"]:
            await message.answer(
                "❌ Неверная сторона!\n"
                "Используйте <code>_t</code> — для Т (Атака) или <code>_ct</code> — для СТ (Защита)"
            )
            return
        
        file_id = message.photo[-1].file_id
        
        # Сохраняем в БД с уникальным ключом
        db_key = f"{map_name}_resp_{side}"
        await db.save_bot_photo(db_key, file_id)
        
        side_text = "За Т (Атака)" if side == "t" else "За СТ (Защита)"
        await message.answer(f"✅ Фото респов для {map_name.upper()} ({side_text}) сохранено!")
        return
        
    elif caption == "/setmain":
        file_id = message.photo[-1].file_id
        await db.save_bot_photo("main_menu", file_id)
        await message.answer("✅ Фото главного меню сохранено!")
        return
        
    else:
        await message.answer(
            "❌ Для сохранения фото используйте подпись:\n\n"
            "📸 <b>Главное меню:</b>\n"
            "<code>/setmain</code>\n\n"
            "🎯 <b>Респы за Т (Атака):</b>\n"
            "<code>/setresp_mirage_t</code>\n"
            "<code>/setresp_dust2_t</code>\n\n"
            "🎯 <b>Респы за СТ (Защита):</b>\n"
            "<code>/setresp_mirage_ct</code>\n"
            "<code>/setresp_dust2_ct</code>\n\n"
            "Доступные карты: mirage, dust2, inferno, nuke, anubis, ancient"
        )

@admin_router.message(Command("stats"))
async def show_stats(message: Message):
    if message.from_user.id not in ADMINS:
        return
    
    async with aiosqlite.connect(db.DB_PATH) as conn:
        # Всего пользователей
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]
        
        # Новые за сегодня
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(registered_at) = date('now')"
        )
        today_users = (await cursor.fetchone())[0]
        
        # Новые за неделю
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM users WHERE date(registered_at) >= date('now', '-7 days')"
        )
        week_users = (await cursor.fetchone())[0]
        
        # Активные (с доступом)
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM users WHERE access_until IS NOT NULL AND datetime(access_until) > datetime('now')"
        )
        active_users = (await cursor.fetchone())[0]
        
        # Список последних 5 пользователей
        cursor = await conn.execute(
            "SELECT user_id, username, full_name, registered_at FROM users ORDER BY registered_at DESC LIMIT 5"
        )
        last_users = await cursor.fetchall()
        
    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{total_users}</b>\n"
        f"🆕 За сегодня: <b>{today_users}</b>\n"
        f"📅 За неделю: <b>{week_users}</b>\n"
        f"✅ Активных (с доступом): <b>{active_users}</b>\n\n"
        f"📌 <b>Последние 5 пользователей:</b>\n"
    )
    
    for user_id, username, full_name, registered_at in last_users:
        name = full_name or username or str(user_id)
        text += f"• {name} — {registered_at[:16]}\n"
    
    await message.answer(text, parse_mode="HTML")

@admin_router.message(Command("users"))
async def list_users(message: Message):
    if message.from_user.id not in ADMINS:
        return
    
    async with aiosqlite.connect(db.DB_PATH) as conn:
        cursor = await conn.execute(
            "SELECT user_id, username, full_name, registered_at, access_until FROM users ORDER BY registered_at DESC"
        )
        users = await cursor.fetchall()
    
    if not users:
        await message.answer("❌ Пользователей пока нет")
        return
    
    text = "📋 <b>Список пользователей:</b>\n\n"
    for user_id, username, full_name, registered_at, access_until in users:
        name = full_name or username or str(user_id)
        status = "✅ Активен" if access_until and access_until > datetime.now().strftime("%Y-%m-%d %H:%M:%S") else "⏸ Неактивен"
        text += f"• {name} — {registered_at[:16]} — {status}\n"
        
        if len(text) > 3500:  # Telegram лимит
            await message.answer(text, parse_mode="HTML")
            text = ""
    
    if text:
        await message.answer(text, parse_mode="HTML")

@admin_router.message(Command("adddays"))
async def add_days_command(message: Message):
    """Добавить дни пользователю вручную.
    Использование: /adddays USER_ID DAYS
    Пример: /adddays 2129614624 7
    """
    if message.from_user.id not in ADMINS:
        return
    
    parts = message.text.split()
    
    if len(parts) != 3:
        await message.answer(
            "❌ <b>Неверный формат</b>\n\n"
            "Используйте: <code>/adddays USER_ID DAYS</code>\n\n"
            "Пример: <code>/adddays 2129614624 7</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        user_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.answer("❌ USER_ID и DAYS должны быть числами.")
        return
    
    if days <= 0:
        await message.answer("❌ DAYS должно быть больше 0.")
        return
    
    # Проверяем, есть ли пользователь в БД
    user_info = await db.get_user_info(user_id)
    
    if not user_info:
        await message.answer(f"❌ Пользователь <code>{user_id}</code> не найден в БД.", parse_mode="HTML")
        return
    
    # Добавляем дни
    new_until = await db.add_days(user_id, days)
    
    await message.answer(
        f"✅ <b>Готово!</b>\n\n"
        f"👤 Пользователь: <code>{user_id}</code>\n"
        f"📅 Добавлено дней: <b>{days}</b>\n"
        f"🗓️ Новая дата: <b>{new_until.strftime('%d.%m.%Y %H:%M')}</b>",
        parse_mode="HTML"
    )
    
    # Уведомляем пользователя
    try:
        await message.bot.send_message(
            user_id,
            f"<b>Вам добавлено {days} дней доступа!</b>\n\n"
            f"Подписка активна до: <b>{new_until.strftime('%d.%m.%Y %H:%M')}</b>"
        )
    except Exception as e:
        print(f"Не удалось уведомить пользователя {user_id}: {e}")