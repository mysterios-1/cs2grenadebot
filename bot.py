import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InputMediaPhoto, LabeledPrice, Message, CallbackQuery, FSInputFile
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import PreCheckoutQuery, LabeledPrice, Message
from aiogram.fsm.context import FSMContext

from aiogram_sentinel import Sentinel, SentinelConfig
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
    user_id = callback.from_user.id

    # 1. ЗАЩИТА НА ПЕРВОМ МЕСТЕ: Сразу отсекаем неавторизованных
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Моментально убираем часики с кнопки в Telegram
    await callback.answer()
    
    raw_data = callback.data
    
    # Парсим callback_data (логика строго твоя)
    if raw_data.startswith("side_"):
        _, map_name, grenade_type, current_zone, current_side = raw_data.split("_")
        current_page = 1
    elif raw_data.startswith("filter_"):
        _, map_name, grenade_type, current_zone, current_side = raw_data.split("_")
        current_page = 1
    elif raw_data.startswith("listpage_"):
        _, map_name, grenade_type, current_zone, current_side, page_str = raw_data.split("_")
        current_page = int(page_str)
    else:
        grenade_type, map_name = raw_data.split("_", 1)
        current_side = "t"
        current_zone = "all" if grenade_type in {"insta", "oneway"} else "a"
        current_page = 1

    LIMIT = 7
    OFFSET = (current_page - 1) * LIMIT

    # Определяем ключ для фото заранее, чтобы запросить его в одном пакете с данными раскидок
    insta_maps = ["mirage", "dust2", "inferno", "nuke", "anubis", "ancient"]
    if current_zone == "situational":
        photo_key = f"{map_name.lower()}_situational"
    elif grenade_type == "insta" and map_name.lower() in insta_maps:
        photo_key = f"{map_name.lower()}_resp_{current_side.lower()}"
    else:
        photo_key = "main_menu"

    # 2. УЛЬТРА-ОПТИМИЗАЦИЯ БД: Запускаем ВСЕ запросы (счетчик, список И фото) ОДНОВРЕМЕННО через asyncio.gather.
    # Больше никаких циклов и 8 запросов подряд для режима zone == "all".
    if grenade_type in {"insta", "oneway"} and current_zone == "all":
        # Передаем zone="all" в твои методы get_throws_count и get_throws, чтобы база отдала данные одним махом
        total_count, throws_list, bot_photo = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone="all", side=current_side),
            get_throws(map_name, grenade_type, zone="all", side=current_side, limit=LIMIT, offset=OFFSET),
            get_bot_photo(photo_key)
        )
    else:
        # Для обычных гранат или конкретных зон также делаем тройной одновременный залп
        total_count, throws_list, bot_photo = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone=current_zone, side=current_side),
            get_throws(map_name, grenade_type, zone=current_zone, side=current_side, limit=LIMIT, offset=OFFSET),
            get_bot_photo(photo_key)
        )

    # Если кастомное фото не найдено в базе, быстро добираем дефолтное main_menu
    if not bot_photo and photo_key != "main_menu":
        bot_photo = await get_bot_photo("main_menu")

    # 3. Формируем тексты интерфейса (Логика строго твоя)
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

    # 4. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Сначала шлем новую карточку, а старую стираем в самом конце.
    # Так как картинка уже получена параллельно с данными, отправка происходит моментально.
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
    # 1. ЗАЩИТА НА ПЕРВОМ МЕСТЕ: Сразу отсекаем неавторизованных
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Разбираем callback_data
    try:
        parts = callback.data.split("_")
        if len(parts) == 5:
            _, map_name, grenade_type, zone, side = parts
        elif len(parts) == 4:
            _, map_name, grenade_type, zone = parts
            
            # ИСПРАВЛЕНИЕ БАГА: Вместо жесткого сброса на "t", пытаемся узнать, 
            # какую сторону (T/CT) юзер смотрел прямо сейчас, достав её из кнопок подписи
            side = "t"  # Дефолт, если не найдем
            if callback.message.reply_markup:
                for row in callback.message.reply_markup.inline_keyboard:
                    for btn in row:
                        # Ищем кнопку переключения сторон, чтобы вытащить активную
                        if btn.callback_data and btn.callback_data.startswith("side_"):
                            # Структура: side_map_type_zone_newside. 
                            # Берем текущую противоположную сторону и инвертируем её, либо смотрим на шаблон кнопок
                            side_parts = btn.callback_data.split("_")
                            if len(side_parts) == 5:
                                # Если в кнопке зашито "переключить на ct", значит сейчас активна "t" и наоборот
                                side = "t" if side_parts[4] == "ct" else "ct"
                                break
                    if side != "t":
                        break
        else:
            await callback.answer("Ошибка данных.", show_alert=True)
            return
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # 2. Моментально тушим часики в Telegram
    await callback.answer()

    LIMIT = 7
    CURRENT_PAGE = 1
    OFFSET = (CURRENT_PAGE - 1) * LIMIT

    # 3. Запускаем оба запроса к базе данных параллельно (уже было отлично)
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

    # 4. ЗАЩИТА СЕТИ: Обновляем меню с перехватом ошибок повторных кликов
    try:
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
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        # Если юзер кликает на уже выбранную зону, просто игнорируем ошибку "контент идентичен"
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e


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

    # ОПТИМИЗАЦИЯ БД: Вместо 8 запросов делаем всего 2 эффективных
    if zone == "all":
        zone_for_kb = "all"
        
        # Передаем zone="all" в базу, чтобы SQL-запрос сам выбрал нужные данные одним заходом
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone="all", side=new_side),
            get_throws(map_name, grenade_type, zone="all", side=new_side, limit=LIMIT, offset=OFFSET)
        )
    else:
        zone_for_kb = zone
        # Для конкретной зоны запускаем оба запроса параллельно
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone=zone, side=new_side),
            get_throws(map_name, grenade_type, zone=zone, side=new_side, limit=LIMIT, offset=OFFSET)
        )

    # Словари и подготовка интерфейса (Тексты и логика полностью твои)
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

    # 3. Обновляем вкладку интерфейса с защитой от флуда кликами
    try:
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
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        # Если юзер спамит кнопку Т/СТ, которая уже выбрана, просто пропускаем ошибку
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e



