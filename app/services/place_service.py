"""Витрина заведений: карточки с загрузкой кухни и временем до готовности (главный экран)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models.establishment import Establishment
from app.repositories.menu_repository import EstablishmentRepository, MenuRepository
from app.repositories.order_repository import OrderRepository
from app.services.slot_service import SlotService
from app.utils.time_utils import combine, local_now

# Порог «свободно / небольшая очередь / всё занято» по доле свободных минут.
BUSY_SHARE = 0.6
PACKED_SHARE = 0.25
LOAD_WINDOW_MINUTES = 60
# Дальше этого срока не обещаем «заберёте через N минут»: гостю это не полезно.
MAX_READY_MINUTES = 90


class PlaceService:
    """Собирает то, что видно в списке заведений: фото, рейтинг, загрузку, время."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.places = EstablishmentRepository(db)
        self.menu = MenuRepository(db)
        self.orders = OrderRepository(db)
        self.slots = SlotService(db)

    def list_cards(self, *, now: datetime | None = None) -> list[dict]:
        reference = now or local_now()
        cards = [self.card(place, now=reference) for place in self.places.list_all()]
        # Сначала те, где заказ можно забрать раньше.
        return sorted(
            cards,
            key=lambda card: (
                not card["is_open_now"],
                card["ready_in_minutes"] if card["ready_in_minutes"] is not None else 10**6,
            ),
        )

    def card(self, place: Establishment, *, now: datetime | None = None) -> dict:
        reference = now or local_now()
        items = self.menu.list_for_establishment(place.id, only_active=True)
        max_prep = max((item.prep_time_minutes for item in items), default=0)
        # Названия блюд отдаём в карточку: поиск ищет и по еде тоже.
        dish_names = [item.name for item in items][:12]

        is_open = self._is_open(place, reference)
        nearest = (
            self.slots.nearest_available(place, min_lead_minutes=max_prep, now=reference)
            if is_open
            else None
        )
        load, label, ready_in = self._load(place, nearest, reference, max_prep)

        return {
            "id": place.id,
            "name": place.name,
            "address": place.address,
            "cuisine": place.cuisine,
            "photo": place.photo,
            "rating": float(place.rating or 0),
            "reviews_count": place.reviews_count or 0,
            "opens_at": place.opens_at,
            "closes_at": place.closes_at,
            "is_open_now": is_open and nearest is not None,
            "ready_in_minutes": ready_in,
            "nearest_slot": nearest.isoformat() if nearest else None,
            "load": load,
            "load_label": label,
            "dishes_count": len(items),
            "popular_dishes": dish_names,
        }

    @staticmethod
    def _is_open(place: Establishment, reference: datetime) -> bool:
        """Открыто ли сейчас: сравниваем время с часами работы заведения."""
        opens = combine(reference.date(), place.opens_at)
        closes = combine(reference.date(), place.closes_at)
        if closes <= opens:                       # смена через полночь
            return reference >= opens or reference <= closes
        return opens <= reference <= closes

    def _load(
        self,
        place: Establishment,
        nearest: datetime | None,
        reference: datetime,
        max_prep: int,
    ) -> tuple[str, str, int | None]:
        """Загрузка кухни на ближайший час и время до готовности заказа."""
        if nearest is None:
            if self._is_open(place, reference):
                return "packed", "Все минуты заняты", None
            return "closed", f"Откроется в {place.opens_at:%H:%M}", None

        day = reference.date()
        window_start = max(reference + timedelta(minutes=max_prep), reference)
        window_end = window_start + timedelta(minutes=LOAD_WINDOW_MINUTES)
        views = self.slots.build_slots(place, day, now=reference, min_lead_minutes=max_prep)
        in_window = [v for v in views if window_start <= v.slot_datetime <= window_end]

        if in_window:
            free_share = sum(1 for v in in_window if v.available) / len(in_window)
        else:
            free_share = 1.0

        if free_share >= BUSY_SHARE:
            load, label = "free", "Свободно сейчас"
        elif free_share >= PACKED_SHARE:
            load, label = "busy", "Небольшая очередь"
        else:
            load, label = "packed", "Кухня загружена"

        ready_in = max(int((nearest - reference).total_seconds() // 60), 1)
        # Готовность за пределами окна ожидания не показываем: «через 11 часов» гостю не полезно.
        return load, label, ready_in if ready_in <= MAX_READY_MINUTES else None

    def get(self, place_id: int) -> Establishment:
        place = self.places.get(place_id)
        if place is None:
            raise NotFoundError("Заведение не найдено")
        return place

    def cuisines(self) -> list[str]:
        result: list[str] = []
        for place in self.places.list_all():
            label = place.cuisine or "Другое"
            if label not in result:
                result.append(label)
        return result

    # ── Главный экран: сводка и популярные блюда ────────────────────────────
    def home_stats(self, cards: list[dict], *, now: datetime | None = None) -> dict:
        """Короткая сводка: сколько заведений, блюд, как быстро и сколько заказов."""
        reference = now or local_now()
        dishes = self.menu.count_active()
        prep = self.menu.average_prep_time()
        fastest = [card["ready_in_minutes"] for card in cards if card["ready_in_minutes"]]
        free_today = self._free_slots_today(cards[0]["id"] if cards else None, reference)
        opens_at = None
        if not fastest and cards:
            # Всё закрыто — подскажем, во сколько откроется ближайшее заведение.
            soonest = min(cards, key=lambda card: card["opens_at"])
            opens_at = soonest["opens_at"].strftime("%H:%M")

        return {
            "places_count": len(cards),
            "dishes_count": dishes,
            "open_now_count": sum(1 for card in cards if card["is_open_now"]),
            "fastest_ready_minutes": min(fastest) if fastest else None,
            "opens_at": opens_at,
            "average_prep_minutes": prep,
            "orders_today": self.orders.count_created_on(reference.date()),
            "free_slots_today": free_today,
        }

    def _free_slots_today(self, place_id: int | None, reference: datetime) -> int:
        if place_id is None:
            return 0
        place = self.places.get(place_id)
        if place is None:
            return 0
        views = self.slots.build_slots(place, reference.date(), now=reference)
        return sum(1 for view in views if view.available)

    def popular_dishes(self, limit: int = 8) -> list[dict]:
        """Блюда, которые есть в нескольких заведениях: их показываем на главной.

        Это не выдуманный рейтинг, а честная витрина: видно, у кого это блюдо
        есть и сколько оно стоит.
        """
        items = self.menu.list_active_with_place()
        grouped: dict[str, dict] = {}

        for item in items:
            key = item.name.strip().lower()
            entry = grouped.get(key)
            price = float(item.price)
            if entry is None:
                grouped[key] = {
                    "name": item.name,
                    "photo": item.photo,
                    "description": item.description,
                    "price": price,
                    "prep_time_minutes": item.prep_time_minutes,
                    "places_count": 1,
                    "place_names": [item.establishment.name],
                }
                continue
            entry["places_count"] += 1
            entry["place_names"].append(item.establishment.name)
            if price < entry["price"]:
                entry["price"] = price
                entry["photo"] = item.photo or entry["photo"]
            entry["prep_time_minutes"] = min(entry["prep_time_minutes"], item.prep_time_minutes)

        # Сначала то, что есть в нескольких местах, затем самое быстрое.
        ordered = sorted(
            grouped.values(),
            key=lambda entry: (-entry["places_count"], entry["prep_time_minutes"]),
        )
        for entry in ordered:
            entry["place_names"] = entry["place_names"][:3]
        return ordered[:limit]


def human_day(place: Establishment, moment: datetime) -> str:
    """«Работает до 18:00» — короткая подпись для карточки."""
    return f"до {combine(moment.date(), place.closes_at):%H:%M}"
