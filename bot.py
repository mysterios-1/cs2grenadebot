import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InputMediaPhoto, Message, CallbackQuery, FSInputFile
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext

from dotenv import load_dotenv

import aiosqlite

import database
from database import *
from emojis_utils import emoji, E
from emojis_config import CUSTOM_EMOJIS
from keyboards import *
from admin import admin_router, EditThrowState, ADMINS

load_dotenv()

print(f"[DEBUG] DB_PATH = {DB_PATH}")
print(f"[DEBUG] Файл существует: {os.path.exists(DB_PATH)}")

if os.path.exists(DB_PATH):
    print(f"[DEBUG] Размер файла: {os.path.getsize(DB_PATH)} байт")


# ==================== НАСТРОЙКИ ====================
API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables.")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

proxy_url = os.getenv("PROXY_URL", "")
session = AiohttpSession(proxy=proxy_url) if proxy_url else None

bot = Bot(
    token=API_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


# ==================== ГЛАВНОЕ МЕНЮ ====================

async def send_main_menu(message_or_callback, full_name: str = None):
    if isinstance(message_or_callback, CallbackQuery):
        user_id = message_or_callback.from_user.id
        full_name = full_name or message_or_callback.from_user.full_name
        
        # Пытаемся удалить сообщение, но если не получается - просто игнорируем
        try:
            await message_or_callback.message.delete()
        except Exception:
            pass  # Если не удалось удалить - просто продолжаем
        
        msg_func = message_or_callback.message.answer_photo
    else:
        user_id = message_or_callback.from_user.id
        full_name = full_name or message_or_callback.from_user.full_name
        msg_func = message_or_callback.answer_photo
    
    has_access = await check_access(user_id)
    
    bot_icon = emoji("bot_icon")
    check = emoji("check")
    
    subscription_text = await get_subscription_text(user_id)
    date_text = subscription_text
    
    caption = (
        f"{bot_icon} <b>GrenadeCS2</b> на связи, {full_name}\n"
        f"Подписка: <b>{check} {subscription_text}</b>\n\n"
        "Выберите действие:"
    )
    
    photo = await get_bot_photo("main_menu")
    
    await msg_func(
        photo=photo,
        caption=caption,
        reply_markup=get_main_menu(has_access),
        parse_mode="HTML"
    )

@dp.message(Command("id"))
async def get_user_id(message: Message):
    await message.answer(f"Твой ID: <code>{message.from_user.id}</code>", parse_mode="HTML")

# ==================== НАЗАД В ГЛАВНОЕ МЕНЮ ====================

@dp.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    await send_main_menu(callback)
    await callback.answer()


# ==================== КОМАНДА START ====================

@dp.message(Command("start"))
async def start_command(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or "unknown"
    full_name = message.from_user.full_name or "unknown"
    
    referrer_id = None
    if command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args.replace("ref_", ""))
        except ValueError:
            pass
    
    # Передаём bot в add_user для отправки уведомлений
    success, referrer = await add_user(user_id, username, full_name, referrer_id, bot)
    
    # 🎯 Приветствие для нового пользователя (если пришёл по рефке)
    if success and referrer:
        try:
            # Получаем имя реферера
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "SELECT full_name, username FROM users WHERE user_id = ?",
                    (referrer,)
                )
                row = await cursor.fetchone()
                referrer_name = row[0] or row[1] or str(referrer) if row else str(referrer)
            
            await message.answer(
                f"🎉 <b>Добро пожаловать!</b>\n\n"
                f"Вас пригласил пользователь <b>{referrer_name}</b>.\n"
                f"Вы получили <b>7 дней</b> бесплатного доступа! 🎁\n\n"
                f"Используйте кнопки ниже, чтобы начать тренировку гранат."
            )
        except Exception as e:
            print(f"Не удалось отправить приветствие рефералу: {e}")
    
    await send_main_menu(message, full_name)


# ==================== КАРТЫ ====================

