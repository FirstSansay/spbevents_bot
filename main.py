#!/usr/bin/env python3
"""
Бот для поиска мероприятий в Санкт-Петербурге
==============================================
Чат-бот для мессенджера MAX, который помогает найти интересные события
и мероприятия в Санкт-Петербурге с использованием KudaGo API.

Функции:
    - Поиск мероприятий по категориям
    - События дня
    - Текстовый поиск
    - Бесплатные мероприятия

Использование:
    1. Создайте бота на платформе business.max.ru и получите токен.
    2. Скопируйте .env.example в .env и впишите токен.
    3. pip install -r requirements.txt
    4. python main.py
"""

import os
import json
import time
import sys
import signal
import ssl
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from events_api import EventsAPI, EventsAPIError

API_BASE = "https://platform-api2.max.ru"


# ---------------------------------------------------------------------------
# Работа с API мессенджера MAX
# ---------------------------------------------------------------------------

class MaxApi:
    """Клиент для работы с Bot API мессенджера MAX"""

    SSL_CA_BUNDLE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "certs", "russian_trusted_root_ca.pem",
    )

    def __init__(self, token: str):
        self.token = token
        self.base_url = API_BASE

    def _ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if os.path.exists(self.SSL_CA_BUNDLE):
            ctx.load_verify_locations(self.SSL_CA_BUNDLE)
        return ctx

    def _request(self, method: str, path: str,
                 query: Optional[Dict] = None, body: Optional[Dict] = None,
                 timeout: int = 95) -> Optional[Dict]:
        url = self.base_url + path
        if query:
            url += "?" + urlencode({k: v for k, v in query.items() if v is not None})

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(url, data=data, headers=headers, method=method)

        try:
            with urlopen(req, timeout=timeout, context=self._ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body_err = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                print("Отказано в доступе. Проверьте токен MAX_BOT_TOKEN.", file=sys.stderr)
            else:
                print(f"HTTP {e.code}: {body_err}", file=sys.stderr)
            return None
        except URLError as e:
            print(f"Сетевая ошибка: {e.reason}", file=sys.stderr)
            return None
        except (ValueError, json.JSONDecodeError):
            print("Некорректный ответ API", file=sys.stderr)
            return None

    def get_me(self) -> Optional[Dict]:
        """Информация о боте (проверка токена)"""
        return self._request("GET", "/me")

    def get_updates(self, marker: Optional[int] = None,
                    timeout: int = 30, limit: int = 100,
                    types: Optional[str] = None) -> Optional[Dict]:
        """Long Polling: получение обновлений о событиях"""
        return self._request(
            "GET", "/updates",
            query={
                "timeout": timeout,
                "limit": limit,
                "marker": marker,
                "types": types,
            },
            timeout=timeout + 10,
        )

    def send_message(self, text: str, chat_id: Optional[int] = None,
                     user_id: Optional[int] = None,
                     format_: Optional[str] = "markdown",
                     keyboard: Optional[Dict] = None) -> Optional[Dict]:
        """Отправка сообщения в чат или пользователю.

        keyboard — inline-клавиатура в формате:
            {"buttons": [[{"type": "message", "text": "Категории"}], ...]}
        """
        if chat_id is None and user_id is None:
            raise ValueError("Нужно указать chat_id или user_id")

        query: Dict = {"chat_id": chat_id, "user_id": user_id}
        body: Dict = {"text": text}
        if format_:
            body["format"] = format_
        if keyboard:
            body["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard,
            }]

        return self._request("POST", "/messages", query=query, body=body)


# ---------------------------------------------------------------------------
# Диалоговые состояния
# ---------------------------------------------------------------------------

class BotState(Enum):
    IDLE = "idle"
    WAITING_CATEGORY = "waiting_category"
    WAITING_SEARCH_QUERY = "waiting_search_query"


@dataclass
class UserSession:
    """Состояние диалога конкретного пользователя"""
    user_id: int
    state: BotState = BotState.IDLE
    data: Dict = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Чат-бот
# ---------------------------------------------------------------------------