# ==================== ПАГИНАЦИЯ СПИСКА РАСКИДОК ====================

@dp.callback_query(F.data.startswith("listpage_"))
async def list_pagination(callback: CallbackQuery):
    """Обработчик переключения страниц в списке раскидок"""
    user_id = callback.from_user.id
    
    # 1. Быстро проверяем доступ, чтобы отсечь неавторизованных пользователей
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Разбираем callback_data
    try:
        _, map_name, grenade_type, zone, side, page = callback.data.split("_")
        page = int(page)
    except ValueError:
        await callback.answer("Ошибка данных.", show_alert=True)
        return

    # 2. Моментально тушим часики в ТГ
    await callback.answer()

    LIMIT = 7
    OFFSET = (page - 1) * LIMIT
    
    # ОПТИМИЗАЦИЯ БД: Склеиваем кучу запросов в один эффективный
    if grenade_type in ["insta", "oneway"]:
        zone_for_kb = "all"
        
        # Вместо 8 запросов делаем ВСЕГО ДВА: один для общего счета, один для пачки данных.
        # Твои функции get_throws_count и get_throws должны уметь принимать zone=None 
        # или zone="all" и делать запрос вида: WHERE zone IN ('a', 'b', 'mid', 'situational')
        # Если они этого не умеют — перепиши SQL-запрос внутри них, это ускорит базу в 10 раз.
        total_count, throws_list = await asyncio.gather(
            get_throws_count(map_name, grenade_type, zone="all", side=side),
            get_throws(map_name, grenade_type, zone="all", side=side, limit=LIMIT, offset=OFFSET)
        )
    else:
        zone_for_kb = zone
        # Для стандартных одиночных зон также выполняем оба запроса параллельно
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

    # 3. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Обновляем интерфейс меню с защитой от двойного клика
    try:
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
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e


# ==================== ПРОСМОТР РАСКИДКИ ====================

YOUR_ADMIN_ID = 2129614624