@dp.callback_query(F.data == "show_maps")
async def show_maps(callback: CallbackQuery):
    has_access = await check_access(callback.from_user.id)
    if not has_access:
        cross = emoji("cross")
        await callback.message.edit_caption(
            caption=f"{cross} <b>Доступ ограничен!</b>\n\n"
                    "Для просмотра карт необходимо оформить подписку.",
            reply_markup=get_no_access_menu()
        )
        await callback.answer()
        return
    
    map_icon = emoji("map_icon")
    await callback.message.edit_caption(
        caption=f"{map_icon} <b>Выберите карту:</b>\n\n"
                "Доступные карты для тренировки гранат:",
        reply_markup=get_maps_keyboard()
    )
    await callback.answer()


# ==================== ДЕТАЛИ КАРТЫ ====================

@dp.callback_query(F.data.startswith("map_"))
async def show_map_details(callback: CallbackQuery):

    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    map_key = callback.data.replace("map_", "")
    
    map_names = {
    "mirage": "Mirage",
    "dust2": "Dust II",
    "inferno": "Inferno",
    "nuke": "Nuke",
    "anubis": "Anubis",
    "ancient": "Ancient"
    }
    
    map_name = map_names.get(map_key, map_key.capitalize())
    
    text = (
        f"{emoji('geo')} <b>{map_name}</b>\n\n"
        "Выберите тип гранаты:"
    )
    
    main_photo = await get_bot_photo("main_menu")
    
    if main_photo:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=main_photo,
            caption=text,
            reply_markup=get_map_detail_menu(map_key)
        )
    else:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_map_detail_menu(map_key)
        )
    await callback.answer()



# ==================== ГРАНАТЫ ====================

