# callback_server.py
import os
from fastapi import FastAPI, Request, Header, HTTPException
import logging
from dotenv import load_dotenv
from database import add_days
from aiogram.exceptions import TelegramForbiddenError

load_dotenv()

app = FastAPI()

# ========== КЛЮЧИ ИЗ .env ==========
PLATEGA_MERCHANT_ID = os.getenv("PLATEGA_MERCHANT_ID")
PLATEGA_SECRET = os.getenv("PLATEGA_SECRET")
# ===================================

if not PLATEGA_MERCHANT_ID or not PLATEGA_SECRET:
    logging.warning("[Platega] Ключи не найдены в .env!")

logging.basicConfig(level=logging.INFO)

_bot = None


def set_bot(bot_instance):
    """Устанавливает бота для отправки сообщений пользователям"""
    global _bot
    _bot = bot_instance


@app.post("/platega/callback")
async def platega_callback(
    request: Request,
    x_merchantid: str = Header(None),
    x_secret: str = Header(None)
):
    """Принимает уведомления от Platega о статусе платежа"""
    # 1. Проверяем, что запрос от Platega
    if x_merchantid != PLATEGA_MERCHANT_ID or x_secret != PLATEGA_SECRET:
        logging.warning(f"[Platega] Unauthorized: merchant={x_merchantid}")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    # 2. Читаем тело
    try:
        data = await request.json()
    except Exception as e:
        logging.error(f"[Platega] Ошибка чтения JSON: {e}")
        return {"status": "ok"}
    
    logging.info(f"[Platega] Callback: {data}")
    status = data.get("status")
    
    # 3. Обработка статуса
    if status == "CONFIRMED":
        payload = data.get("payload", "")
        try:
            parts = payload.split("_")
            user_id = int(parts[1])
            days = int(parts[3])
            
            await add_days(user_id, days)
            logging.info(f"[Platega] Начислено {days} дней юзеру {user_id}")
            
            if _bot:
                try:
                    await _bot.send_message(
                        user_id,
                        f"✅ <b>Оплата прошла успешно!</b>\n\n"
                        f"Вам начислено <b>{days} дней</b> доступа. Спасибо! 🎉",
                        parse_mode="HTML"
                    )
                except TelegramForbiddenError:
                    logging.warning(f"[Platega] Юзер {user_id} заблокировал бота")
                except Exception as e:
                    logging.error(f"[Platega] Ошибка отправки {user_id}: {e}")
        except (ValueError, IndexError) as e:
            logging.error(f"[Platega] Ошибка payload '{payload}': {e}")
    
    elif status == "CANCELED":
        logging.info(f"[Platega] Платёж отменён: {data.get('id')}")
    elif status == "CHARGEBACKED":
        logging.warning(f"[Platega] Возврат: {data.get('id')}")
    
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"status": "ok", "service": "Platega callback"}