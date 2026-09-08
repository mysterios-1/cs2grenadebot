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

from aiogram_sentinel import Sentinel, SentinelConfig
from dotenv import load_dotenv

import aiosqlite

import database
from database import *
from emojis_utils import emoji, E
from emojis_config import CUSTOM_EMOJIS
from keyboards import *

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from admin_handlers import admin_router, EditThrowState, ADMINS

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
    # Более надежное извлечение ID реферера без лишних строковых операций
    if command.args and command.args.startswith("ref_"):
        try:
            referrer_id = int(command.args[4:])
        except ValueError:
            pass
    
    # Ожидаем, что add_user теперь возвращает:
    # success (bool), referrer_id (int или None), referrer_name (str или None)
    # Передаём bot в add_user для отправки уведомлений
    success, referrer, referrer_name = await add_user(user_id, username, full_name, referrer_id, bot)
    
    # 🎯 Приветствие для нового пользователя (если пришёл по рефке и успешно зарегистрирован)
    if success and referrer:
        try:
            # Если имя реферера не пришло из функции add_user, ставим ID как заглушку
            ref_display_name = referrer_name or str(referrer)
            
            await message.answer(
                f"🎉 <b>Добро пожаловать!</b>\n\n"
                f"Вас пригласил пользователь <b>{ref_display_name}</b>.\n"
                f"Вы получили <b>7 дней</b> бесплатного доступа! 🎁\n\n"
                f"Используйте кнопки ниже, чтобы начать тренировку гранат."
            )
        except Exception as e:
            print(f"Не удалось отправить приветствие рефералу: {e}")
    
    # Отправляем главное меню пользователю
    await send_main_menu(message, full_name)


# ==================== КАРТЫ ====================

@dp.callback_query(F.data == "show_maps")
async def show_maps(callback: CallbackQuery):
    # 1. Сразу гасим анимацию загрузки на кнопке (избавляемся от ошибки таймаута)
    await callback.answer()
    
    # 2. Быстро проверяем доступ в БД (используется наша ускоренная функция)
    has_access = await check_access(callback.from_user.id)
    
    # 3. Если доступа нет, выводим соответствующее меню
    if not has_access:
        cross = emoji("cross")
        await callback.message.edit_caption(
            caption=f"{cross} <b>Доступ ограничен!</b>\n\n"
                    "Для просмотра карт необходимо оформить подписку.",
            reply_markup=get_no_access_menu()
        )
        return
    
    # 4. Если доступ есть, показываем клавиатуру с картами
    map_icon = emoji("map_icon")
    await callback.message.edit_caption(
        caption=f"{map_icon} <b>Выберите карту:</b>\n\n"
                "Доступные карты для тренировки гранат:",
        reply_markup=get_maps_keyboard()
    )


# ==================== ДЕТАЛИ КАРТЫ ====================

@dp.callback_query(F.data.startswith("map_"))
async def show_map_details(callback: CallbackQuery):
    # 1. Запускаем проверку доступа и получение фото параллельно
    has_access, main_photo = await asyncio.gather(
        check_access(callback.from_user.id),
        get_bot_photo("main_menu")
    )

    # 2. Если доступа нет, сразу выводим уведомление-алерт и завершаем функцию
    if not has_access:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # 3. Гасим часики анимации загрузки, так как доступ есть и мы готовы перерисовать меню
    await callback.answer()

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
    
    # 4. Обновляем интерфейс
    if main_photo:
        # Сначала отправляем новое фото, чтобы интерфейс не «прыгал»
        await callback.message.answer_photo(
            photo=main_photo,
            caption=text,
            reply_markup=get_map_detail_menu(map_key)
        )
        # И только потом удаляем старое сообщение
        try:
            await callback.message.delete()
        except Exception:
            pass
    else:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_map_detail_menu(map_key)
        )



# ==================== ГРАНАТЫ ====================

import asyncio
from aiogram import F
from aiogram.types import CallbackQuery

# ==================== ГРАНАТЫ ====================