@dp.callback_query(
    F.data.startswith("smoke_")
    | F.data.startswith("flash_")
    | F.data.startswith("he_")
    | F.data.startswith("molotov_")
    | F.data.startswith("insta_")
    | F.data.startswith("oneway_")
)
async def show_grenade_type(callback: CallbackQuery):
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    grenade_type, map_name = callback.data.split("_", 1)

    LIMIT = 5
    CURRENT_PAGE = 1
    DEFAULT_SIDE = "t"
    OFFSET = 0

    if grenade_type in {"insta", "oneway"}:
        kb_zone = "all"
        throws_list = []
        total_count = 0

        for possible_zone in ("a", "b", "mid", "situational"):
            total_count += await get_throws_count(
                map_name,
                grenade_type,
                zone=possible_zone,
                side=DEFAULT_SIDE,
            )

            items = await get_throws(
                map_name,
                grenade_type,
                zone=possible_zone,
                side=DEFAULT_SIDE,
                limit=LIMIT,
                offset=OFFSET,
            )
            throws_list.extend(items)

        throws_list = throws_list[:LIMIT]
    else:
        kb_zone = "a"

        total_count = await get_throws_count(
            map_name,
            grenade_type,
            zone=kb_zone,
            side=DEFAULT_SIDE,
        )

        throws_list = await get_throws(
            map_name,
            grenade_type,
            zone=kb_zone,
            side=DEFAULT_SIDE,
            limit=LIMIT,
            offset=OFFSET,
        )

    grenade_names = {
        "smoke": "Смоки",
        "flash": "Флешки",
        "he": "Хаешки",
        "molotov": "Молики",
        "insta": "Insta Смоки",
        "oneway": "One-Way Смоки",
    }

    grenade_name = grenade_names.get(grenade_type, "Гранаты")
    emoji_name = (
        grenade_type
        if grenade_type in {"smoke", "flash", "he", "molotov"}
        else "smoke"
    )
    grenade_emoji = emoji(emoji_name)

    text = (
        f"{grenade_emoji} <b>{grenade_name}</b> "
        f"на карте {map_name.capitalize()}\n\n"
        "Выбирайте сторону кнопками-вкладками ниже:"
    )

    reply_markup = get_throws_list_menu(
        map_name=map_name,
        grenade_type=grenade_type,
        throws_list=throws_list,
        page=CURRENT_PAGE,
        total_count=total_count,
        current_zone=kb_zone,
        current_side=DEFAULT_SIDE,
        limit=LIMIT,
    )

    # Для Mirage Insta показываем фото респа Т
    if map_name.lower() == "mirage" and grenade_type == "insta":
        resp_photo = await get_bot_photo("mirage_resp_t")

        if resp_photo:
            try:
                await callback.message.delete()
            except Exception:
                pass

            await callback.message.answer_photo(
                photo=resp_photo,
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
            await callback.answer()
            return

    # Для остальных случаев удаляем старое сообщение
    # и отправляем главное фото заново
    main_photo = await get_bot_photo("main_menu")

    try:
        await callback.message.delete()
    except Exception:
        pass

    if main_photo:
        await callback.message.answer_photo(
            photo=main_photo,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    await callback.answer()

# ==================== ФИЛЬТР ПО ЗОНАМ ====================

@dp.callback_query(F.data.startswith("filter_"))
async def filter_by_zone(callback: CallbackQuery):
    """Обработчик нажатия на кнопки зон (Плент А, Плент Б, Мид, Ситуация)"""
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    try:
        _, map_name, grenade_type, zone, side = callback.data.split("_")
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    LIMIT = 5
    CURRENT_PAGE = 1
    OFFSET = (CURRENT_PAGE - 1) * LIMIT

    total_count = await get_throws_count(map_name, grenade_type, zone=zone, side=side)
    throws_list = await get_throws(map_name, grenade_type, zone=zone, side=side, limit=LIMIT, offset=OFFSET)

    grenade_names = {
        "smoke": "Смоки", "flash": "Флешки", "he": "Хаешки", "molotov": "Молики",
        "insta": "Insta Смоки", "oneway": "One-Way Смоки"
    }
    grenade_name = grenade_names.get(grenade_type, "Гранаты")
    grenade_emoji = emoji(grenade_type if grenade_type in ["smoke", "flash", "he", "molotov"] else "smoke")

    text = (
        f"{grenade_emoji} <b>{grenade_name}</b> "
        f"на карте {map_name.capitalize()}\n\n"
        "Выбирайте сторону кнопками-вкладками ниже:"
    )

    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_throws_list_menu(
            map_name=map_name,
            grenade_type=grenade_type,
            throws_list=throws_list,
            page=CURRENT_PAGE,
            total_count=total_count,
            current_zone=zone,
            current_side=side,
            limit=LIMIT
        )
    )
    await callback.answer()

# ==================== ПЕРЕКЛЮЧЕНИЕ СТОРОНЫ (Т/СТ) ====================

@dp.callback_query(F.data.startswith("side_"))
async def switch_side(callback: CallbackQuery):
    """Обработчик переключения между Т и СТ"""
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    try:
        _, map_name, grenade_type, zone, new_side = callback.data.split("_")
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    LIMIT = 5
    CURRENT_PAGE = 1
    OFFSET = 0

    if zone == "all":
        throws_list = []
        total_count = 0
        for possible_zone in ["a", "b", "mid", "situational"]:
            count = await get_throws_count(map_name, grenade_type, zone=possible_zone, side=new_side)
            total_count += count
            items = await get_throws(map_name, grenade_type, zone=possible_zone, side=new_side, limit=LIMIT, offset=OFFSET)
            if items:
                throws_list.extend(items)
        throws_list = throws_list[:LIMIT]
        zone_for_kb = "all"
    else:
        total_count = await get_throws_count(map_name, grenade_type, zone=zone, side=new_side)
        throws_list = await get_throws(map_name, grenade_type, zone=zone, side=new_side, limit=LIMIT, offset=OFFSET)
        zone_for_kb = zone

    grenade_names = {
        "smoke": "Смоки", "flash": "Флешки", "he": "Хаешки", "molotov": "Молики",
        "insta": "Insta Смоки", "oneway": "One-Way Смоки"
    }
    grenade_name = grenade_names.get(grenade_type, "Гранаты")
    grenade_emoji = emoji(grenade_type if grenade_type in ["smoke", "flash", "he", "molotov"] else "smoke")

    text = (
        f"{grenade_emoji} <b>{grenade_name}</b> на карте {map_name.capitalize()}\n\n"
        "Выбирайте сторону кнопками-вкладками ниже:"
    )

    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_throws_list_menu(
            map_name=map_name,
            grenade_type=grenade_type,
            throws_list=throws_list,
            page=CURRENT_PAGE,
            total_count=total_count,
            current_zone=zone_for_kb,
            current_side=new_side,
            limit=LIMIT
        )
    )
    await callback.answer()


