from emojis_config import CUSTOM_EMOJIS

EMOJI_FALLBACK = {
    "bot_icon": "🤖",
    "profile": "👤",
    "referral": "👥",
    "support": "🆘",
    "info": "ℹ️",
    "check": "✅",
    "cross": "❌",
    "left": "👏",
    "right": "🫤",
    "menu": "😴",
    "geo": "💀",
    "grenade_position": "🤲",
    "grenade_jumptype": "🫨",
    "target": "👎",
    "rychka": "🤌",
    "pushpin": "😿",
    "musor": "👩‍🦳",
    "secure": "👨‍🦳",
    "where_it_explodes": "👨‍🦲",
    "ct": "🧙‍♂️",
    "t": "👨‍⚖️",
    "plant_a": "💪",
    "plant_b": "🕵️",
    "mid": "👷",
    "situationally": "🦹‍♂️",
    "map_icon": "🗺️",
    "mirage": "🏛️",
    "dust2": "🌲",
    "inferno": "🔥",
    "nuke": "🏗️",
    "smoke": "💨",
    "flash": "💡",
    "he": "💣",
    "molotov": "🔥",
    "anubis": "👷‍♂️",
    "ancient": "👩‍🎨",
}

def emoji(emoji_key: str) -> str:
    """Возвращает HTML-тег для кастомного эмодзи (ИСПОЛЬЗОВАТЬ ТОЛЬКО В ТЕКСТЕ СООБЩЕНИЙ)"""
    emoji_id = CUSTOM_EMOJIS.get(emoji_key)
    fallback = EMOJI_FALLBACK.get(emoji_key, "❓")
    
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


def get_emoji_text(emoji_key: str, text: str = "") -> str:
    """Возвращает кастомный эмодзи с текстом для сообщений"""
    emoji_part = emoji(emoji_key)
    if text:
        return f"{emoji_part} {text}"
    return emoji_part


def get_button_emoji(emoji_key: str) -> tuple[str | None, str]:
    """
    Специальная функция для клавиатур.
    Возвращает кортеж: (custom_emoji_id, fallback_unicode_emoji)
    """
    emoji_id = CUSTOM_EMOJIS.get(emoji_key)
    fallback = EMOJI_FALLBACK.get(emoji_key, "")
    
    return (str(emoji_id) if emoji_id else None, fallback)

E = emoji  