@dp.callback_query(
    F.data.startswith("smoke_") | F.data.startswith("flash_") |
    F.data.startswith("he_") | F.data.startswith("molotov_") |
    F.data.startswith("insta_") | F.data.startswith("oneway_") |
    F.data.startswith("side_") | F.data.startswith("filter_") |
    F.data.startswith("listpage_")
)
async def show_grenade_type(callback: CallbackQuery):
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    await callback.answer()
    
    raw_data = callback.data
    
    # 1. Парсим callback_data
    if raw_data.startswith("side_"):
        # side_map_grenade_zone_side
        _, map_name, grenade_type, current_zone, current_side = raw_data.split("_")
        current_page = 1
    elif raw_data.startswith("filter_"):
        # filter_map_grenade_zone_side
        _, map_name, grenade_type, current_zone, current_side = raw_data.split("_")
        current_page = 1
    elif raw_data.startswith("listpage_"):
        # listpage_map_grenade_zone_side_page
        _, map_name, grenade_type, current_zone, current_side, page_str = raw_data.split("_")
        current_page = int(page_str)
    else:
        # Первичный клик по категории (например, insta_mirage)
        grenade_type, map_name = raw_data.split("_", 1)
        current_side = "t"
        # Для инста/уанвей изначально ставим "all", чтобы запросить все зоны
        current_zone = "all" if grenade_type in {"insta", "oneway"} else "a"
        current_page = 1

    LIMIT = 7
    OFFSET = (current_page - 1) * LIMIT

    # 2. Получаем данные из БД с объединением зон для insta и oneway
    if grenade_type in {"insta", "oneway"} and current_zone == "all":
        # Сканируем эти зоны в БД, так как вы сохраняете инста-смоки в конкретные зоны (например, mid)
        zones_to_check = ("a", "b", "mid", "situational")
        
        # Получаем общее количество во всех зонах для пагинации
        count_tasks = [
            get_throws_count(map_name, grenade_type, zone=z, side=current_side)
            for z in zones_to_check
        ]
        counts = await asyncio.gather(*count_tasks)
        total_count = sum(counts)

        # Достаем раскидки из всех зон
        throws_tasks = [
            get_throws(map_name, grenade_type, zone=z, side=current_side, limit=LIMIT + OFFSET, offset=0)
            for z in zones_to_check
        ]
        throws_results = await asyncio.gather(*throws_tasks)
        
        # Объединяем результаты в один плоский список
        all_throws = []
        for items in throws_results:
            all_throws.extend(items)
            
        # Применяем пагинацию (OFFSET и LIMIT) уже на объединенном списке
        throws_list = all_throws[OFFSET : OFFSET + LIMIT]
    else:
        # Обычные гранаты или конкретно выбранная зона
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone=current_zone, side=current_side),
            get_throws(map_name, grenade_type, zone=current_zone, side=current_side, limit=LIMIT, offset=OFFSET)
        )

    # 3. Формируем текст интерфейса
    grenade_names = {
        "smoke": "Смоки", "flash": "Флешки", "he": "Хаешки",
        "molotov": "Молики", "insta": "Insta Смоки", "oneway": "One-Way Смоки",
    }
    grenade_name = grenade_names.get(grenade_type, "Гранаты")
    emoji_name = grenade_type if grenade_type in {"smoke", "flash", "he", "molotov"} else "smoke"
    grenade_emoji = emoji(emoji_name)

    if current_zone == "situational":
        side_text = "<b>Ситуационные (Для обеих сторон)</b>"
    else:
        side_text = f"Сторона: <b>{'Атака (Т)' if current_side == 't' else 'Защита (СТ)'}</b>"

    text = (
        f"{grenade_emoji} <b>{grenade_name}</b> на карте {map_name.capitalize()}\n\n"
        f"Выбран раздел: {side_text}\n"
        "Выбирайте нужные фильтры кнопками ниже:"
    )

    reply_markup = get_throws_list_menu(
        map_name=map_name,
        grenade_type=grenade_type,
        throws_list=throws_list,
        page=current_page,
        total_count=total_count,
        current_zone=current_zone,
        current_side=current_side,
        limit=LIMIT,
    )

    # 4. Логика подбора фото
    insta_maps = ["mirage", "dust2", "inferno", "nuke", "anubis", "ancient"]
    
    if current_zone == "situational":
        bot_photo = await get_bot_photo(f"{map_name.lower()}_situational") or await get_bot_photo("main_menu")
    elif grenade_type == "insta" and map_name.lower() in insta_maps:
        # Теперь CURRENT_SIDE динамическая и фото СТ-респа на Мираже будет отображаться корректно!
        photo_key = f"{map_name.lower()}_resp_{current_side.lower()}"
        bot_photo = await get_bot_photo(photo_key) or await get_bot_photo("main_menu")
    else:
        bot_photo = await get_bot_photo("main_menu")

    # Отправка сообщения
    if bot_photo:
        await callback.message.answer_photo(
            photo=bot_photo, caption=text, reply_markup=reply_markup, parse_mode="HTML"
        )
    else:
        await callback.message.answer(
            text=text, reply_markup=reply_markup, parse_mode="HTML"
        )

    try:
        await callback.message.delete()
    except Exception:
        pass