# ==================== ПАГИНАЦИЯ СПИСКА РАСКИДОК ====================

@dp.callback_query(F.data.startswith("listpage_"))
async def list_pagination(callback: CallbackQuery):
    """Обработчик переключения страниц в списке раскидок"""
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    try:
        _, map_name, grenade_type, zone, side, page = callback.data.split("_")
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    LIMIT = 5
    OFFSET = (page - 1) * LIMIT

    if grenade_type in ["insta", "oneway"]:
        throws_list = []
        total_count = 0
        for possible_zone in ["a", "b", "mid", "situational"]:
            count = await get_throws_count(map_name, grenade_type, zone=possible_zone, side=side)
            total_count += count
            items = await get_throws(map_name, grenade_type, zone=possible_zone, side=side, limit=LIMIT, offset=OFFSET)
            if items:
                throws_list.extend(items)
        throws_list = throws_list[:LIMIT]
        zone_for_kb = "all"
    else:
        total_count = await get_throws_count(map_name, grenade_type, zone=zone, side=side)
        throws_list = await get_throws(map_name, grenade_type, zone=zone, side=side, limit=LIMIT, offset=OFFSET)
        zone_for_kb = zone

    grenade_names = {
        "smoke": "Смоки", "flash": "Флешки", "he": "Хаешки", "molotov": "Молики",
        "insta": "Insta Смоки", "oneway": "One-Way Смоки"
    }
    grenade_name = grenade_names.get(grenade_type, "Гранаты")
    grenade_emoji = emoji(grenade_type if grenade_type in ["smoke", "flash", "he", "molotov"] else "smoke")

    text = (
        f"{grenade_emoji} <b>{grenade_name}</b> на карте {map_name.capitalize()}\n\n"
        "Выбирайте сторону кнопками-вкладками ниже:"
    )

    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_throws_list_menu(
            map_name=map_name,
            grenade_type=grenade_type,
            throws_list=throws_list,
            page=page,
            total_count=total_count,
            current_zone=zone_for_kb,
            current_side=side,
            limit=LIMIT
        )
    )
    await callback.answer()

# ==================== ПРОСМОТР РАСКИДКИ ====================

YOUR_ADMIN_ID = 2129614624

