#!/usr/bin/env python3
"""
Подписка бота на события через Webhook (POST /subscriptions)
=============================================================
Настраивает доставку событий MAX на публичный webhook-URL.
Использование:
    python subscribe_webhook.py          # подписаться
    python subscribe_webhook.py --list   # показать текущие подписки
    python subscribe_webhook.py --delete # удалить все подписки
"""

import os
import sys
import json
import argparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import ssl

API_BASE = "https://platform-api2.max.ru"

DEFAULT_TYPES = ["message_created", "message_callback", "bot_started", "bot_added"]


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    bundle = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "certs", "russian_trusted_root_ca.pem",
    )
    if os.path.exists(bundle):
        ctx.load_verify_locations(bundle)
    return ctx


def _request(method: str, path: str, token: str, body: dict | None = None,
             query: dict | None = None) -> dict:
    url = API_BASE + path
    if query:
        url += "?" + urlencode({k: v for k, v in query.items() if v is not None})
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, method=method,
                  headers={"Authorization": token, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
    except URLError as e:
        raise RuntimeError(f"Сетевая ошибка: {e.reason}")


def list_subscriptions(token: str) -> list:
    return _request("GET", "/subscriptions", token).get("subscriptions", [])


def delete_subscriptions(token: str, url: str):
    return _request("DELETE", "/subscriptions", token, query={"url": url})


def subscribe(token: str, url: str, update_types: list) -> dict:
    return _request("POST", "/subscriptions", token, body={
        "url": url,
        "update_types": update_types,
    })


def main():
    parser = argparse.ArgumentParser(description="Управление webhook-подписками бота MAX")
    parser.add_argument("--url", default=os.environ.get("WEBHOOK_PUBLIC_URL", ""),
                        help="Публичный webhook URL")
    parser.add_argument("--types", default=",".join(DEFAULT_TYPES),
                        help="Типы событий через запятую")
    parser.add_argument("--list", action="store_true", help="Показать текущие подписки")
    parser.add_argument("--delete", action="store_true", help="Удалить подписки")
    args = parser.parse_args()

    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        print("Токен MAX_BOT_TOKEN не задан", file=sys.stderr)
        sys.exit(1)

    if args.list:
        subs = list_subscriptions(token)
        print(json.dumps(subs, ensure_ascii=False, indent=2))
        return

    if args.delete:
        url = args.url or "https://m-bot.consult-b2b.ru/webhook"
        print(delete_subscriptions(token, url))
        return

    url = args.url
    if not url:
        print("Не указан --url (или WEBHOOK_PUBLIC_URL в .env)", file=sys.stderr)
        sys.exit(1)

    types = [t.strip() for t in args.types.split(",") if t.strip()]
    result = subscribe(token, url, types)
    print("Подписка создана:")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()