# ==================== ФИЛЬТР ПО ЗОНАМ ====================

@dp.callback_query(F.data.startswith("filter_"))
async def filter_by_zone(callback: CallbackQuery):
    # 1. Быстро проверяем доступ, чтобы сразу отсечь неавторизованных
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Разбираем callback_data
    try:
        parts = callback.data.split("_")
        # filter_mirage_smoke_a_t (5 частей)
        # filter_mirage_smoke_situational (4 части)
        if len(parts) == 5:
            _, map_name, grenade_type, zone, side = parts
        elif len(parts) == 4:
            _, map_name, grenade_type, zone = parts
            side = "t"  # Значение по умолчанию
        else:
            await callback.answer("Ошибка данных.", show_alert=True)
            return
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # 2. Данные валидны, доступ есть — СРАЗУ гасим часики загрузки в Telegram
    await callback.answer()

    LIMIT = 7
    CURRENT_PAGE = 1
    OFFSET = (CURRENT_PAGE - 1) * LIMIT

    # 3. Запускаем оба запроса к базе данных параллельно
    total_count, throws_list = await asyncio.gather(
        get_throws_count(map_name, grenade_type, zone=zone, side=side),
        get_throws(map_name, grenade_type, zone=zone, side=side, limit=LIMIT, offset=OFFSET)
    )

    # Словари и генерация текста
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

    # 4. Обновляем меню для пользователя
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

# ==================== ПЕРЕКЛЮЧЕНИЕ СТОРОНЫ (Т/СТ) ====================

@dp.callback_query(F.data.startswith("side_"))
async def switch_side(callback: CallbackQuery):
    """Обработчик переключения между Т и СТ"""
    # 1. Быстро проверяем доступ, чтобы отсечь неавторизованных
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Разбираем callback_data
    try:
        _, map_name, grenade_type, zone, new_side = callback.data.split("_")
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # 2. Данные валидны, доступ есть — СРАЗУ гасим часики загрузки в Telegram
    await callback.answer()

    LIMIT = 7
    CURRENT_PAGE = 1
    OFFSET = 0
    
    possible_zones = ["a", "b", "mid", "situational"]

    if zone == "all":
        zone_for_kb = "all"
        
        # Запускаем ВСЕ запросы количества для всех зон одновременно
        count_tasks = [
            get_throws_count(map_name, grenade_type, zone=z, side=new_side)
            for z in possible_zones
        ]
        counts = await asyncio.gather(*count_tasks)
        total_count = sum(counts)

        # Запускаем ВСЕ запросы раскидок для всех зон одновременно
        throws_tasks = [
            get_throws(map_name, grenade_type, zone=z, side=new_side, limit=LIMIT, offset=OFFSET)
            for z in possible_zones
        ]
        throws_results = await asyncio.gather(*throws_tasks)
        
        # Собираем элементы в один список и обрезаем по лимиту
        throws_list = []
        for items in throws_results:
            if items:
                throws_list.extend(items)
        throws_list = throws_list[:LIMIT]
        
    else:
        zone_for_kb = zone
        # Для конкретной зоны запускаем оба запроса параллельно
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone=zone, side=new_side),
            get_throws(map_name, grenade_type, zone=zone, side=new_side, limit=LIMIT, offset=OFFSET)
        )

    # Словари и подготовка интерфейса
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

    # 3. Обновляем вкладку интерфейса
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


# ==================== ПАГИНАЦИЯ СПИСКА РАСКИДОК ====================