@dp.callback_query(F.data.startswith("view_"))
async def view_throw_page_one(callback: CallbackQuery):
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return


    throw_id = int(callback.data.split("_")[-1])
    throw = await get_throw_detail(throw_id)
    
    if not throw:
        await callback.answer(f"{emoji('cross')} Раскидка не найдена.", show_alert=True)
        return
        
    if len(throw) < 12:
        await callback.answer(f"{emoji('cross')} Ошибка данных раскидки.", show_alert=True)
        return
        
    _, map_name, g_type, title, photo_pos, photo_aim, photo_result, desc, throw_type, zone, side, combo_id = throw[:12]
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    caption = (
        f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
        f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n\n"
        f"{emoji('grenade_jumptype')} <b>Тип броска:</b> <code>{throw_type}</code>"
    )
    
    markup = get_combo_page_kb(throw_id, "pos", combo_list, user_id=callback.from_user.id, admin_id=YOUR_ADMIN_ID)
    
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == "back_to_list_placeholder":
                btn.callback_data = f"{g_type}_{map_name}"

    try:
        await callback.message.delete()
        await callback.message.answer_photo(photo=photo_pos, caption=caption, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        media = InputMediaPhoto(media=photo_pos, caption=caption, parse_mode="HTML")
        await callback.message.edit_media(media=media, reply_markup=markup)
        
    await callback.answer()


@dp.callback_query(F.data.startswith("page_"))
async def switch_pages(callback: CallbackQuery):
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    parts = callback.data.split("_")

    if len(parts) != 3:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    throw_id = int(parts[1])
    page = int(parts[2])

    throw = await get_throw_detail(throw_id)
    if not throw or len(throw) < 12:
        await callback.answer("Раскидка не найдена.", show_alert=True)
        return

    (
        id_,
        map_name,
        g_type,
        title,
        photo_pos,
        photo_aim,
        photo_result,
        desc,
        throw_type,
        zone,
        side,
        combo_id,
    ) = throw[:12]

    combo_list = await get_combo_throws(combo_id) if combo_id else []

    if page == 1:
        photo = photo_pos
        view_type = "pos"
        caption = (
            f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
            f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n"
            f"{emoji('grenade_jumptype')} <b>Тип броска:</b> "
            f"<code>{throw_type}</code>"
        )
    elif page == 2:
        photo = photo_aim
        view_type = "aim"
        caption = (
            f"{emoji('target')} <b>{title}</b> (ПРИЦЕЛ)\n\n"
            "Повторите наводку прицела по изображению.\n"
            f"{emoji('grenade_jumptype')} <b>Бросок:</b> "
            f"<code>{throw_type}</code>"
        )
    elif page == 3:
        photo = photo_result or photo_aim
        view_type = "result"
        caption = (
            f"{emoji('where_it_explodes')} <b>{title}</b> (РЕЗУЛЬТАТ)\n\n"
            "Граната успешно раскрывается и закрывает обзор противнику."
        )
    else:
        await callback.answer("Такой страницы нет.", show_alert=True)
        return

    markup = get_combo_page_kb(
        throw_id,
        view_type,
        combo_list,
        user_id=callback.from_user.id,
        admin_id=YOUR_ADMIN_ID,
    )

    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data == "back_to_list_placeholder":
                button.callback_data = f"{g_type}_{map_name}"

    media = InputMediaPhoto(
        media=photo,
        caption=caption,
        parse_mode="HTML",
    )

    await callback.message.edit_media(media=media, reply_markup=markup)
    await callback.answer()


# ==================== РЕДАКТИРОВАНИЕ РАСКИДКИ ====================

@dp.callback_query(F.data.startswith("edit_"))
async def edit_throw_start(callback: CallbackQuery, state: FSMContext):
    """Начало редактирования раскидки (только для админа)"""
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    throw_id = int(callback.data.split("_")[-1])
    throw = await get_throw_detail(throw_id)

    if not throw:
        await callback.answer("❌ Раскидка не найдена", show_alert=True)
        return

    await state.update_data(throw_id=throw_id)
    await state.set_state(EditThrowState.title)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="adm_cancel")
    )

    await callback.message.edit_caption(
        caption=f"✏️ <b>Редактирование раскидки #{throw_id}</b>\n\n"
                f"Текущее название: <i>{throw[3]}</i>\n\n"
                "Введите <b>НОВОЕ НАЗВАНИЕ</b> или отправьте /skip, чтобы пропустить:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# ==================== УДАЛЕНИЕ РАСКИДКИ ====================

@dp.callback_query(F.data.startswith("del_"))
async def delete_throw(callback: CallbackQuery):
    """Удаление раскидки (только для админа)"""
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    throw_id = int(callback.data.split("_")[-1])

    # Подтверждение удаления
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del_{throw_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_list_placeholder")
    )

    throw = await get_throw_detail(throw_id)
    if not throw:
        await callback.answer("❌ Раскидка не найдена", show_alert=True)
        return

    title = throw[3] if len(throw) > 3 else f"#{throw_id}"

    await callback.message.edit_caption(
        caption=f"⚠️ <b>Вы уверены, что хотите удалить раскидку?</b>\n\n"
                f"📌 Название: <i>{title}</i>\n"
                f"🆔 ID: <code>{throw_id}</code>\n\n"
                f"<b>Это действие НЕОБРАТИМО!</b>",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

# ============================ Потверждение ==============================

@dp.callback_query(F.data.startswith("confirm_del_"))
async def confirm_delete_throw(callback: CallbackQuery):
    """Подтверждение удаления раскидки"""
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет прав", show_alert=True)
        return

    throw_id = int(callback.data.split("_")[-1])

    async with aiosqlite.connect(DB_PATH) as conn:
        # Получаем информацию для отображения
        cursor = await conn.execute("SELECT title FROM throws WHERE id = ?", (throw_id,))
        row = await cursor.fetchone()
        title = row[0] if row else f"#{throw_id}"

        # Удаляем
        await conn.execute("DELETE FROM throws WHERE id = ?", (throw_id,))
        await conn.commit()

    await callback.message.edit_caption(
        caption=f"✅ <b>Раскидка '{title}' успешно удалена!</b>",
        reply_markup=get_back_button()
    )
    await callback.answer("🗑️ Раскидка удалена", show_alert=True)


# ==================== ПРОФИЛЬ ====================

@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):

    user_info = await get_user_info(callback.from_user.id)
    if not user_info:
        await callback.message.edit_caption(
            caption=f"{emoji('cross')} <b>Профиль не найден</b>",
            reply_markup=get_back_button()
        )
        await callback.answer()
        return
    
    access_until, balance_days, referrer_id = user_info
    has_access = await check_access(callback.from_user.id)
    ref_count = await get_referral_count(callback.from_user.id)
    
    profile_icon = emoji("profile")
    check = emoji("check")
    cross = emoji("cross")
    account_icon = emoji("account_icon")
    calendar = emoji("calendar")
    key = emoji("key")
    status = check if has_access else cross
    status_text = "Активен" if has_access else "Неактивен"
    date_text = await get_subscription_text(callback.from_user.id)
    
    text = (
        f"{profile_icon} <b>Личный кабинет</b>\n\n"
        f"{account_icon} Имя: {callback.from_user.full_name}\n"
        f"{calendar} Доступ: {date_text}\n"
        f"{key} Статус: {status} {status_text}\n"
    )
    
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_profile_menu()
    )
    await callback.answer()