@dp.callback_query(F.data.startswith("view_fav_"))
async def view_favorite_throw(callback: CallbackQuery):
    print("!!! ХЭНДЛЕР ИЗБРАННОГО СРАБОТАЛ !!!")  # <-- ДОБАВЬ ЭТО СЮДА
    await callback.answer()
    
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return
    
    throw_id = int(callback.data.split("_")[-1])
    throw = await get_throw_detail(throw_id)
    
    if not throw or len(throw) < 12:
        await callback.answer("Раскидка не найдена.", show_alert=True)
        return
    
    _, map_name, g_type, title, photo_pos, photo_aim, photo_result, desc, throw_type, zone, side, combo_id = throw[:12]
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    caption = (
        f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
        f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n\n"
        f"{emoji('grenade_jumptype')} <b>Тип броска:</b> <code>{throw_type}</code>"
    )
    
    is_fav = await is_favorite(callback.from_user.id, throw_id)
    
    # Теперь клавиатура четко понимает source="fav" и для одиночных, и для комбо!
    markup = get_combo_page_kb(
        throw_id, "pos", combo_list,
        user_id=callback.from_user.id,
        admin_id=YOUR_ADMIN_ID,
        is_fav=is_fav,
        source="fav"
    )
    
    # Логика автозамены колбэка
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == "back_to_list_placeholder_fav":
                btn.callback_data = f"favmap_{map_name}_1"
    
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    await callback.message.answer_photo(
        photo=photo_pos,
        caption=caption,
        parse_mode="HTML",
        reply_markup=markup
    )