@dp.callback_query(F.data.startswith("listpage_"))
async def list_pagination(callback: CallbackQuery):
    """Обработчик переключения страниц в списке раскидок"""
    # 1. Быстро проверяем доступ, чтобы отсечь неавторизованных пользователей
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Разбираем callback_data
    try:
        _, map_name, grenade_type, zone, side, page = callback.data.split("_")
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # 2. Данные валидны, доступ подтвержден — СРАЗУ убираем анимацию загрузки кнопки в Telegram
    await callback.answer()

    LIMIT = 7
    OFFSET = (page - 1) * LIMIT
    
    possible_zones = ["a", "b", "mid", "situational"]

    if grenade_type in ["insta", "oneway"]:
        zone_for_kb = "all"
        
        # Запускаем параллельный сбор количества раскидок по всем зонам
        count_tasks = [
            get_throws_count(map_name, grenade_type, zone=z, side=side)
            for z in possible_zones
        ]
        counts = await asyncio.gather(*count_tasks)
        total_count = sum(counts)

        # Запускаем параллельный сбор самих раскидок по всем зонам с учетом OFFSET
        throws_tasks = [
            get_throws(map_name, grenade_type, zone=z, side=side, limit=LIMIT, offset=OFFSET)
            for z in possible_zones
        ]
        throws_results = await asyncio.gather(*throws_tasks)
        
        # Объединяем списки и берем только нужный лимит страниц
        throws_list = []
        for items in throws_results:
            if items:
                throws_list.extend(items)
        throws_list = throws_list[:LIMIT]
        
    else:
        zone_for_kb = zone
        # Для стандартных одиночных зон выполняем оба запроса к БД параллельно
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone=zone, side=side),
            get_throws(map_name, grenade_type, zone=zone, side=side, limit=LIMIT, offset=OFFSET)
        )

    # Словари наименований гранат
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

    # 3. Обновляем интерфейс меню (перелистываем страницу)
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

# ==================== ПРОСМОТР РАСКИДКИ ====================

YOUR_ADMIN_ID = 2129614624

@dp.callback_query(F.data.startswith("view_"))
async def view_throw_page_one(callback: CallbackQuery):
    throw_id = int(callback.data.split("_")[-1])

    # 1. Запускаем проверку доступа и получение деталей раскидки параллельно
    has_access, throw = await asyncio.gather(
        check_access(callback.from_user.id),
        get_throw_detail(throw_id)
    )

    if not has_access:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    if not throw:
        await callback.answer(f"{emoji('cross')} Раскидка не найдена.", show_alert=True)
        return
        
    if len(throw) < 12:
        await callback.answer(f"{emoji('cross')} Ошибка данных раскидки.", show_alert=True)
        return

    # 2. Данные на месте — моментально гасим анимацию загрузки кнопки в Telegram
    await callback.answer()
        
    _, map_name, g_type, title, photo_pos, photo_aim, photo_result, desc, throw_type, zone, side, combo_id = throw[:12]
    
    # 3. Быстро запрашиваем комбо-раскидки, если они привязаны
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

    # 4. Обновляем интерфейс
    try:
        # Пытаемся отправить как новое фото
        await callback.message.answer_photo(photo=photo_pos, caption=caption, parse_mode="HTML", reply_markup=markup)
        try:
            await callback.message.delete()
        except Exception:
            pass
    except Exception:
        # Если отправка фото не удалась, редактируем текущее медиа
        media = InputMediaPhoto(media=photo_pos, caption=caption, parse_mode="HTML")
        await callback.message.edit_media(media=media, reply_markup=markup)

