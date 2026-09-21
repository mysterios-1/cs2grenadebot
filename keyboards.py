import asyncio

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import get_throw_detail
from emojis_utils import emoji, get_button_emoji
from urllib.parse import quote


def create_btn(emoji_key: str, text: str, **kwargs) -> InlineKeyboardButton:
    """
    Вспомогательная функция для создания кнопки с поддержкой кастомных эмодзи.
    kwargs принимает параметры вроде callback_data или switch_inline_query.
    """
    emoji_id, fallback = get_button_emoji(emoji_key)
    
    if emoji_id:
        return InlineKeyboardButton(text=text, icon_custom_emoji_id=emoji_id, **kwargs)
    else:
        button_text = f"{fallback} {text}".strip() if fallback else text
        return InlineKeyboardButton(text=button_text, **kwargs)


def get_main_menu(has_access: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(create_btn("map_icon", "Карты", callback_data="show_maps"))
    builder.row(create_btn("favorites2", "Избранное", callback_data="show_favorites"))
    builder.row(create_btn("profile", "Личный кабинет", callback_data="profile"))
    builder.row(create_btn("referral", "Пригласить друга", callback_data="referral"))
    builder.row(create_btn("support", "Поддержка", callback_data="support"))
    builder.row(create_btn("info", "Инфо", callback_data="info"))

    return builder.as_markup()


def get_maps_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для выбора карт"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        create_btn("mirage", "Mirage", callback_data="map_mirage"),
        create_btn("dust2", "Dust II", callback_data="map_dust2")
    )
    builder.row(
        create_btn("inferno", "Inferno", callback_data="map_inferno"),
        create_btn("nuke", "Nuke", callback_data="map_nuke")
    )
    builder.row(
        create_btn("anubis", "Anubis", callback_data="map_anubis"),
        create_btn("ancient", "Ancient", callback_data="map_ancient")
    )
    builder.row(create_btn("left", "Назад", callback_data="back_main"))
    
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_map_detail_menu(map_name: str) -> InlineKeyboardMarkup:
    """Меню для конкретной карты со ВСЕМИ типами гранат (6 вариантов)"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        create_btn("smoke", "Insta Smoke", callback_data=f"insta_{map_name}"),
        create_btn("smoke", "One-Way Smoke", callback_data=f"oneway_{map_name}")
    )
    builder.row(
        create_btn("smoke", "Smoke", callback_data=f"smoke_{map_name}"),
        create_btn("flash", "Flash", callback_data=f"flash_{map_name}")
    )
    builder.row(
        create_btn("he", "HE", callback_data=f"he_{map_name}"),
        create_btn("molotov", "Molotov", callback_data=f"molotov_{map_name}")
    )
    
    builder.row(
        create_btn("left", "Назад к картам", callback_data="show_maps"),
        create_btn("menu", "Главное меню", callback_data="back_main")
    )
    
    builder.adjust(2)
    return builder.as_markup()


def get_throws_list_menu(map_name: str, grenade_type: str, throws_list: list, page: int, total_count: int, current_zone: str = "a", current_side: str = "t", limit: int = 5) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    cb_zone = "all" if grenade_type in ["insta", "oneway"] else current_zone
    
    # 1. Кнопки сторон (Т/СТ) — Ровно две кнопки в один ряд
    if current_zone != "situational":
        if current_side == "t":
            side_t, emoji_t = "» За Т «", "t"
            side_ct, emoji_ct = "За СТ", None
        else:
            side_t, emoji_t = "За Т", None
            side_ct, emoji_ct = "» За СТ «", "ct"
        
        builder.row(
            create_btn(emoji_t, side_t, callback_data=f"side_{map_name}_{grenade_type}_{cb_zone}_t") if emoji_t else InlineKeyboardButton(text=side_t, callback_data=f"side_{map_name}_{grenade_type}_{cb_zone}_t"),
            create_btn(emoji_ct, side_ct, callback_data=f"side_{map_name}_{grenade_type}_{cb_zone}_ct") if emoji_ct else InlineKeyboardButton(text=side_ct, callback_data=f"side_{map_name}_{grenade_type}_{cb_zone}_ct")
        )
    
    # 2. Кнопки зон — Сетка 2х2 (Только для стандартных гранат)
    if grenade_type not in ["insta", "oneway"]:
        z_a = "» Плент А «" if current_zone == "a" else "Плент А"
        z_b = "» Плент Б «" if current_zone == "b" else "Плент Б"
        z_mid = "» Мид «" if current_zone == "mid" else "Мид"
        z_sit = "» Ситуация «" if current_zone == "situational" else "Ситуация"
    
        builder.row(
            create_btn("plant_a", z_a, callback_data=f"filter_{map_name}_{grenade_type}_a_{current_side}"),
            create_btn("plant_b", z_b, callback_data=f"filter_{map_name}_{grenade_type}_b_{current_side}")
        )
        builder.row(
            create_btn("mid", z_mid, callback_data=f"filter_{map_name}_{grenade_type}_mid_{current_side}"),
            create_btn("situationally", z_sit, callback_data=f"filter_{map_name}_{grenade_type}_situational_{current_side}")
        )
    
    # 3. Список раскидок — СТРОГО каждая раскидка на новой строчке (Row)
    for throw_id, title in throws_list:
        builder.row(InlineKeyboardButton(text=title, callback_data=f"view_{throw_id}"))
        
    # 4. Пагинация (Назад / Далее) — Кнопки встают вместе на один предпоследний ряд
    total_pages = (total_count + limit - 1) // limit
    if total_pages < 1:
        total_pages = 1

    if total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(
                text="Назад",
                callback_data=f"listpage_{map_name}_{grenade_type}_{cb_zone}_{current_side}_{page-1}"
            ))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(
                text="Далее",
                callback_data=f"listpage_{map_name}_{grenade_type}_{cb_zone}_{current_side}_{page+1}"
            ))
        if nav_buttons:
            builder.row(*nav_buttons)

    # 5. Кнопка возврата — Жестко пишем в отдельный ряд, чтобы она стояла одна снизу
    builder.row(create_btn("left", "Назад к категориям", callback_data=f"map_{map_name}"))

    return builder.as_markup()



def get_throw_page_kb(throw_id: int, page: int) -> InlineKeyboardMarkup:
    """Инлайн-кнопки переключения страниц одиночной раскидки"""
    builder = InlineKeyboardBuilder()
    
    if page == 1:
        builder.row(create_btn("right", "Далее (Прицел)", callback_data=f"page_{throw_id}_2"))
    else:
        builder.row(create_btn("left", "Назад (Позиция)", callback_data=f"page_{throw_id}_1"))
        
    builder.row(create_btn("menu", "Главное меню", callback_data="back_main"))
    return builder.as_markup()


def get_combo_page_kb(throw_id, current_view, combo_list=None, user_id=0, admin_id=0, is_fav=False, source="list"):
    builder = InlineKeyboardBuilder()
    
    # 1. Быстро определяем, является ли раскидка одиночной
    is_single = not combo_list or len(combo_list) <= 1
    
    # Текст для кнопки возврата (вынесено из условий, чтобы не дублировать код)
    back_text = "В избранное" if source == "fav" else "К списку"
    
    if is_single:
        if current_view == "pos":
            builder.row(create_btn("right", "Далее", callback_data=f"page_{throw_id}_2_{source}"))
        elif current_view == "aim":
            builder.row(
                create_btn("left", "Позиция", callback_data=f"page_{throw_id}_1_{source}"),
                create_btn("right", "Результат", callback_data=f"page_{throw_id}_3_{source}")
            )
        elif current_view == "result":
            builder.row(create_btn("left", "Назад", callback_data=f"page_{throw_id}_2_{source}"))
        
        # Кнопка избранного
        fav_btn = (create_btn("favorites", "Убрать", callback_data=f"fav_remove_{throw_id}_{source}") if is_fav 
                   else create_btn("favorites", "В избранное", callback_data=f"fav_add_{throw_id}_{source}"))
        
        builder.row(
            create_btn("left", back_text, callback_data=f"back_to_list_placeholder_{source}"),
            fav_btn
        )
        
        if user_id == admin_id:
            builder.row(
                create_btn("rychka", "Изменить", callback_data=f"edit_{throw_id}"),
                create_btn("musor", "Удалить", callback_data=f"del_{throw_id}")
            )
        
        return builder.as_markup()
    
    # 2. ОПТИМИЗАЦИЯ ДЛЯ КОМБО-СВЯЗОК
    total = len(combo_list)
    first_throw_id = combo_list[0][0]
    
    # Быстрый поиск текущего индекса раскидки без полного прохода цикла
    current_index = next((i for i, item in enumerate(combo_list) if item[0] == throw_id), 0)
    
    if current_view == "pos":
        # ИСПРАВЛЕН БАГ: переход к прицелу ТЕКУЩЕЙ раскидки (throw_id), а не всегда первой (first_id)
        builder.row(create_btn("right", "Далее", callback_data=f"page_{throw_id}_2_{source}"))
        
    elif current_view == "aim":
        # Формируем левую кнопку
        left_btn = (create_btn("left", "Позиция", callback_data=f"page_{throw_id}_1_{source}") if current_index == 0 
                    else create_btn("left", "Назад", callback_data=f"page_{combo_list[current_index - 1][0]}_2_{source}"))
        
        # Формируем правую кнопку
        right_btn = (create_btn("right", "Следующая", callback_data=f"page_{combo_list[current_index + 1][0]}_2_{source}") if current_index < total - 1 
                     else create_btn("right", "Результат", callback_data=f"page_{first_throw_id}_3_{source}"))
        
        builder.row(left_btn, right_btn)
        
    elif current_view == "result":
        builder.row(create_btn("left", "Назад", callback_data=f"page_{combo_list[-1][0]}_2_{source}"))
    
    # Кнопка избранного для комбо
    is_current_fav = True if source == "fav" else is_fav
    fav_btn = (create_btn("favorites", "Убрать", callback_data=f"fav_remove_{throw_id}_{source}") if is_current_fav 
               else create_btn("favorites", "В избранное", callback_data=f"fav_add_{throw_id}_{source}"))
    
    builder.row(
        create_btn("left", back_text, callback_data=f"back_to_list_placeholder_{source}"),
        fav_btn
    )
    
    if user_id == admin_id:
        builder.row(
            create_btn("rychka", "Изменить", callback_data=f"edit_{throw_id}"),
            create_btn("musor", "Удалить", callback_data=f"del_{throw_id}")
        )
    
    return builder.as_markup()



def get_profile_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        create_btn("pushpin", "Продлить доступ", callback_data="renew")
    )
    builder.row(
        create_btn("left", "Назад", callback_data="back_main")
    )
    return builder.as_markup()


def get_subscription_packages_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        create_btn("week", "Неделя — 99 TG-Stars", callback_data="buy_week")
    )
    builder.row(
        create_btn("month", "Месяц — 299 TG-Stars", callback_data="buy_month")
    )
    builder.row(
        create_btn("year", "Год — 999 TG-Stars", callback_data="buy_year")
    )
    builder.row(
        create_btn("left", "Назад", callback_data="profile")
    )

    return builder.as_markup()


def get_referral_menu(ref_link: str, ref_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    share_text = quote("Присоединяйся к GrenadeCS2! Имбовые раскидки:")
    share_url = f"https://t.me/share/url?url={quote(ref_link)}&text={share_text}"

    builder.row(
        InlineKeyboardButton(
            text="Поделиться ботом",
            url=share_url
        )
    )
    builder.row(create_btn("left", "Назад", callback_data="back_main"))

    return builder.as_markup()


def get_no_access_menu() -> InlineKeyboardMarkup:
    """Меню для пользователей без доступа"""
    builder = InlineKeyboardBuilder()
    builder.row(create_btn("referral", "Пригласить друга", callback_data="referral"))
    builder.row(create_btn("left", "Назад", callback_data="back_main"))
    return builder.as_markup()


def get_back_button() -> InlineKeyboardMarkup:
    """Универсальная кнопка возврата"""
    builder = InlineKeyboardBuilder()
    builder.row(create_btn("left", "Назад в меню", callback_data="back_main"))
    return builder.as_markup()


# ==================== КЛАВИАТУРЫ ДЛЯ АДМИН-ПАНЕЛИ ====================

def get_admin_maps_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for m in ["mirage", "dust2", "inferno", "nuke", "anubis", "ancient"]:
        builder.row(create_btn(m, m.upper(), callback_data=f"adm_map_{m}"))
    return builder.as_markup()


def get_admin_grenades_kb() -> InlineKeyboardMarkup:
    """Кнопки выбора типа гранаты для администратора"""
    builder = InlineKeyboardBuilder()
    grenades = {
        "insta": "Insta Смоки",
        "smoke": "Смоки",
        "flash": "Флешки",
        "he": "Хаешки",
        "molotov": "Молики",
        "oneway": "One-Way"
    }
    for g_type, g_text in grenades.items():
        emoji_key = "smoke" if g_type in ["insta", "oneway"] else g_type
        builder.row(create_btn(emoji_key, g_text, callback_data=f"adm_type_{g_type}"))
    builder.adjust(2)
    return builder.as_markup()


def get_admin_zones_kb() -> InlineKeyboardMarkup:
    """Кнопки выбора зоны для администратора (в сетке 2х2)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        create_btn("plant_a", "Плент А", callback_data="adm_zone_a"),
        create_btn("plant_b", "Плент Б", callback_data="adm_zone_b")
    )
    builder.row(
        create_btn("mid", "Мид", callback_data="adm_zone_mid"),
        create_btn("situationally", "Ситуация / Разное", callback_data="adm_zone_situational")
    )
    return builder.as_markup()