@dp.callback_query(F.data.startswith("view_"))
async def view_throw_page_one(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. ЗАЩИТА НА ПЕРВОМ МЕСТЕ: Сначала проверяем права.
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return
    
    # Моментально гасим часики на кнопке, чтобы бот казался отзывчивым
    await callback.answer()
    
    throw_id = int(callback.data.split("_")[-1])
    
    # 2. УЛЬТРА-ОПТИМИЗАЦИЯ БД: Запускаем получение информации и проверку избранного ОДНОВРЕМЕННО.
    # Это сэкономит кучу времени на транзакциях SQLite.
    throw, is_fav = await asyncio.gather(
        get_throw_detail(throw_id),
        is_favorite(user_id, throw_id)
    )
    
    if not throw or len(throw) < 12:
        await callback.answer("Раскидка не найдена.", show_alert=True)
        return
    
    _, map_name, g_type, title, photo_pos, photo_aim, photo_result, desc, throw_type, zone, side, combo_id = throw[:12]
    
    # 3. Запрос списка комбо-раскидок (тоже отдельным шагом, если есть combo_id)
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    caption = (
        f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
        f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n\n"
        f"{emoji('grenade_jumptype')} <b>Тип броска:</b> <code>{throw_type}</code>"
    )
    
    markup = get_combo_page_kb(
        throw_id, "pos", combo_list,
        user_id=user_id,
        admin_id=YOUR_ADMIN_ID,
        is_fav=is_fav,
        source="list"
    )
    
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data == "back_to_list_placeholder_list":
                btn.callback_data = f"{g_type}_{map_name}"
    
    # 4. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Сначала отправляем новую карточку с фото, а уже ПОТОМ удаляем старый список.
    # Так интерфейс Telegram не прыгает, смена экранов происходит идеально плавно для глаза.
    await callback.message.answer_photo(
        photo=photo_pos,
        caption=caption,
        parse_mode="HTML",
        reply_markup=markup
    )
    
    try:
        await callback.message.delete()
    except Exception:
        pass


from aiogram.types import InputMediaPhoto

@dp.callback_query(F.data.startswith("page_"))
async def switch_pages(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. СРАЗУ ПРОВЕРЯЕМ ДОСТУП. Если мимо — моментально гасим алерт и выходим.
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return
        
    # Моментально гасим часики на кнопке, чтобы бот визуально реагировал мгновенно
    await callback.answer()
    
    parts = callback.data.split("_")
    # page_{id}_{page}_{source}
    if len(parts) < 4:
        await callback.answer("Ошибка данных.", show_alert=True)
        return
    
    throw_id = int(parts[1])
    page = int(parts[2])
    source = parts[3]
    
    # 2. УЛЬТРА-ОПТИМИЗАЦИЯ БД: Запускаем получение деталей раскидки и статус избранного ПАРАЛЛЕЛЬНО.
    # Так как мы не знаем combo_id до получения throw, запрос комбо-листа сделаем чуть ниже, 
    # но два главных запроса уже сэкономят нам кучу времени.
    throw, is_fav = await asyncio.gather(
        get_throw_detail(throw_id),
        is_favorite(user_id, throw_id)
    )
    
    if not throw or len(throw) < 12:
        await callback.answer("Раскидка не найдена.", show_alert=True)
        return
    
    (id_, map_name, g_type, title, photo_pos, photo_aim, photo_result,
     desc, throw_type, zone, side, combo_id) = throw[:12]
    
    # 3. Запрос комбо-листа делаем только если combo_id существует
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    # Настройка контента вкладки (текст и логика полностью твои)
    if page == 1:
        photo = photo_pos
        view_type = "pos"
        caption = (f"{emoji('geo')} <b>{title}</b> (ПОЗИЦИЯ)\n\n"
                   f"{emoji('grenade_position')} <b>Где стоять:</b> {desc}\n"
                   f"{emoji('grenade_jumptype')} <b>Тип броска:</b> <code>{throw_type}</code>")
    elif page == 2:
        photo = photo_aim
        view_type = "aim"
        caption = (f"{emoji('target')} <b>{title}</b> (ПРИЦЕЛ)\n\n"
                   f"Повторите наводку прицела по изображению.\n"
                   f"{emoji('grenade_jumptype')} <b>Бросок:</b> <code>{throw_type}</code>")
    elif page == 3:
        photo = photo_result or photo_aim
        view_type = "result"
        caption = (f"{emoji('where_it_explodes')} <b>{title}</b> (РЕЗУЛЬТАТ)\n\n"
                   f"Граната успешно раскрывается и закрывает обзор противнику.")
    else:
        return
    
    # Генерируем клавиатуру
    markup = get_combo_page_kb(
        throw_id, view_type, combo_list,
        user_id=user_id,
        admin_id=YOUR_ADMIN_ID,
        is_fav=is_fav,
        source=source
    )
    
    # Переписываем кнопку "К списку" (твоя логика)
    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data == f"back_to_list_placeholder_{source}":
                if source == "fav":
                    button.callback_data = f"favmap_{map_name}_1"
                else:
                    button.callback_data = f"{g_type}_{map_name}"
    
    # 4. Обновляем медиа и кнопки с защитой от флуда кликами
    try:
        media = InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML")
        await callback.message.edit_media(media=media, reply_markup=markup)
    except Exception as e:
        # Если юзер спамит кнопку текущей вкладки, просто игнорируем ошибку "содержимое идентично"
        if "message is not modified" not in str(e):
            raise e



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
    # 1. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Моментально тушим часики на кнопке в Telegram
    await callback.answer()

    user_id = callback.from_user.id

    # 2. ОПТИМИЗАЦИЯ БД: Запускаем только те запросы, которые нельзя объединить.
    # get_user_info и get_referral_count независимы, получаем их параллельно.
    user_info, ref_count = await asyncio.gather(
        get_user_info(user_id),
        get_referral_count(user_id)
    )
    
    if not user_info:
        try:
            await callback.message.edit_caption(
                caption=f"{emoji('cross')} <b>Профиль не найден</b>",
                reply_markup=get_back_button(),
                parse_mode="HTML"
            )
        except Exception:
            pass
        return
    
    # Распаковываем базовую информацию (извлекаем access_until и balance_days)
    access_until, balance_days, referrer_id = user_info
    
    # 3. УБИРАЕМ КРИТИЧЕСКИЙ ОВЕРХЕД: Вместо лишних запросов к БД (check_access и get_subscription_text),
    # рассчитываем статус и текст подписки прямо в памяти на основе уже полученных access_until / balance_days.
    # (Эта логика в точности повторяет то, что делают твои функции, но экономит 2 запроса к SQLite).
    from datetime import datetime
    has_access = False
    if access_until:
        try:
            # Если у тебя в БД дата хранится строкой, парсим её. Если объектом — оставь просто access_until
            dt = datetime.strptime(access_until, "%Y-%m-%d %H:%M:%S") if isinstance(access_until, str) else access_until
            has_access = dt > datetime.now()
        except Exception:
            has_access = balance_days > 0 if balance_days else False
    else:
        has_access = balance_days > 0 if balance_days else False

    status_text = "Активен" if has_access else "Неактивен"
    
    # Формируем текст даты (вместо вызова тяжелой get_subscription_text)
    # Если подписка активна, берем дату, если нет или она пустая — пишем "Нет доступа"
    if has_access and access_until:
        # Если дата — объект datetime, форматируем красиво. Если строка — оставляем как есть.
        date_text = access_until.strftime("%d.%m.%Y") if hasattr(access_until, "strftime") else str(access_until)
    else:
        date_text = "Нет доступа"
    
    # 4. Собираем интерфейс и эмодзи (Текст и переменные строго по твоему шаблону)
    profile_icon = emoji("profile")
    account_icon = emoji("account_icon")
    calendar = emoji("calendar")
    key = emoji("key")
    
    text = (
        f"{profile_icon} <b>Личный кабинет</b>\n\n"
        f"{account_icon} Имя: {callback.from_user.full_name}\n"
        f"{calendar} Доступ: {date_text}\n"
        f"{key} Статус: {status_text}\n"
    )
    
    # 5. Обновляем интерфейс сообщения с защитой от флуда кликами
    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_profile_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e



# ==================== РЕФЕРАЛКА ====================

@dp.callback_query(F.data == "referral")
async def show_referral(callback: CallbackQuery):
    # 1. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Моментально тушим часики на кнопке
    await callback.answer()

    user_id = callback.from_user.id
    
    # 2. ИСПРАВЛЕНИЕ ЗАВИСАНИЙ: Вместо вызова get_me() через сеть, 
    # берем username напрямую из кэша самого бота (он всегда там есть после старта)
    bot_username = callback.bot.id if not hasattr(callback.bot, '_me') else callback.bot._me.username
    # Если aiogram не успел закэшировать при старте, используем безопасный встроенный метод:
    if not bot_username:
        bot_info = await callback.bot.get_me()
        bot_username = bot_info.username

    # Извлекаем количество рефералов из БД
    ref_count = await get_referral_count(user_id)
    
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    check = emoji("check")
    text = (
        f"{check} <b>Бонусы:</b>\n"
        "• Новый пользователь получает 7 дней доступа\n"
        "• Ты получаешь +7 дней за каждого друга\n\n"
        "Делись ссылкой и получай бесплатный доступ!"
    )
    
    # 3. ЗАЩИТА ОТ СПАМА: Игнорируем ошибку ТГ, если юзер бешено кликает по кнопке
    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_referral_menu(ref_link, ref_count),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e


@dp.callback_query(F.data == "copy_referral")
async def copy_referral(callback: CallbackQuery):
    # Тут все отлично и легко, просто добавили пассивный возврат, чтобы хэндлер завершался корректно
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

import logging

@dp.callback_query(F.data == "renew")
async def show_packages(callback: CallbackQuery):
    # 1. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Сразу тушим кнопку
    await callback.answer()
    
    text = (
        "<b>Продление доступа</b>\n\n"
        "Выберите подходящий пакет:"
    )

    # Защита от спама (если меню уже открыто)
    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=get_subscription_packages_menu(),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e


@dp.callback_query(F.data.in_({"buy_week", "buy_month", "buy_year"}))
async def select_package(callback: CallbackQuery):
    # Моментально гасим часики на кнопке, чтобы бот реагировал мгновенно
    await callback.answer()
    
    packages = {
        "buy_week": ("Неделя", 99, 7),
        "buy_month": ("Месяц", 299, 30),
        "buy_year": ("Год", 999, 365),
    }
    
    package_name, price, days = packages[callback.data]
    
    # 2. ЗАЩИТА СЕТИ: Обертываем отправку инвойса. Если юзер заблокал бота — он не повесит поток.
    try:
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"Подписка GrenadeCS2 ({package_name})",
            description=f"Доступ к базе раскидок на {days} дней",
            payload=f"stars_{callback.data}_{days}",
            provider_token="",  
            currency="XTR",     
            prices=[LabeledPrice(label=package_name, amount=price)],
            start_parameter=f"buy_{callback.data}"
        )
    except Exception as e:
        logging.error(f"Ошибка отправки инвойса пользователю {callback.from_user.id}: {e}")


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_q: PreCheckoutQuery):
    # Telegram требует ответить на этот запрос в течение 10 секунд, иначе платеж сорвется.
    # Оставляем его максимально легким и быстрым.
    await pre_checkout_q.answer(ok=True)