# ==================== РЕФЕРАЛКА ====================

@dp.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):

    bot_info = await bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{callback.from_user.id}"
    ref_count = await get_referral_count(callback.from_user.id)
    
    referral_icon = emoji("referral")
    check = emoji("check")
    
    text = (
        f"{check} <b>Бонусы:</b>\n"
        "• Новый пользователь получает 7 дней доступа\n"
        "• Ты получаешь +7 дней за каждого друга\n\n"
        "Делись ссылкой и получай бесплатный доступ!"
    )
    
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_referral_menu(ref_link, ref_count)
    )
    await callback.answer()

@dp.callback_query(F.data == "copy_referral")
async def copy_referral(callback: CallbackQuery):
    await callback.answer(
        "Скопируйте ссылку из сообщения выше.",
        show_alert=True
    )


# ==================== ПОДДЕРЖКА ====================

@dp.callback_query(F.data == "support")
async def show_support(callback: CallbackQuery):
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    support_icon = emoji("support")
    phone = emoji('phone')
    time = emoji('time')
    
    text = (
        f"{support_icon} <b>Поддержка</b>\n\n"
        "По всем вопросам обращайтесь:\n"
        f"{phone} Telegram: @syntax322\n\n"
        f"{time} Время ответа: до 24 часов"
    )
    
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_back_button()
    )
    await callback.answer()
# ===================== ПЛАТЕЖКА =====================