def get_favorites_menu(favorites_list: list, page: int, total_count: int, limit: int = 6) -> InlineKeyboardMarkup:
    """Клавиатура для раздела 'Избранное' со списком всех раскидок и пагинацией"""
    builder = InlineKeyboardBuilder()
    
    # Список раскидок — выводим как ОБЫЧНЫЕ чистые инлайн-кнопки (без кастомных эмодзи)
    for throw_id, title, map_name, grenade_type in favorites_list:
        builder.row(InlineKeyboardButton(
            text=f"{title} ({map_name})",
            callback_data=f"view_{throw_id}"
        ))
    
    total_pages = (total_count + limit - 1) // limit
    if total_pages < 1:
        total_pages = 1
    
    nav_row = []
    if page > 1:
        nav_row.append(create_btn("left", "Назад", callback_data=f"favpage_{page-1}"))
    if page < total_pages:
        nav_row.append(create_btn("right", "Далее", callback_data=f"favpage_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)
    
    builder.row(create_btn("left", "Назад в меню", callback_data="back_main"))
    return builder.as_markup()



def get_favorites_by_map_menu(favorites_list: list, map_name: str, page: int, total_count: int, limit: int = 6) -> InlineKeyboardMarkup:
    """Список избранных раскидок конкретной карты с пагинацией"""
    builder = InlineKeyboardBuilder()
    
    # Выводим раскидки по карте — тоже чистым текстом, без кастомных эмодзи
    for throw_id, title in favorites_list:
        builder.row(InlineKeyboardButton(
            text=title,
            callback_data=f"view_fav_{throw_id}"
        ))
    
    total_pages = (total_count + limit - 1) // limit
    if total_pages < 1:
        total_pages = 1
    
    nav_row = []
    if page > 1:
        nav_row.append(create_btn("left", "Назад", callback_data=f"favmap_{map_name}_{page-1}"))
    if page < total_pages:
        nav_row.append(create_btn("right", "Далее", callback_data=f"favmap_{map_name}_{page+1}"))
    
    if nav_row:
        builder.row(*nav_row)
    
    builder.row(create_btn("left", "Назад к картам", callback_data="show_favorites"))
    return builder.as_markup()

def get_favorites_maps_menu() -> InlineKeyboardMarkup:
    """Меню выбора карт для раздела Избранное (тут иконки карт через create_btn нужны)"""
    builder = InlineKeyboardBuilder()
    
    builder.row(
        create_btn("mirage", "Mirage", callback_data="favmap_mirage_1"),
        create_btn("dust2", "Dust II", callback_data="favmap_dust2_1")
    )
    builder.row(
        create_btn("inferno", "Inferno", callback_data="favmap_inferno_1"),
        create_btn("nuke", "Nuke", callback_data="favmap_nuke_1")
    )
    builder.row(
        create_btn("anubis", "Anubis", callback_data="favmap_anubis_1"),
        create_btn("ancient", "Ancient", callback_data="favmap_ancient_1")
    )
    builder.row(create_btn("left", "Назад", callback_data="back_main"))
    
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