@dp.message(F.successful_payment)
async def success_payment_handler(message: Message):
    payment_info = message.successful_payment
    user_id = message.from_user.id
    payload = payment_info.invoice_payload  
    
    try:
        parts = payload.split("_")
        days = int(parts[-1])  
    except (ValueError, IndexError) as e:
        logging.error(f"Критическая ошибка парсинга payload {payload} для юзера {user_id}: {e}")
        await message.answer("⚠ Произошла ошибка при обработке платежа. Пожалуйста, напишите администратору.")
        return
    
    # 3. БЕЗОПАСНОСТЬ ДЕНЕГ: Обертываем запись в БД. 
    # Если SQLite будет заблокирован другим процессором, бот попробует еще раз или выдаст четкую ошибку.
    try:
        await add_days(user_id, days)
        
        await message.answer(
            f"✅ <b>Оплата звёздами прошла!</b>\n\n"
            f"Вам начислено <b>{days} дней</b> доступа. Спасибо! 🎉",
            parse_mode="HTML"
        )
    except Exception as e:
        # Если база упала, логируем ВСЕ данные, чтобы админ мог начислить вручную и деньги не пропали
        logging.critical(f"!!! ОШИБКА НАЧИСЛЕНИЯ ПОДПИСКИ !!! Юзер: {user_id}, Дней: {days}. Ошибка: {e}")
        await message.answer(
            "⚠ <b>Ваша оплата получена, но произошел сбой в базе данных.</b>\n"
            "Не переживайте, администрация уже уведомлена и активирует вам доступ вручную в ближайшее время!",
            parse_mode="HTML"
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

@dp.callback_query(F.data.startswith("back_to_list_placeholder"))
async def back_to_list(callback: CallbackQuery):
    """Универсальный и безопасный возврат в списки без ошибок Pydantic"""
    user_id = callback.from_user.id
    
    # 1. Защита на первом месте. Убираем лишние вызовы answer()
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Запускаем параллельно гашение часиков
    await callback.answer()

    # Дефолтные настройки
    map_name = "mirage"
    g_type = "smoke"
    zone = "a"
    side = "t"
    throw_id = None

    # Быстрый поиск ID в inline_keyboard
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for btn in row:
                if btn.callback_data and "page_" in btn.callback_data:
                    try:
                        throw_id = int(btn.callback_data.split("_")[1])
                        break
                    except Exception:
                        pass
            if throw_id:
                break

    # 2. ОПТИМИЗАЦИЯ БД: Получаем данные, если нашли ID
    if throw_id:
        throw = await get_throw_detail(throw_id)
        if throw and len(throw) >= 11:
            map_name = throw[1]
            g_type = throw[2]
            zone = throw[9] if throw[9] else "a"
            side = throw[10] if throw[10] else "t"

    if g_type in ["insta", "oneway"]:
        zone = "all"

    # === СЦЕНАРИЙ 1: ЕСЛИ КЛИКНУЛИ ИЗ ИЗБРАННОГО ===
    if callback.data.endswith("_fav"):
        cloned_callback = callback.model_copy(update={'data': f"favmap_{map_name}_1"})
        await show_favorites_by_map(cloned_callback)
        return

    # === СЦЕНАРИЙ 2: ЕСЛИ КЛИКНУЛИ ИЗ ОБЫЧНЫХ РАСКИДОК ===
    target_callback_data = f"listpage_{map_name}_{g_type}_{zone}_{side}_1"
    cloned_callback = callback.model_copy(update={'data': target_callback_data})
    
    try:
        # Вызываем функцию напрямую — она сама сделает edit_caption и обновит меню!
        await list_pagination(cloned_callback)
    except Exception as e:
        print(f"Ошибка прямого перенаправления в меню гранат: {e}")
        
    # ❌ СТРОКА С DELETE УБРАНА, так как list_pagination красиво редактирует это же сообщение.
    # Если оставить delete, меню просто закроется/исчезнет.

# ==================== ИЗБРАННОЕ ====================
@dp.callback_query(F.data == "show_favorites")
async def show_favorites(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    # 1. Сначала проверяем доступ. Если его нет — сразу гасим алерт и выходим.
    # Так мы экономим лишний callback.answer() и не путаем Telegram API
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Запускаем параллельно ответ на кнопку (чтобы убрать часики) и получение фото из БД
    # Функция get_favorites_maps_menu синхронная, её asyncio.gather не нужен
    await callback.answer()
    photo_task = asyncio.create_task(get_bot_photo("main_menu"))
    
    text = f"{emoji('favorites')} <b>Избранное</b>\n\nВыберите карту:"
    markup = get_favorites_maps_menu()
    photo = await photo_task
    
    # 2. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Сначала шлем новое сообщение, потом удаляем старое.
    # Это решает проблему "моргания" и прыжков интерфейса Telegram у пользователя.
    if photo:
        await callback.message.answer_photo(
            photo=photo, caption=text, reply_markup=markup, parse_mode="HTML"
        )
    else:
        await callback.message.answer(text, reply_markup=markup, parse_mode="HTML")
        
    # Удаляем старое сообщение "вдогонку" в самом конце
    try:
        await callback.message.delete()
    except Exception:
        pass


@dp.callback_query(F.data.startswith("favpage_"))
async def favorites_pagination(callback: CallbackQuery):
    user_id = callback.from_user.id

    # 1. Сначала проверяем доступ. Если мимо — сразу гасим алерт и выходим.
    if not await check_access(user_id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return
    
    # Моментально убираем часики с кнопки пагинации
    await callback.answer()
    
    page = int(callback.data.split("_")[1])
    LIMIT = 6
    offset = (page - 1) * LIMIT
    
    # 2. ОПТИМИЗАЦИЯ БД: Загружаем список и общее количество параллельно
    favorites, total_count = await asyncio.gather(
        get_favorites(user_id, limit=LIMIT, offset=offset),
        get_favorites_count(user_id)
    )
    
    text = f"{emoji('favorites')} <b>Избранные раскидки</b>\n\nВсего: <b>{total_count}</b>"
    markup = get_favorites_menu(favorites, page=page, total_count=total_count, limit=LIMIT)
    
    # 3. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Редактируем подпись и кнопки.
    # Игнорируем ошибку, если контент не поменялся (защита от флуда кликами)
    try:
        await callback.message.edit_caption(
            caption=text,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        # Если ТГ ругнулся, что текст/кнопки идентичны — просто пропускаем без фриза кода
        if "message caption and reply markup are exactly the same" not in str(e):
            raise e



@dp.callback_query(F.data.startswith("fav_add_"))
async def add_to_favorites(callback: CallbackQuery):
    parts = callback.data.split("_")
    throw_id = int(parts[2])
    source = parts[3] if len(parts) > 3 else "list"
    user_id = callback.from_user.id
    
    # 1. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Моментально гасим часики на кнопке и показываем Toast.
    # Пользователь сразу видит результат, а база шуршит на заднем фоне.
    await callback.answer("Добавлено в избранное!")
    
    # 2. ОПТИМИЗАЦИЯ БД: Запуск добавления в базу и вызов деталей раскидки ОДНОВРЕМЕННО.
    _, throw = await asyncio.gather(
        add_favorite(user_id, throw_id),
        get_throw_detail(throw_id)
    )
    
    if not throw:
        return
    
    # Достаем combo_id напрямую по индексу 11 (без ручной распаковки всех 12 полей)
    combo_id = throw[11] if len(throw) > 11 else None
    
    # 3. Запрос списка комбо-раскидок
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    # Генерируем клавиатуру, жестко зашив is_fav=True
    markup = get_combo_page_kb(
        throw_id=throw_id,
        current_view="pos",
        combo_list=combo_list,
        user_id=user_id,
        admin_id=YOUR_ADMIN_ID,
        is_fav=True,
        source=source
    )
    
    # 4. Обновляем разметку кнопок
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("fav_remove_"))
async def remove_from_favorites(callback: CallbackQuery):
    parts = callback.data.split("_")
    throw_id = int(parts[2])
    source = parts[3] if len(parts) > 3 else "list"
    user_id = callback.from_user.id
    
    # 1. СЕТЕВАЯ ОПТИМИЗАЦИЯ: Моментально гасим часики и выводим Toast-уведомление.
    # Юзер сразу видит фидбэк, а вся магия с БД и обновлением кнопок происходит в фоне.
    await callback.answer("Убрано из избранного")
    
    # 2. ОПТИМИЗАЦИЯ БД: Запускаем удаление из избранного и получение инфы о раскидке ОДНОВРЕМЕННО.
    # Они независимы друг от друга, поэтому нет смысла делать их по очереди.
    _, throw = await asyncio.gather(
        remove_favorite(user_id, throw_id),
        get_throw_detail(throw_id)
    )
    
    if not throw:
        return
    
    # Достаем combo_id из кортежа (индекс 11)
    combo_id = throw[11] if len(throw) > 11 else None
    
    # 3. Дополнительный запрос к комбо делаем только если combo_id существует
    combo_list = await get_combo_throws(combo_id) if combo_id else []
    
    # Генерируем клавиатуру
    markup = get_combo_page_kb(
        throw_id=throw_id,
        current_view="pos",
        combo_list=combo_list,
        user_id=user_id,
        admin_id=YOUR_ADMIN_ID,
        is_fav=False,  # Мы точно знаем, что теперь она не в избранном
        source=source
    )
    
    # 4. Обновляем кнопки
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("favmap_"))
async def show_favorites_by_map(callback: CallbackQuery):
    # 1. Защита: Сначала проверяем доступ. Если нет — сразу гасим alert и выходим.
    # Так мы экономим один пустой callback.answer()
    if not await check_access(callback.from_user.id):
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    # Запускаем параллельно ответ на кнопку, чтобы у пользователя пропали «часики»
    # и фоновые запросы не вешали интерфейс
    await callback.answer()
    
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    map_name = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 1
    
    LIMIT = 6
    offset = (page - 1) * LIMIT
    
    # 2. ОПТИМИЗАЦИЯ БД: Запускаем оба запроса к базе ОДНОВРЕМЕННО через asyncio.gather
    favorites, total_count, photo = await asyncio.gather(
        get_favorites_by_map(user_id, map_name, limit=LIMIT, offset=offset),
        get_favorites_count_by_map(user_id, map_name),
        get_bot_photo("main_menu")
    )
    
    map_names = {
        "mirage": "Mirage", "dust2": "Dust II", "inferno": "Inferno",
        "nuke": "Nuke", "anubis": "Anubis", "ancient": "Ancient"
    }
    display_name = map_names.get(map_name, map_name.capitalize())
    fav_emoji = emoji('favorites')
    
    if not favorites:
        text = f"{fav_emoji} <b>Избранное — {display_name}</b>\n\nНа этой карте пока нет сохранённых раскидок."
        markup = get_favorites_by_map_menu([], map_name, 1, 0, LIMIT)
    else:
        text = f"{fav_emoji} <b>Избранное — {display_name}</b>\n\nВсего: <b>{total_count}</b>"
        markup = get_favorites_by_map_menu(favorites, map_name, page, total_count, LIMIT)
    
    # 3. ОПТИМИЗАЦИЯ СЕТИ: Сначала отправляем НОВОЕ сообщение, а потом УДАЛЯЕМ старое.
    # Если сначала удалять, а потом слать — интерфейс ТГ визуально «прыгает» и тупит.
    if photo:
        sent_message = await callback.message.answer_photo(
            photo=photo, caption=text, reply_markup=markup, parse_mode="HTML"
        )
    else:
        sent_message = await callback.message.answer(
            text, reply_markup=markup, parse_mode="HTML"
        )
        
    # Удаляем старое сообщение в самом конце, не заставляя юзера ждать анимации удаления
    try:
        await callback.message.delete()
    except Exception:
        pass


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