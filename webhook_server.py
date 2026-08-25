#!/usr/bin/env python3
"""
Webhook-сервер для бота мероприятий в Санкт-Петербурге
======================================================
Принимает Push-события от MAX через Webhook (POST /webhook) и
передаёт их в EventsBot.handle_update.

В отличие от Long Polling Webhook не требует постоянного опроса —
MAX сам доставляет события на наш URL. Это production-режим работы.

Запуск:
    WEBHOOK_PORT=8000 python webhook_server.py

Для настройки доставки событий на этот URL выполните:
    POST /subscriptions  {"url": "https://<домен>/webhook", "update_types": [...]}
"""

import os
import sys
import json
import signal
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from main import EventsBot

# На каком адресе MAX доставляет события (для подписки)
WEBHOOK_PUBLIC_URL = os.environ.get("WEBHOOK_PUBLIC_URL", "https://m-bot.consult-b2b.ru/webhook")

# Типы событий, на которые подписываемся
WEBHOOK_UPDATE_TYPES = os.environ.get(
    "WEBHOOK_UPDATE_TYPES",
    "message_created,message_callback,bot_started,bot_added",
).split(",")


class WebhookHandler(BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов на webhook-endpoint"""

    server_version = "EventsBotWebhook/1.0"

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # --- GET /health — проверка живости ---

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/healthz", ""):
            self._send_json(200, {"status": "ok", "ts": datetime.now().isoformat()})
        else:
            self._send_json(404, {"error": "not found"})

    # --- POST /webhook — EВENTS от MAX ---

    def do_POST(self):
        if self.path.rstrip("/") != "/webhook":
            return self._send_json(404, {"error": "not found"})

        update = self._read_body()
        if update is None:
            return self._send_json(400, {"error": "invalid json"})

        try:
            self.server.bot.handle_update(update)
        except Exception as e:
            print(f"Ошибка обработки события: {e}", file=sys.stderr)

        # Всегда отвечаем 200, чтобы MAX не считал доставку неудачной
        self._send_json(200, {"ok": True})

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[webhook] {self.client_address[0]} - {fmt % args}\n")


class WebhookServer:
    """Обёртка над ThreadingHTTPServer: хранит бота и запускает сервер"""

    def __init__(self, host: str, port: int, token: str):
        self.bot = EventsBot(token)
        self.host = host
        self.port = port

        self.httpd = ThreadingHTTPServer((host, port), WebhookHandler)
        # Привязываем бота к серверу, чтобы обработчик мог его использовать
        self.httpd.bot = self.bot

    def run(self):
        me = self.bot.api.get_me()
        if not me:
            print("Не удалось авторизоваться. Проверьте токен MAX_BOT_TOKEN.", file=sys.stderr)
            return
        name = me.get("name") or me.get("username") or "бот"
        print(f"Авторизован как: {name}", flush=True)
        print(f"Webhook-сервер слушает {self.host}:{self.port} (POST /webhook)", flush=True)
        print(f"Публичный URL: {WEBHOOK_PUBLIC_URL}", flush=True)

        def stop(signum, frame):
            print("\nПолучен сигнал остановки...", flush=True)
            self.httpd.shutdown()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)

        self.httpd.serve_forever()


def main():
    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        print(
            "Токен бота не задан.\n"
            "Установите переменную окружения MAX_BOT_TOKEN или укажите его в .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("WEBHOOK_PORT", "8000"))
    except ValueError:
        port = 8000

    server = WebhookServer(host, port, token)
    server.run()


if __name__ == "__main__":
    main()