import aiohttp
import uuid
import logging
from typing import Optional

# ========== НАСТРОЙКИ ==========
PLATEGA_MERCHANT_ID = "4ed377e6-ffc2-4b14-8cc0-c0b2dbd94523"
PLATEGA_SECRET = "eGGg0NcNf3HFGpGyRRWiPF5jw6GLb1t3vVxC6L6NzxhGmA8WITqs3BOnEyLoMbHA4V76nwJ2jxfdAfFNzyxCGAFOYF2n731wqbk5"
PLATEGA_API_URL = "https://app.platega.io/v2/transaction/process"
# ==============================


async def create_platega_link(
    amount: float,
    description: str,
    user_id: int,
    days: int
) -> Optional[str]:
    """
    Создаёт универсальную платёжную ссылку Platega (без заданного метода).
    Пользователь сам выберет способ оплаты: СБП или карта МИР.
    
    Возвращает ссылку на оплату или None, если ошибка.
    """
    headers = {
        "Content-Type": "application/json",
        "X-MerchantId": PLATEGA_MERCHANT_ID,
        "X-Secret": PLATEGA_SECRET
    }
    
    # Уникальный ID транзакции (UUID)
    transaction_id = str(uuid.uuid4())
    
    # Payload — то, что вернётся в callback, чтобы понять кому начислять
    payload_data = f"user_{user_id}_days_{days}"
    
    body = {
        "id": transaction_id,
        "paymentDetails": {
            "amount": amount,
            "currency": "RUB"
        },
        "description": description,
        "return": "https://t.me/GrenadeCS2Help_bot",
        "failedUrl": "https://t.me/GrenadeCS2Help_bot",
        "payload": payload_data
        # paymentMethod НЕ передаём — пользователь выберет сам
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(PLATEGA_API_URL, json=body, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    # В ответе приходит поле "redirect" со ссылкой на оплату
                    link = data.get("url") or data.get("redirect")
                    return link
                else:
                    error_text = await response.text()
                    logging.error(f"Platega error {response.status}: {error_text}")
                    return None
    except Exception as e:
        logging.error(f"Platega connection error: {e}")
        return None