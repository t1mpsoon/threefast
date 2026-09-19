"""Тесты аналитики: подтверждение критериев успеха кейса (Ф-9)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.order import Order, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreateRequest
from app.services.analytics_service import AnalyticsService
from app.services.order_service import OrderService
from tests.conftest import next_local_slot, order_payload


def _tomorrow_at(hour: int, minute: int) -> datetime:
    """Завтра в указанный час, по сетке слотов.

    Слот обязан быть в будущем, иначе бронь не примут. И при этом все заказы
    теста должны попасть в одни сутки — поэтому берём завтра, а отчёт строим
    за эту же дату. Так результат не зависит от часа запуска.
    """
    moment = (datetime.now() + timedelta(days=1)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    remainder = moment.minute % 5
    if remainder:
        moment += timedelta(minutes=5 - remainder)
    return moment


def _report_day() -> date:
    """Дата, за которую строим отчёт: день слотов тестовых заказов."""
    return _tomorrow_at(12, 0).date()


def _picked_up_order(
    db: Session,
    establishment,
    menu,
    *,
    wait_minutes: float,
    key: str,
    at: datetime | None = None,
) -> str:
    """Создаёт заказ и доводит его до picked_up с заданной задержкой выдачи."""
    service = OrderService(db)
    moment = at or next_local_slot()
    created = service.create_order(
        OrderCreateRequest(**order_payload(establishment.id, [(menu[0].id, 1)], moment, key=key))
    )
    order = service.change_status(
        created.order.id, OrderStatus.IN_PROGRESS, expected_version=1,
        establishment_id=establishment.id,
    )
    order = service.change_status(
        created.order.id, OrderStatus.READY, expected_version=order.version,
        establishment_id=establishment.id,
    )
    order = service.change_status(
        created.order.id, OrderStatus.PICKED_UP, expected_version=order.version,
        establishment_id=establishment.id,
    )

    # Фактическое время выдачи: время слота + задержка. В БД хранится UTC-момент,
    # поэтому локальное время слота переводим в реальный момент времени.
    local_pickup = order.slot.slot_datetime + timedelta(minutes=wait_minutes)
    utc_pickup = local_pickup.astimezone().astimezone(timezone.utc)
    OrderRepository(db).mark_picked_up(order.id, utc_pickup)
    db.commit()
    return order.order_code


def test_report_without_data_says_insufficient(db: Session, establishment) -> None:
    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.orders_count == 0
    assert report.average_wait_minutes is None
    assert "Недостаточно данных" in (report.message or "")


def _day_of_orders(db: Session) -> date:
    """День, в который попали слоты созданных заказов.

    Тест не должен зависеть от часов на стене: вечером слот уезжает на завтра,
    и отчёт нужно строить именно за этот день.
    """
    moments = [
        order.slot.slot_datetime
        for order in db.scalars(select(Order).options(joinedload(Order.slot))).unique()
    ]
    if not moments:
        return date.today()
    # Слоты могут разойтись по двум дням: берём тот, где заказов больше.
    counts: dict[date, int] = {}
    for moment in moments:
        counts[moment.date()] = counts.get(moment.date(), 0) + 1
    return max(counts.items(), key=lambda pair: pair[1])[0]


def test_average_wait_computed_from_slot_time(db: Session, establishment, menu) -> None:
    """Ожидание = picked_up_at − время слота, а не время с момента заказа."""
    _picked_up_order(db, establishment, menu, wait_minutes=2, key="analytics-key-01",
                     at=_tomorrow_at(9, 0))
    _picked_up_order(db, establishment, menu, wait_minutes=4, key="analytics-key-02",
                     at=_tomorrow_at(12, 0))

    # Отчёт строим за тот день, в который попали слоты: поздним вечером
    # «через 55 минут» — это уже завтра, и дневной отчёт был бы пустым.
    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.date_from == report.date_to
    assert report.picked_up_count == 2
    assert report.average_wait_minutes is not None
    assert abs(report.average_wait_minutes - 3.0) < 0.5


def test_wait_target_met_flag(db: Session, establishment, menu) -> None:
    _picked_up_order(db, establishment, menu, wait_minutes=1, key="analytics-key-03",
                     at=_tomorrow_at(9, 0))
    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.wait_target_met is True


def test_wait_target_not_met_flag(db: Session, establishment, menu) -> None:
    _picked_up_order(db, establishment, menu, wait_minutes=18, key="analytics-key-04",
                     at=_tomorrow_at(9, 0))
    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.wait_target_met is False


def test_cancelled_orders_excluded_from_wait_but_counted_as_lost(
    db: Session, establishment, menu
) -> None:
    """Edge case Ф-9: отменённые не искажают среднее ожидание."""
    _picked_up_order(db, establishment, menu, wait_minutes=2, key="analytics-key-05",
                     at=_tomorrow_at(9, 0))

    service = OrderService(db)
    # Слот берём внутри сегодняшнего дня: иначе поздним вечером «через 2 часа»
    # уезжает на завтра и в дневной отчёт не попадает.
    created = service.create_order(
        OrderCreateRequest(
            **order_payload(
                establishment.id, [(menu[1].id, 1)], _tomorrow_at(15, 0),
                key="analytics-key-06",
            )
        )
    )
    service.change_status(
        created.order.id, OrderStatus.CANCELLED, expected_version=1,
        establishment_id=establishment.id,
    )

    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.picked_up_count == 1
    assert report.lost_orders_count == 1
    assert abs(report.average_wait_minutes - 2.0) < 0.5


def test_throughput_growth_calculation() -> None:
    """Рост относительно эталона: 47 против 35 в день -> +34.3%."""
    growth = AnalyticsService.throughput_growth(47, 35, days=1)
    assert growth == 34.3


def test_throughput_growth_without_baseline_is_none() -> None:
    assert AnalyticsService.throughput_growth(10, 0, days=1) is None


def test_throughput_growth_for_week_period() -> None:
    """За неделю эталон умножается на число дней."""
    growth = AnalyticsService.throughput_growth(490, 35, days=7)
    assert growth == 100.0


def test_capacity_per_hour_matches_slot_settings(db: Session, establishment) -> None:
    establishment.slot_duration_minutes = 10
    establishment.slot_capacity = 4
    db.commit()
    report = AnalyticsService(db).build_report(
        establishment.id, "day", today=_report_day()
    )
    assert report.capacity_per_hour == 24  # (60/10) * 4


def test_period_resolution() -> None:
    today = datetime(2026, 9, 19).date()
    assert AnalyticsService.resolve_period("day", today=today) == (today, today)
    assert AnalyticsService.resolve_period("week", today=today) == (
        datetime(2026, 9, 13).date(),
        today,
    )
    assert AnalyticsService.resolve_period("month", today=today) == (
        datetime(2026, 8, 21).date(),
        today,
    )


def test_invalid_period_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        AnalyticsService.resolve_period("year")


def test_analytics_api_contract(client, admin_headers) -> None:
    response = client.get("/api/staff/analytics?period=day", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    for field in (
        "period",
        "date_from",
        "date_to",
        "orders_count",
        "picked_up_count",
        "lost_orders_count",
        "average_wait_minutes",
        "baseline_orders_count",
        "baseline_wait_minutes",
        "throughput_growth_percent",
        "capacity_per_hour",
    ):
        assert field in body, f"нет поля {field}"
    assert body["period"] == "day"


def test_analytics_api_rejects_unknown_period(client, admin_headers) -> None:
    response = client.get("/api/staff/analytics?period=year", headers=admin_headers)
    assert response.status_code == 422

# ── Сводка по всей платформе (администратор сервиса) ────────────────────────
def test_platform_report_counts_all_establishments(db: Session, establishment, menu) -> None:
    """Платформенная сводка суммирует заказы всех заведений, без фильтра по одному."""
    from app.models.establishment import Establishment

    second = Establishment(
        name="Второе заведение",
        address="ул. Вторая, 2",
        opens_at=establishment.opens_at,
        closes_at=establishment.closes_at,
        slot_duration_minutes=establishment.slot_duration_minutes,
        slot_capacity=establishment.slot_capacity,
    )
    db.add(second)
    db.flush()

    # Меню второго заведения: сервис создаёт заказ только по своим блюдам.
    from decimal import Decimal

    from app.models.menu_item import MenuItem

    item = MenuItem(
        establishment_id=second.id, name="Блюдо второй точки", category="Прочее",
        price=Decimal("700.00"), prep_time_minutes=5, is_active=True,
    )
    db.add(item)
    db.commit()

    _picked_up_order(db, establishment, menu, wait_minutes=2, key="platform-key-01",
                     at=_tomorrow_at(9, 0))
    _picked_up_order(db, second, [item], wait_minutes=4, key="platform-key-02",
                     at=_tomorrow_at(12, 0))

    report = AnalyticsService(db).build_platform_report("day", today=_report_day())
    assert report.places_total == 2
    assert report.active_places == 2, "обе точки должны быть активны"
    assert report.orders_count == 2
    assert report.picked_up_count == 2
    assert report.average_wait_minutes is not None
    assert abs(report.average_wait_minutes - 3.0) < 0.5, "среднее по двум заведениям"
    assert report.revenue > 0
    assert report.places_by_status["idle"] == 0


def test_platform_report_counts_idle_places(db: Session, establishment, menu) -> None:
    """Заведение без заказов попадает в «простаивают», а не исчезает из сводки."""
    from app.models.establishment import Establishment

    idle = Establishment(
        name="Тихая точка",
        address="ул. Тихая, 3",
        opens_at=establishment.opens_at,
        closes_at=establishment.closes_at,
        slot_duration_minutes=establishment.slot_duration_minutes,
        slot_capacity=establishment.slot_capacity,
    )
    db.add(idle)
    db.commit()

    _picked_up_order(db, establishment, menu, wait_minutes=2, key="platform-key-03",
                     at=_tomorrow_at(9, 0))

    report = AnalyticsService(db).build_platform_report("day", today=_report_day())
    assert report.places_total == 2
    assert report.active_places == 1
    assert report.places_by_status["idle"] == 1


def test_platform_report_without_orders(db: Session, establishment) -> None:
    """Пустая платформа отвечает понятным сообщением, а не нулями без объяснения."""
    report = AnalyticsService(db).build_platform_report("day")
    assert report.orders_count == 0
    assert report.average_wait_minutes is None
    assert report.wait_target_met is False
    assert report.message, "нужно объяснить, почему показателей нет"


def test_platform_analytics_endpoint_requires_super(client: TestClient, admin_headers,
                                                    staff_headers, client_admin) -> None:
    """Ручка /api/super/analytics доступна только администратору сервиса."""
    # Обычный администратор заведения и кухня получают отказ.
    assert client.get("/api/super/analytics", headers=admin_headers).status_code == 403
    assert client.get("/api/super/analytics", headers=staff_headers).status_code == 403

    # Администратор сервиса получает сводку по всей платформе.
    response = client.get("/api/super/analytics", headers=client_admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "day"
    assert body["places_total"] >= 1
    assert "orders_count" in body and "average_wait_minutes" in body