@dp.callback_query(F.data == "renew")
async def show_packages(callback: CallbackQuery):
    text = (
        "💳 <b>Продление доступа</b>\n\n"
        "Выберите подходящий пакет:"
    )

    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_subscription_packages_menu()
    )
    await callback.answer()


@dp.callback_query(F.data.in_({"buy_week", "buy_month", "buy_year"}))
async def select_package(callback: CallbackQuery):
    packages = {
        "buy_week": ("Неделя", 99, 7),
        "buy_month": ("Месяц", 299, 30),
        "buy_year": ("Год", 999, 365),
    }

    package_name, price, days = packages[callback.data]

    await callback.answer(
        f"Вы выбрали: {package_name} — {price} ₽",
        show_alert=True
    )

# ==================== ИНФО ====================

@dp.callback_query(F.data == "info")
async def show_info(callback: CallbackQuery):
    info_icon = emoji("info")
    bot_icon = emoji("bot_icon")
    pushpin = emoji("pushpin")
     
    text = (
        f"{info_icon} <b>Информация о боте</b>\n\n"
        f"{bot_icon} <b>GrenadeCS2</b> — бот для тренировки гранат в CS2.\n\n"
        f"{pushpin} <b>Доступные карты:</b>\n"
        f"{emoji('mirage')} Mirage\n"
        f"{emoji('dust2')} Dust II\n"
        f"{emoji('inferno')} Inferno\n"
        f"{emoji('nuke')} Nuke\n\n"
        "💡 <b>Возможности:</b>\n"
        f"{emoji('smoke')} Изучение смоков\n"
        f"{emoji('flash')} Тренировка флешек\n"
        f"{emoji('he')} Практика хаешек\n"
        f"{emoji('molotov')} Обучение моликам\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Документы</b>\n"
        "📄 <a href='https://telegra.ph/Polzovatelskoe-soglashenie-GrenadeCS2-08-27'>Пользовательское соглашение</a>\n"
        "🔒 <a href='https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-08-27-80'>Политика конфиденциальности</a>"
    )
    
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_back_button(),
        parse_mode="HTML",
        disable_web_page_preview=False
    )
    await callback.answer()
# ==================== Уведомления ======================

async def expiry_notifications_worker():
    while True:
        try:
            users = await get_expiring_users()

            for user_id, access_until in users:
                try:
                    until = datetime.strptime(
                        access_until,
                        "%Y-%m-%d %H:%M:%S"
                    )

                    await bot.send_message(
                        user_id,
                        f"<b>Доступ заканчивается завтра</b>\n\n"
                        f"Ваша подписка действует до "
                        f"<b>{until.strftime('%d.%m.%Y %H:%M')}</b>.\n\n"
                        "Продлите доступ, чтобы продолжить пользоваться раскидками."
                    )

                    await mark_expiry_notice_sent(user_id)

                except Exception as error:
                    logging.warning(
                        f"Не удалось отправить уведомление {user_id}: {error}"
                    )

        except Exception:
            logging.exception("Ошибка проверки окончаний подписок")

        await asyncio.sleep(3600)


# ==================== ВОЗВРАТ К СПИСКУ РАСКИДОК ====================

@dp.callback_query(F.data == "back_to_list_placeholder")
async def back_to_list(callback: CallbackQuery):
    """Возврат к списку раскидок"""
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Пытаемся получить текущее сообщение и вернуться в меню карт
    # Просто отправляем пользователя в главное меню карт
    map_icon = emoji("map_icon")
    await callback.message.edit_caption(
        caption=f"{map_icon} <b>Выберите карту:</b>\n\n"
                "Доступные карты для тренировки гранат:",
        reply_markup=get_maps_keyboard()
    )
    await callback.answer()


# ==================== ЗАПУСК БОТА ====================

async def main():
    await init_db()

    dp.include_router(admin_router) 
    asyncio.create_task(expiry_notifications_worker())

    try:
        logging.info("🚀 Бот GrenadeCS2 запущен!")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())