class EventsBot:
    """Бот для поиска мероприятий в Санкт-Петербурге"""

    COMMANDS = (
        "Команды:\n"
        "/start — главное меню\n"
        "/help — справка\n"
        "/cancel — отменить текущий ввод"
    )

    HELP_TEXT = (
        "Справка бота мероприятий СПб\n\n"
        "Бот помогает найти интересные события в Санкт-Петербурге "
        "с использованием сервиса KudaGo.\n\n"
        "Основные функции:\n"
        "  Категории — выбор типа мероприятия\n"
        "  Сегодня — события дня\n"
        "  Поиск — поиск по тексту\n"
        "  Бесплатно — бесплатные мероприятия\n\n"
        + COMMANDS
    )

    START_TEXT = (
        "Привет! Я бот для поиска мероприятий в СПб.\n\n"
        "Что хотите найти?\n\n"
        "Категории — концерты, выставки, спектакли\n"
        "Сегодня — что происходит сегодня\n"
        "Поиск — найти по названию\n"
        "Бесплатно — бесплатные события\n\n"
        + COMMANDS
    )

    def __init__(self, token: str):
        self.api = MaxApi(token)
        self.events = EventsAPI()
        self.sessions: Dict[int, UserSession] = {}
        self._stop = False

    def _get_session(self, user_id: int) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id=user_id)
        return self.sessions[user_id]

    def _reset_session(self, user_id: int):
        s = self._get_session(user_id)
        s.state = BotState.IDLE
        s.data.clear()

    def _cleanup_sessions(self, max_age: int = 3600):
        now = time.time()
        stale = [
            uid for uid, s in self.sessions.items()
            if now - s.updated_at > max_age
        ]
        for uid in stale:
            del self.sessions[uid]

    def _reply(self, chat_id: int, text: str, keyboard: Optional[Dict] = None):
        self.api.send_message(text, chat_id=chat_id, keyboard=keyboard)

    @staticmethod
    def main_keyboard() -> Dict:
        """Главная inline-клавиатура бота"""
        return {
            "buttons": [
                [{"type": "message", "text": "Сегодня"}],
                [{"type": "message", "text": "Категории"}],
                [{"type": "message", "text": "Поиск"}],
                [{"type": "message", "text": "Бесплатно"}, {"type": "message", "text": "Помощь"}],
            ]
        }

    def categories_keyboard(self) -> Dict:
        """Клавиатура с категориями мероприятий"""
        cats = self.events.EVENT_CATEGORIES
        popular = ["concert", "theater", "exhibition", "cinema", "festival", "quest",
                   "tour", "recreation", "party", "kids"]
        rows = []
        for i in range(0, len(popular), 3):
            rows.append([
                {"type": "message", "text": cats[slug]}
                for slug in popular[i:i + 3] if slug in cats
            ])
        rows.append([{"type": "message", "text": "Главное меню"}])
        return {"buttons": rows}

    def _handle_command(self, user_id: int, chat_id: int, command: str):
        cmd = command.lower()

        if cmd == "/start":
            self._reset_session(user_id)
            self._reply(chat_id, self.START_TEXT, keyboard=self.main_keyboard())

        elif cmd == "/help":
            self._reply(chat_id, self.HELP_TEXT, keyboard=self.main_keyboard())

        elif cmd == "/cancel":
            self._reset_session(user_id)
            self._reply(chat_id, "Ввод отменён. Выберите действие из меню.",
                        keyboard=self.main_keyboard())

        else:
            self._reply(chat_id, "Неизвестная команда. Введите /help")

    def _handle_state(self, user_id: int, chat_id: int, session: UserSession, text: str):
        """Обработка сообщения в зависимости от состояния диалога."""

        if session.state == BotState.WAITING_CATEGORY:
            return self._handle_category_selection(user_id, chat_id, session, text)

        elif session.state == BotState.WAITING_SEARCH_QUERY:
            return self._handle_search_query(user_id, chat_id, session, text)

        return False

    def _handle_category_selection(self, user_id: int, chat_id: int,
                                   session: UserSession, text: str) -> bool:
        """Обработка выбора категории"""
        categories = self.events.EVENT_CATEGORIES

        selected = None
        for slug, name in categories.items():
            if text.lower() in name.lower() or text.lower() == slug:
                selected = slug
                break

        if not selected:
            self._reply(chat_id,
                "Категория не найдена. Попробуйте ещё раз или отправьте /cancel")
            return True

        try:
            events = self.events.get_events_by_category(selected, page_size=5)
        except EventsAPIError as e:
            self._reply(chat_id, f"Ошибка при получении событий: {e}")
            self._reset_session(user_id)
            return True

        if not events:
            self._reply(chat_id, f"Событий в категории '{categories[selected]}' не найдено.")
        else:
            header = f"События в категории: {categories[selected]}\n\n"
            items = "\n\n".join([self.events.format_event(e) for e in events])
            self._reply(chat_id, header + items)

        self._reset_session(user_id)
        return True

    def _handle_search_query(self, user_id: int, chat_id: int,
                             session: UserSession, text: str) -> bool:
        """Обработка текстового поиска"""
        try:
            events = self.events.search_events(text, page_size=5)
        except EventsAPIError as e:
            self._reply(chat_id, f"Ошибка поиска: {e}")
            self._reset_session(user_id)
            return True

        if not events:
            self._reply(chat_id, f"По запросу '{text}' ничего не найдено.")
        else:
            header = f"Результаты поиска: '{text}'\n\n"
            items = "\n\n".join([self.events.format_event(e) for e in events])
            self._reply(chat_id, header + items)

        self._reset_session(user_id)
        return True

    def _handle_free_input(self, user_id: int, chat_id: int,
                           session: UserSession, text: str):
        """Обработка текстовых кнопок в состоянии IDLE"""
        lower = text.lower().strip()

        if lower in ("категории", "категория", "category"):
            self._show_categories(user_id, chat_id, session)

        elif lower in ("сегодня", "today"):
            self._show_today_events(chat_id)

        elif lower in ("поиск", "search"):
            session.state = BotState.WAITING_SEARCH_QUERY
            self._reply(chat_id, "Введите название или тему мероприятия:")

        elif lower in ("бесплатно", "free", "бесплатные"):
            self._show_free_events(chat_id)

        elif lower in ("помощь", "help", "справка"):
            self._reset_session(user_id)
            self._reply(chat_id, self.HELP_TEXT, keyboard=self.main_keyboard())

        elif lower in ("главное меню", "меню", "start", "/start"):
            self._reset_session(user_id)
            self._reply(chat_id, self.START_TEXT, keyboard=self.main_keyboard())

        else:
            self._reply(chat_id,
                "Не понял команду. Используйте кнопки или /help",
                keyboard=self.main_keyboard())

    def _show_categories(self, user_id: int, chat_id: int, session: UserSession):
        """Показать список категорий с кнопками"""
        session.state = BotState.WAITING_CATEGORY
        self._reply(chat_id, "Выберите категорию мероприятия:",
                    keyboard=self.categories_keyboard())

    def _show_today_events(self, chat_id: int):
        """Показать события дня"""
        try:
            events = self.events.get_events_today(page_size=5)
        except EventsAPIError as e:
            self._reply(chat_id, f"Ошибка: {e}")
            return

        if not events:
            self._reply(chat_id, "Сегодня мероприятий не найдено.",
                        keyboard=self.main_keyboard())
        else:
            header = "Сегодня в Петербурге:\n\n"
            items = "\n\n".join([self.events.format_event(e) for e in events])
            self._reply(chat_id, header + items, keyboard=self.main_keyboard())

    def _show_free_events(self, chat_id: int):
        """Показать бесплатные события"""
        try:
            events = self.events.get_free_events(page_size=5)
        except EventsAPIError as e:
            self._reply(chat_id, f"Ошибка: {e}")
            return

        if not events:
            self._reply(chat_id, "Бесплатных мероприятий не найдено.",
                        keyboard=self.main_keyboard())
        else:
            header = "Бесплатные мероприятия в Петербурге:\n\n"
            items = "\n\n".join([self.events.format_event(e) for e in events])
            self._reply(chat_id, header + items, keyboard=self.main_keyboard())

    def _handle_text(self, user_id: int, chat_id: int, text: str):
        text = text.strip()
        if not text:
            return

        if text.startswith("/"):
            self._handle_command(user_id, chat_id, text)
            return

        session = self._get_session(user_id)
        session.updated_at = time.time()

        if session.state != BotState.IDLE:
            if self._handle_state(user_id, chat_id, session, text):
                return
            self._reply(chat_id, "Продолжите ввод или /cancel для отмены.")
            return

        self._handle_free_input(user_id, chat_id, session, text)

    def handle_update(self, update: Dict):
        update_type = update.get("update_type")

        if update_type == "message_created":
            message = update.get("message") or {}
            body = message.get("body") or {}
            text = body.get("text") or ""

            recipient = message.get("recipient") or {}
            chat_id = recipient.get("chat_id")

            sender = message.get("sender") or {}
            user_id = sender.get("user_id")

            if chat_id is not None and user_id is not None:
                self._handle_text(user_id, chat_id, text)
            elif user_id is not None:
                self.api.send_message(
                    "Не удалось определить чат. Попробуйте ещё раз.", user_id=user_id)

        elif update_type == "bot_started":
            chat_id = update.get("chat_id")
            user_id = update.get("user", {}).get("user_id")
            if chat_id is not None and user_id is not None:
                self._reset_session(user_id)
                self._reply(chat_id, self.START_TEXT, keyboard=self.main_keyboard())

    def run(self):
        me = self.api.get_me()
        if me:
            name = me.get("name") or me.get("username") or "бот"
            print(f"Авторизован как: {name}")
        else:
            print("Не удалось авторизоваться. Проверьте токен MAX_BOT_TOKEN.", file=sys.stderr)
            return

        marker: Optional[int] = None
        print("Бот запущен. Ожидание сообщений... (Ctrl+C для остановки)")

        while not self._stop:
            try:
                data = self.api.get_updates(
                    marker=marker,
                    timeout=30,
                    types="message_created,bot_started",
                )
                if not data:
                    self._cleanup_sessions()
                    time.sleep(1)
                    continue

                updates = data.get("updates") or []
                new_marker = data.get("marker")
                if new_marker is not None:
                    marker = new_marker

                for update in updates:
                    try:
                        self.handle_update(update)
                    except Exception as e:
                        print(f"Ошибка обработки события: {e}", file=sys.stderr)

            except Exception as e:
                if self._stop:
                    break
                print(f"Ошибка опроса: {e}", file=sys.stderr)
                time.sleep(3)

        print("Бот остановлен.")


def main():
    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        print(
            "Токен бота не задан.\n"
            "Установите переменную окружения MAX_BOT_TOKEN или укажите его в .env:\n"
            "    cp .env.example .env\n"
            "Токен можно получить на платформе бизнес.max.ru в разделе Чат-боты.",
            file=sys.stderr,
        )
        sys.exit(1)

    bot = EventsBot(token)

    def stop(signum, frame):
        bot._stop = True
        print("\nПолучен сигнал остановки...")

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    bot.run()


if __name__ == "__main__":
    main()
