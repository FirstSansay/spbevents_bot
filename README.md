# Бот мероприятий в Санкт-Петербурге

Чат-бот для мессенджера MAX, который помогает найти интересные события и мероприятия в Санкт-Петербурге.

Использует [KudaGo API](https://docs.kudago.com/api/) — бесплатную базу событий для крупнейших городов России.

## Возможности

- **Категории** — поиск по типу мероприятия (концерты, выставки, спектакли и т.д.)
- **Сегодня** — события дня в Петербурге
- **Поиск** — текстовый поиск по мероприятиям
- **Бесплатно** — бесплатные события

Все функции доступны через inline-клавиатуру — кнопки встроены прямо в сообщения бота.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # впишите токен бота
```

### Переменные окружения (`.env`)

| Переменная | Описание |
| --- | --- |
| `MAX_BOT_TOKEN` | Токен бота MAX (раздел «Чат-боты» → «Расширенные настройки») |
| `WEBHOOK_HOST` | Адрес, на котором слушает webhook-сервер (по умолчанию `0.0.0.0`) |
| `WEBHOOK_PORT` | Порт webhook-сервера (по умолчанию `8000`) |
| `WEBHOOK_PUBLIC_URL` | Публичный URL, на который MAX доставляет события |

## Запуск (Webhook)

Бот работает через **Webhook** (production-режим): MAX сам доставляет события на ваш URL — сервер не опрашивает платформу постоянно.

```bash
python webhook_server.py
```

Сервер слушает `WEBHOOK_HOST:WEBHOOK_PORT` и принимает события на `POST /webhook`.

### Настройка подписки на события

Подпишите бота на доставку событий на ваш публичный URL:

```bash
python subscribe_webhook.py --url https://your-domain.com/webhook
```

Управление подписками:

```bash
python subscribe_webhook.py --list     # показать текущие подписки
python subscribe_webhook.py --delete   # удалить все подписки
```

> Webhook требует HTTPS и корректный URL, доступный из интернета. Публичный адрес должен совпадать с `WEBHOOK_PUBLIC_URL`.

### Long Polling (для разработки)

Для локального тестирования без сервера доступен Long Poll:

```bash
python main.py
```

> Long Polling ограничен по скорости и сроку хранения событий — для production используйте Webhook.

## Требования

- Python 3.8+
- Бот, созданный на платформе [MAX для партнёров](https://business.max.ru)
- Токен бота (раздел «Чат-боты» → «Расширенные настройки»)

## Структура

```
spbevents_bot/
├── main.py                # логика бота (обработка команд, состояний)
├── events_api.py          # API-модуль для KudaGo
├── webhook_server.py      # webhook-сервер (production-режим)
├── subscribe_webhook.py   # управление webhook-подписками
├── certs/
│   └── russian_trusted_root_ca.pem   # сертификат Минцифры
├── .env.example
├── .env
├── requirements.txt
├── .gitignore
└── README.md
```

## Inline-клавиатура

Бот отправляет кнопки прямо в сообщениях (`attachments` с типом `inline_keyboard`):

- Главное меню: Сегодня / Категории / Поиск / Бесплатно / Помощь
- Меню категорий: популярные категории + Главное меню

Кнопки типа `message` — нажатие отправляет боту готовый текст, который обрабатывается в `_handle_free_input` (`main.py`).

## API

Бот использует KudaGo API v1.4 (бесплатное, без ключа):

- `GET /events/` — список событий с фильтрами (по категории, бесплатные, «сегодня»)
- `GET /search/` — текстовый поиск
- `GET /event-categories/` — категории событий

## Развёртывание на сервере (systemd)

Пример unit-файла для запуска под systemd:

```ini
[Unit]
Description=SPb events bot for MAX messenger (KudaGo API) — Webhook
After=network.target

[Service]
Type=simple
User=sansay
WorkingDirectory=/path/to/spbevents_bot
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/path/to/spbevents_bot/.env
ExecStart=/path/to/spbevents_bot/.venv/bin/python /path/to/spbevents_bot/webhook_server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Примечания

- **KudaGo API** — бесплатное, не требует регистрации
- **Webhook** — production-режим, MAX доставляет события на ваш URL
- **Long Polling** — режим для разработки и тестирования
- **Лицензия**: MIT