@dp.callback_query(F.data.startswith("page_"))
async def switch_pages(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    throw_id = int(parts[1])
    page = int(parts[2])

    # 1. Запускаем параллельно проверку прав и извлечение информации по раскидке
    has_access, throw = await asyncio.gather(
        check_access(callback.from_user.id),
        get_throw_detail(throw_id)
    )

    if not has_access:
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    if not throw or len(throw) < 12:
        await callback.answer("Раскидка не найдена.", show_alert=True)
        return

    # 2. Доступ подтвержден, раскидка найдена — СРАЗУ гасим часики загрузки
    await callback.answer()

    (
        id_, map_name, g_type, title, photo_pos, photo_aim, photo_result,
        desc, throw_type, zone, side, combo_id
    ) = throw[:12]

    # 3. Быстро запрашиваем список комбинаций
    combo_list = await get_combo_throws(combo_id) if combo_id else []

    # Определяем медиафайл и текст в зависимости от выбранной вкладки (страницы)
    if page == 1:
        photo = photo_pos
        view_type = "pos"
        caption = (
            f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
            f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n"
            f"{emoji('grenade_jumptype')} <b>Тип броска:</b> <code>{throw_type}</code>"
        )
    elif page == 2:
        photo = photo_aim
        view_type = "aim"
        caption = (
            f"{emoji('target')} <b>{title}</b> (ПРИЦЕЛ)\n\n"
            "Повторите наводку прицела по изображению.\n"
            f"{emoji('grenade_jumptype')} <b>Бросок:</b> <code>{throw_type}</code>"
        )
    elif page == 3:
        photo = photo_result or photo_aim
        view_type = "result"
        caption = (
            f"{emoji('where_it_explodes')} <b>{title}</b> (РЕЗУЛЬТАТ)\n\n"
            "Граната успешно раскрывается и закрывает обзор противнику."
        )
    else:
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

    # 4. Перерисовываем медиавкладку
    await callback.message.edit_media(media=media, reply_markup=markup)


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
    # 1. Отвечаем Telegram СРАЗУ, чтобы избежать таймаута (ошибки query is too old)
    await callback.answer()

    # 2. Сначала получаем базовую информацию о пользователе
    user_info = await get_user_info(callback.from_user.id)
    if not user_info:
        await callback.message.edit_caption(
            caption=f"{emoji('cross')} <b>Профиль не найден</b>",
            reply_markup=get_back_button()
        )
        return
    
    # Распаковываем базовую информацию (если referrer_id или balance_days понадобятся дальше)
    access_until, balance_days, referrer_id = user_info
    
    # 3. 🔥 ОПТИМИЗАЦИЯ: Запускаем оставшиеся три запроса к БД ПАРАЛЛЕЛЬНО
    has_access, ref_count, date_text = await asyncio.gather(
        check_access(callback.from_user.id),
        get_referral_count(callback.from_user.id),
        get_subscription_text(callback.from_user.id)
    )
    
    # 4. Собираем интерфейс и эмодзи
    profile_icon = emoji("profile")
    account_icon = emoji("account_icon")
    calendar = emoji("calendar")
    key = emoji("key")
    
    status_text = "Активен" if has_access else "Неактивен"
    
    # Примечание: Если вам нужно вывести количество рефералов в текст профиля, 
    # вы можете добавить переменную {ref_count} в строку ниже.
    text = (
        f"{profile_icon} <b>Личный кабинет</b>\n\n"
        f"{account_icon} Имя: {callback.from_user.full_name}\n"
        f"{calendar} Доступ: {date_text}\n"
        f"{key} Статус: {status_text}\n"
    )
    
    # 5. Обновляем интерфейс сообщения
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_profile_menu()
    )



# ==================== РЕФЕРАЛКА ====================

@dp.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    # 1. Отвечаем Telegram СРАЗУ, чтобы убрать анимацию загрузки кнопки
    await callback.answer()

    # 2. 🔥 ОПТИМИЗАЦИЯ: Запускаем получение информации о боте и подсчет рефералов ПАРАЛЛЕЛЬНО
    bot_info, ref_count = await asyncio.gather(
        callback.bot.get_me(),
        get_referral_count(callback.from_user.id)
    )
    
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start=ref_{callback.from_user.id}"
    
    referral_icon = emoji("referral")
    check = emoji("check")
    
    text = (
        f"{check} <b>Бонусы:</b>\n"
        "• Новый пользователь получает 7 дней доступа\n"
        "• Ты получаешь +7 дней за каждого друга\n\n"
        "Делись ссылкой и получай бесплатный доступ!"
    )
    
    # 3. Обновляем интерфейс меню
    await callback.message.edit_caption(
        caption=text,
        reply_markup=get_referral_menu(ref_link, ref_count)
    )

@dp.callback_query(F.data == "copy_referral")
async def copy_referral(callback: CallbackQuery):
    # Здесь нет тяжелых операций, но вызов callback.answer() 
    # является единственным действием, поэтому он остается как есть.
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
     
    text = (
        f"{info_icon} <b>Информация о боте</b>\n\n"
        f"<b>GrenadeCS2</b> — бот для тренировки гранат, и использовании их в матчах CS2.\n\n"
        f"<b>Доступные карты:</b>\n"
        f"{emoji('mirage')} Mirage\n"
        f"{emoji('dust2')} Dust II\n"
        f"{emoji('inferno')} Inferno\n"
        f"{emoji('nuke')} Nuke\n\n"
        "<b>Возможности:</b>\n"
        f"{emoji('smoke')} Изучение смоков\n"
        f"{emoji('flash')} Тренировка флешек\n"
        f"{emoji('he')} Практика хаешек\n"
        f"{emoji('molotov')} Обучение моликам\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Документы</b>\n"
        "<a href='https://telegra.ph/Polzovatelskoe-soglashenie-GrenadeCS2-08-27'>Пользовательское соглашение</a>\n"
        "<a href='https://telegra.ph/POLITIKA-KONFIDENCIALNOSTI-08-27-80'>Политика конфиденциальности</a>"
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

    # ========== НАСТРОЙКА ТРОТТЛИНГА ==========
    config = SentinelConfig(
        throttling_default_max=5,          # максимум 5 запросов
        throttling_default_per_seconds=10, # за 10 секунд
    )
    await Sentinel.setup(dp, config)
    # =========================================

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