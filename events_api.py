#!/usr/bin/env python3
"""
API-модуль для работы с KudaGo API
====================================
Бесплатное API для поиска событий и мест в крупнейших городах России.
Документация: https://docs.kudago.com/api/

Использование:
    api = EventsAPI()
    events = api.get_events(category="concert")
    today = api.get_events_today()
    results = api.search("концерт")
"""

import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Маркеры «бесконечных» дат в ответах KudaGo
ENDLESS_TS = 253370754000  # 9999-12-31 — событие без окончания
STARTLESS_TS = -62135433000  # 0001-01-01 — начало события не определено


class EventsAPIError(Exception):
    """Базовое исключение для ошибок KudaGo API"""
    pass


class EventsAPI:
    """Клиент для работы с KudaGo API v1.4"""

    BASE_URL = "https://kudago.com/public-api/v1.4"
    LOCATION = "spb"

    EVENT_CATEGORIES = {
        "concert": "Концерты",
        "theater": "Спектакли",
        "exhibition": "Выставки",
        "cinema": "Кинопоказы",
        "entertainment": "Развлечения",
        "festival": "Фестивали",
        "party": "Вечеринки",
        "holiday": "Праздники",
        "kids": "Детям",
        "education": "Обучение",
        "quest": "Квесты",
        "tour": "Экскурсии",
        "recreation": "Активный отдых",
        "stock": "Акции и скидки",
        "fashion": "Мода и стиль",
        "other": "Разное",
    }

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Выполнение HTTP-запроса к API"""
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})

        req = Request(url, headers={"Accept": "application/json"})

        try:
            with urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise EventsAPIError(f"HTTP {e.code}: {body}")
        except URLError as e:
            raise EventsAPIError(f"Сетевая ошибка: {e.reason}")
        except (ValueError, json.JSONDecodeError):
            raise EventsAPIError("Некорректный ответ API")

    def get_event_categories(self) -> List[Dict]:
        """Получить список категорий событий"""
        return self._request("/event-categories/", {"lang": "ru"})

    def get_events(
        self,
        category: Optional[str] = None,
        is_free: Optional[bool] = None,
        actual_since: Optional[str] = None,
        actual_until: Optional[str] = None,
        ids: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Dict:
        """Получить список событий с фильтрами"""
        params = {
            "location": self.LOCATION,
            "page": page,
            "page_size": page_size,
            "fields": "id,title,slug,site_url,dates,place,images,categories,price,is_free",
            "expand": "place,dates",
        }

        if ids:
            params["ids"] = ids

        if category:
            params["categories"] = category

        if is_free is not None:
            params["is_free"] = 1 if is_free else 0

        if actual_since:
            params["actual_since"] = actual_since

        if actual_until:
            params["actual_until"] = actual_until

        return self._request("/events/", params)

    def get_event_detail(self, event_id: int) -> Dict:
        """Получить детали конкретного события"""
        params = {
            "expand": "place,dates,categories",
        }
        return self._request(f"/events/{event_id}/", params)

    def search(self, query: str, page: int = 1, page_size: int = 10) -> Dict:
        """Текстовый поиск событий"""
        params = {
            "q": query,
            "location": self.LOCATION,
            "ctype": "event",
            "page": page,
            "page_size": page_size,
            "expand": "place,dates",
        }
        return self._request("/search/", params)

    def format_event(self, event: Dict) -> str:
        """Форматирование события для вывода в бота (краткий формат)"""
        title = event.get("title", "Без названия")

        dates = event.get("dates", [])
        date_str = self._format_dates(dates)

        place = event.get("place", {})
        place_name = place.get("title", "Место не указано") if place else "Место не указано"

        is_free = event.get("is_free", False)
        price = event.get("price", "")

        site_url = event.get("site_url")
        if site_url:
            link = site_url
        elif event.get("slug"):
            link = f"https://kudago.com/spb/event/{event['slug']}/"
        else:
            link = f"https://kudago.com/spb/event/{event.get('id', '')}"

        lines = [
            f"🎭 {title}",
            f"📅 {date_str}",
            f"📍 {place_name}",
        ]

        if is_free:
            lines.append("🆓 Бесплатно")
        elif price:
            lines.append(f"💰 {price}")

        lines.append(f"🔗 {link}")

        return "\n".join(lines)

    def _format_dates(self, dates: List[Dict]) -> str:
        """Форматирование дат события (ближайшие к сегодня)"""
        if not dates:
            return "Дата уточняется"

        endless = next((d for d in dates if d.get("is_endless")), None)
        if endless:
            start = endless.get("start")
            if self._is_real_timestamp(start):
                try:
                    dt = self._to_datetime(start)
                    return f"с {dt.strftime('%d.%m.%Y')}, постоянно"
                except (ValueError, TypeError, OSError, OverflowError):
                    return "постоянно"
            return "постоянно"

        now = datetime.now().timestamp()
        parsed = []
        for d in dates:
            s = d.get("start")
            if self._is_real_timestamp(s):
                text = self._format_single_date(s)
                if text:
                    parsed.append((float(s), text))
            elif isinstance(s, str):
                text = self._format_single_date(s)
                if text:
                    parsed.append((float("-inf"), text))

        if not parsed:
            return "Дата уточняется"

        future = sorted((p for p in parsed if p[0] >= now), key=lambda p: p[0])
        past = sorted((p for p in parsed if p[0] < now), key=lambda p: p[0], reverse=True)
        ordered = future or past

        items = [text for _, text in ordered[:3]]
        if len(ordered) > 3:
            items.append("...")

        return " — ".join(items)

    @staticmethod
    def _is_real_timestamp(value: Any) -> bool:
        """Проверка, что timestamp — реальная дата, а не маркер бесконечности"""
        return (isinstance(value, (int, float))
                and value < ENDLESS_TS
                and value > STARTLESS_TS)

    @classmethod
    def _to_datetime(cls, value: Any) -> datetime:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    @classmethod
    def _format_single_date(cls, value: Any) -> str:
        """Форматирование одной даты (timestamp или ISO-строка)"""
        if isinstance(value, str):
            try:
                return cls._to_datetime(value).strftime("%d.%m.%Y %H:%M")
            except (ValueError, TypeError):
                return value
        if cls._is_real_timestamp(value):
            try:
                return cls._to_datetime(value).strftime("%d.%m.%Y %H:%M")
            except (ValueError, TypeError, OSError, OverflowError):
                return ""
        return ""

    def get_events_today(self, page_size: int = 10) -> List[Dict]:
        """Получить события, проходящие сегодня (фильтрует по реальным датам)"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        ts_start = int(today_start.timestamp())
        ts_end = int(today_end.timestamp())

        result = self.get_events(
            actual_since=ts_start,
            actual_until=ts_end,
            page_size=min(max(page_size * 5, 50), 100),
        )
        events = result.get("results", [])

        concrete = [
            e for e in events
            if self._has_date_in_range(e.get("dates", []), ts_start, ts_end, endless=False)
        ]
        endless = [
            e for e in events
            if e not in concrete and self._has_endless_date(e.get("dates", []))
        ]
        return (concrete + endless)[:page_size]

    @staticmethod
    def _has_endless_date(dates: List[Dict]) -> bool:
        """Есть ли в датах события бессрочная запись"""
        return any(d.get("is_endless") for d in dates)

    @staticmethod
    def _has_date_in_range(dates: List[Dict], start: int, end: int,
                           endless: bool = True) -> bool:
        """Событие проходит в заданном диапазоне, если есть дата в нём
        (или, при endless=True, если оно бессрочное)"""
        for d in dates:
            if endless and d.get("is_endless"):
                return True
            s = d.get("start")
            if isinstance(s, (int, float)) and start <= s < end:
                return True
        return False

    @staticmethod
    def _is_actual_event(event: Dict, now_ts: int) -> bool:
        """Событие ещё актуально: бессрочное, ещё не закончилось или ещё не началось"""
        dates = event.get("dates", [])
        if not dates:
            return False
        for d in dates:
            if d.get("is_endless"):
                return True
            start = d.get("start")
            end = d.get("end")
            if isinstance(end, (int, float)) and end >= now_ts:
                return True
            if isinstance(start, (int, float)) and start >= now_ts:
                return True
        return False

    def _filter_actual(self, events: List[Dict]) -> List[Dict]:
        """Оставить только события, актуальные на данный момент"""
        now_ts = int(datetime.now().timestamp())
        return [e for e in events if self._is_actual_event(e, now_ts)]

    def get_free_events(self, page_size: int = 10) -> List[Dict]:
        """Получить бесплатные актуальные события"""
        since = int((datetime.now() - timedelta(days=30)).timestamp())
        result = self.get_events(
            is_free=True, actual_since=since, page_size=max(page_size * 4, 20)
        )
        return self._filter_actual(result.get("results", []))[:page_size]

    def get_events_by_category(self, category: str, page_size: int = 10) -> List[Dict]:
        """Получить актуальные события по категории"""
        since = int((datetime.now() - timedelta(days=30)).timestamp())
        result = self.get_events(
            category=category, actual_since=since, page_size=max(page_size * 4, 20)
        )
        return self._filter_actual(result.get("results", []))[:page_size]

    def search_events(self, query: str, page_size: int = 10) -> List[Dict]:
        """Поиск актуальных событий по тексту.
        Поиск возвращает только базовые данные, поэтому после нахождения
        id запрашиваются полные карточки через /events/?ids=.. """
        result = self.search(query, page_size=max(page_size * 4, 20))
        raw = result.get("results", [])

        ids = [str(e["id"]) for e in raw if e.get("id")]
        if not ids:
            return []

        full = self.get_events(
            ids=",".join(ids[:max(page_size * 4, 20)]),
            page_size=max(page_size * 4, 20),
        ).get("results", [])

        full_by_id = {e["id"]: e for e in full}
        events = [full_by_id[e["id"]] for e in raw if e.get("id") in full_by_id]
        return self._filter_actual(events)[:page_size]


if __name__ == "__main__":
    api = EventsAPI()

    print("=== Тест KudaGo API ===\n")

    print("1. Категории событий:")
    cats = api.get_event_categories()
    for c in cats[:5]:
        print(f"  - {c['name']} ({c['slug']})")

    print("\n2. События на сегодня:")
    events = api.get_events_today(page_size=3)
    for e in events:
        print(f"  - {api.format_event(e)}\n")

    print("\n3. Бесплатные события:")
    free = api.get_free_events(page_size=3)
    for e in free:
        print(f"  - {api.format_event(e)}\n")

    print("\n4. Поиск 'концерт':")
    results = api.search_events("концерт", page_size=3)
    for e in results:
        print(f"  - {api.format_event(e)}\n")
