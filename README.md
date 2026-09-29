GrenadeCS2 — это Telegram-бот, который помогает игрокам в CS2 быстро находить и изучать раскидки гранат (смоки, флешки, хешки, молики) прямо во время игры.

Возможности
Для пользователей
6 карт: Mirage, Dust II, Inferno, Nuke, Anubis, Ancient
6 типов гранат: смоки, флешки, хешки, молики, инста-смоки, one-way
Круглый зум прицела — видно даже с телефона
Избранное — сохраняй любимые раскидки
Комбо-связки — несколько гранат с одной позиции
Реферальная система — получай +7 дней за каждого друга
Статистика рефералов (/refstat)
Оплата рублями через Platega (СБП / карта)
Оплата Telegram Stars
7 дней бесплатно при регистрации
Для администратора
Добавление раскидок через FSM (/add)
Загрузка фото респов (/setresp_карта_сторона)
Статистика (/stats, /users)
Ручное начисление дней (/adddays)
Проверка БД (/checkdb)
Список сохранённых фото (/listphotos)
Автоматический зум прицелов (/focus)

Технологии

Технология	Назначение
Python 3.13	Язык разработки
aiogram 3.22	Telegram Bot Framework
FastAPI + Uvicorn	Обработка вебхуков от Platega
SQLite (aiosqlite)	База данных
Pillow	Обработка изображений (зум прицелов)
aiogram-sentinel	Анти-троттлинг
Platega API	Приём платежей (СБП, карты)
Telegram Stars	Альтернативная оплата

Структура проекта
text
grenadecs2-bot/
├── bot.py                  # Точка входа, основные хендлеры
├── admin.py                # Админ-панель (FSM для добавления раскидок)
├── database.py             # Работа с SQLite (пользователи, раскидки, платежи)
├── keyboards.py            # Все инлайн-клавиатуры
├── callback_server.py      # FastAPI для вебхуков Platega
├── platega.py              # Клиент Platega API
├── emojis_config.py        # ID кастомных эмодзи
├── emojis_utils.py         # Утилиты для эмодзи
├── requirements.txt        # Зависимости
├── amvera.yml              # Конфиг для деплоя на Amvera
├── .env                    # Переменные окружения (не в Git!)
└── data/
    └── smoke_bot.db        # База данных (на сервере: /data/)
    
Установка и запуск
1. Клонирование репозитория
bash
git clone https://github.com/твой_username/grenadecs2-bot.git
cd grenadecs2-bot
2. Создание виртуального окружения
bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
3. Установка зависимостей
bash
pip install -r requirements.txt
4. Настройка .env
Создай файл .env в корне проекта:

env
# Telegram Bot
BOT_TOKEN=твой_токен_от_BotFather
PROXY_URL=

# Platega (платёжная система)
PLATEGA_MERCHANT_ID=твой_merchant_id
PLATEGA_SECRET=твой_secret_key
5. Запуск
bash
python bot.py
Бот запустится и будет слушать:

Telegram API (aiogram)

HTTP-сервер на порту 8080 (FastAPI для вебхуков Platega)

Деплой на Amvera
1. Настройка amvera.yml
yaml
meta:
  environment: python
  toolchain:
    name: pip
    version: "3.13"

build:
  requirementsPath: requirements.txt

run:
  scriptName: bot.py
  persistenceMount: /data
  containerPort: 8080
  
2. Переменные окружения

В Amvera → Настройки → Переменные окружения добавь:

Ключ	Значение	Этап
BOT_TOKEN	токен бота	Запуск
PLATEGA_MERCHANT_ID	ID мерчанта	Запуск
PLATEGA_SECRET	секретный ключ	Запуск

3. Деплой
bash
git add .
git commit -m "Deploy"
git push amvera master
4. Настройка домена для вебхуков

Amvera → Настройки → Доменные имена → Добавить → Бесплатный домен Амвера.

Получишь URL вида: https://твой-проект.твой-ник.amvera.io

5. Настройка Callback URL в Platega

В личном кабинете Platega → Callback URL:

text
https://твой-проект.твой-ник.amvera.io/platega/callback


Как работает оплата

Пользователь нажимает «Продлить доступ» в боте
Бот создаёт ссылку через Platega API (create_platega_link)
Пользователь переходит по ссылке и оплачивает (СБП или карта)
Platega отправляет POST на callback_server.py → /platega/callback
Сервер проверяет заголовки X-MerchantId и X-Secret
При статусе CONFIRMED:
Начисляет дни через add_days()
Записывает платёж в БД (для /refstat)
Отправляет пользователю сообщение об успехе

Реферальная система

При /start ref_<user_id> новый пользователь получает +7 дней
Реферер получает +7 дней и уведомление
Команда /refstat показывает:
Сколько всего перешло по ссылке
Сколько из них купило подписку

Кастомные эмодзи
Бот использует Telegram Premium Emoji через <tg-emoji emoji-id="...">.
Все ID хранятся в emojis_config.py, а fallback (обычные эмодзи) — в emojis_utils.py.

Использование:

python
from emojis_utils import emoji
text = f"{emoji('smoke')} <b>Смоки</b>"

База данных

Таблицы
Таблица	Назначение
users	Пользователи, подписки, рефералы
throws	Раскидки (карта, тип, фото, зона, сторона)
payments	Платежи (для статистики)
bot_photos	Фото главного меню и респов
favorites	Избранные раскидки пользователей
Путь к БД
На сервере: /data/smoke_bot.db (постоянное хранилище)

Локально: ./data/smoke_bot.db

Локальное тестирование
bash
# Запуск бота локально
python bot.py

# Проверка callback-сервера
curl http://localhost:8080/
# Должно вернуть: {"status":"ok","service":"Platega callback"}

Команды администратора
Команда	Описание
/add	Добавить новую раскидку
/adddays USER_ID DAYS	Начислить дни вручную
/stats	Статистика бота
/users	Список пользователей
/checkdb	Проверить БД
/listphotos	Список фото
/focus	Зазумить все фото прицелов
/setmain	Установить фото главного меню
/setresp_карта_сторона	Установить фото респов

Безопасность

Все ключи хранятся в .env (не в Git!)
Callback от Platega проверяется по X-MerchantId и X-Secret
Анти-троттлинг через aiogram-sentinel
Проверка доступа через check_access() перед каждым действием
Защита от повторных кликов (message is not modified)

Лицензия
MIT License. Свободно используй, изменяй и распространяй.

Контакты
Telegram: @syntax322

Бот: @GrenadeCS2Help_bot

GitHub Issues: создать issue

Roadmap
База раскидок на 6 карт
Круглый зум прицелов
Избранное и комбо-связки
Реферальная система + статистика
Оплата через Platega (рубли)
Оплата через Telegram Stars
Callback-сервер для вебхуков
Пользовательские паки раскидок
Видео-раскидки (GIF)
Расширение на другие игры (Valorant, Dota 2)

Сделано с ❤️ для CS2-сообщества
