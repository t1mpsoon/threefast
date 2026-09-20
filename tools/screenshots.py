"""Набор снимков для презентации проекта.

Запуск:
    python -m tools.screenshots

Что делает:
1. наполняет демо-базу выразительными данными (заказы с разными статусами,
   временем и примечаниями) — иначе на кадрах будет пустая очередь;
2. проходит весь путь гостя, панель кухни, панель администратора заведения
   и раздел администратора сервиса в светлой и тёмной темах;
3. складывает PNG в presentation/ и пишет туда же README со описанием кадров.

Снимки проверок (`tools/visual_check.py`, `tools/crew_shot.py`) лежат отдельно
в shots/ — их назначение в том, чтобы ловить регрессии, а не показывать продукт.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timezone
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("EP_BASE_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parent.parent / "presentation"
ADMIN_PASSWORD = os.environ.get("EP_ADMIN_PASSWORD", "demo-pass-12345")
STAFF_PASSWORD = os.environ.get("EP_STAFF_PASSWORD", "demo-pass-12345")

DESKTOP = {"width": 1440, "height": 950}
MOBILE = {"width": 390, "height": 844}

# Подсказки (nudges.js) при первом заходе открывают диалоги — установка
# приложения, знакомство, уведомления. На кадрах они перекрывают интерфейс,
# поэтому в контексте снимков помечаем их просмотренными заранее.
QUIET_INIT = """
  try {
    localStorage.setItem('ep_tour_seen', '1');
    localStorage.setItem('ep_notify_seen', '1');
    localStorage.setItem('ep_install_later', String(Date.now()));
  } catch (_) { /* приватный режим */ }
"""


def new_context(browser, viewport: dict, scale: int = 2):
    """Контекст для снимка: нужный вьюпорт и без всплывающих подсказок."""
    context = browser.new_context(viewport=viewport, device_scale_factor=scale)
    context.add_init_script(QUIET_INIT)
    return context

# Русские имена: очередь с одинаковыми гостями выглядит как тестовые данные.
GUESTS = [
    ("Айгерим", "+7 701 111 00 01", "Без лука, пожалуйста", "card_on_pickup"),
    ("Данияр", "+7 701 111 00 02", None, "cash_on_pickup"),
    ("Мадина", "+7 701 111 00 03", "Приборы на двоих", "card_on_pickup"),
    ("Ерасыл", "+7 701 111 00 04", None, "cash_on_pickup"),
    ("Камила", "+7 701 111 00 05", "Позвоните, когда будет готово", "cash_on_pickup"),
    ("Нурлан", "+7 701 111 00 06", None, "card_on_pickup"),
    ("Асель", "+7 701 111 00 07", "Соус отдельно", "card_on_pickup"),
    ("Тимур", "+7 701 111 00 08", None, "cash_on_pickup"),
]


def prepare_demo_data() -> int:
    """Наполняет базу так, чтобы на кадрах была живая очередь.

    Заказы удаляем и создаём заново: повторный запуск не должен копить дубли.
    """
    sys.path.insert(0, str(OUT.parent))
    os.environ.setdefault("SECRET_KEY", "presentation-shots")

    from sqlalchemy import delete, select, update

    from app.database import SessionLocal
    from app.models.establishment import Establishment
    from app.models.menu_item import MenuItem
    from app.models.order import Order, OrderStatus
    from app.models.order_item import OrderItem
    from app.models.time_slot import TimeSlot
    from app.schemas.order import OrderCreateRequest
    from app.services.order_service import OrderService

    db = SessionLocal()
    try:
        db.execute(delete(OrderItem))
        db.execute(delete(Order))
        db.execute(update(TimeSlot).values(booked_count=0))
        db.commit()

        place = db.scalars(
            select(Establishment).where(Establishment.name == "Green Bowl")
        ).first() or db.scalars(select(Establishment).order_by(Establishment.id)).first()
        if place is None:
            print("нет заведений — сначала выполните python -m app.init_db")
            return 1

        menu = list(db.scalars(
            select(MenuItem)
            .where(MenuItem.establishment_id == place.id, MenuItem.is_active.is_(True))
            .order_by(MenuItem.id)
            .limit(3)
        ))
        if len(menu) < 3:
            print(f"у заведения «{place.name}» мало блюд для демонстрации")
            return 1

        # Окно работы открываем на сутки целиком, а лимит заказов на минуту
        # поднимаем: снимки делаются в любое время, в том числе ночью, когда
        # заведение закрыто и слотов на ближайшие минуты просто нет.
        # Без этого на кадрах была бы пустая очередь.
        place.opens_at = place.opens_at.replace(hour=0, minute=0)
        place.closes_at = place.closes_at.replace(hour=23, minute=55)
        place.slot_capacity = 6
        db.commit()

        from app.config import settings as app_settings

        app_settings.rate_limit_orders_per_minute = 1000

        from datetime import datetime, timedelta

        service = OrderService(db)
        plan = [
            # (минут до выдачи, блюда, статус)
            (10, [(menu[0].id, 2)], OrderStatus.READY),
            (18, [(menu[1].id, 1)], OrderStatus.READY),
            (25, [(menu[2].id, 1), (menu[0].id, 1)], OrderStatus.IN_PROGRESS),
            (35, [(menu[0].id, 1)], OrderStatus.IN_PROGRESS),
            (48, [(menu[1].id, 2)], OrderStatus.CONFIRMED),
            (62, [(menu[2].id, 1)], OrderStatus.CONFIRMED),
            (78, [(menu[0].id, 1), (menu[1].id, 1)], OrderStatus.CONFIRMED),
            # Отменённый заказ: показывает и «гость не придёт» в очереди,
            # и отдельный экран отмены у гостя.
            (95, [(menu[0].id, 1), (menu[2].id, 2)], OrderStatus.CANCELLED),
        ]

        # Маршрут по статусам: отмену ставим сразу, остальное — по цепочке.
        routes = {
            OrderStatus.CONFIRMED: (),
            OrderStatus.IN_PROGRESS: (OrderStatus.IN_PROGRESS,),
            OrderStatus.READY: (OrderStatus.IN_PROGRESS, OrderStatus.READY),
            OrderStatus.CANCELLED: (OrderStatus.CANCELLED,),
        }

        created = 0
        for index, (minutes, items, target) in enumerate(plan):
            name, phone, note, payment = GUESTS[index % len(GUESTS)]
            moment = datetime.now() + timedelta(minutes=max(minutes, 20))
            moment = moment.replace(second=0, microsecond=0)
            moment = moment.replace(minute=moment.minute - moment.minute % 5)
            try:
                order = service.create_order(OrderCreateRequest(
                    establishment_id=place.id,
                    slot_datetime=moment,
                    guest_name=name,
                    guest_phone=phone,
                    note=note,
                    # Часть заказов — за столиком: смена видит, куда нести.
                    table_number=None if index % 3 == 2 else (index % 5) + 1,
                    items=[{"menu_item_id": i, "quantity": q} for i, q in items],
                    payment_method=payment,
                    idempotency_key=f"presentation-{index:02d}",
                )).order
            except Exception as error:  # noqa: BLE001 — данные для кадра, не критично
                print(f"  заказ {index} не создан: {type(error).__name__}: {error}")
                continue

            for step in routes[target]:
                order = service.change_status(
                    order.id, step, expected_version=order.version,
                    establishment_id=place.id,
                )
            created += 1

        # Второй точке тоже даём заказы: иначе аналитика администратора
        # заведения показывает нули и кадр не о чём.
        history = _fill_history(db)
        print(f"демо-данные: {created} заказов в «{place.name}», "
              f"{history} выданных в «Кафе Central»")
        return 0
    finally:
        db.close()


def _fill_history(db, *, target: int = 46) -> int:
    """Заказы за сегодня для заведения из сида: нужны для аналитики.

    Ждём средний результат около двух минут — именно его кейс называет целью.
    Часть заказов выдаём раньше минуты, часть с задержкой: среднее выходит
    правдоподобным, а не идеальным.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.models.establishment import Establishment
    from app.models.menu_item import MenuItem
    from app.models.order import Order, OrderStatus
    from app.repositories.order_repository import OrderRepository
    from app.schemas.order import OrderCreateRequest
    from app.services.order_service import OrderService

    place = db.scalars(
        select(Establishment).where(Establishment.name == "Кафе Central")
    ).first()
    if place is None:
        return 0

    # Часы открываем на сутки: иначе половина слотов за сегодня недоступна.
    place.opens_at = place.opens_at.replace(hour=0, minute=0)
    place.closes_at = place.closes_at.replace(hour=23, minute=55)
    place.slot_capacity = 6
    db.commit()

    menu = list(db.scalars(
        select(MenuItem)
        .where(MenuItem.establishment_id == place.id, MenuItem.is_active.is_(True))
        .order_by(MenuItem.id)
    ))
    if not menu:
        return 0

    service = OrderService(db)
    repository = OrderRepository(db)
    start = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    # Задержка выдачи по кругу: 30 % успевают за минуту, 45 % — около двух,
    # остальные чуть отстают. Среднее держится у цели кейса.
    delays = [0.5, 1.0, 2.0, 2.0, 3.0, 4.0, 1.5, 2.5]
    made = 0

    for index in range(target):
        moment = start + timedelta(minutes=index * 10)
        name, phone, note, payment = GUESTS[index % len(GUESTS)]
        item = menu[index % len(menu)]
        try:
            order = service.create_order(OrderCreateRequest(
                establishment_id=place.id,
                slot_datetime=moment,
                guest_name=name,
                guest_phone=phone,
                note=note if index % 3 == 0 else None,
                items=[{"menu_item_id": item.id, "quantity": 1 + index % 2}],
                payment_method=payment,
                idempotency_key=f"presentation-history-{index:03d}",
            )).order
        except Exception:  # noqa: BLE001 — данные для кадра
            continue

        for step in (OrderStatus.IN_PROGRESS, OrderStatus.READY, OrderStatus.PICKED_UP):
            order = service.change_status(
                order.id, step, expected_version=order.version,
                establishment_id=place.id,
            )
        # Фактическая выдача: время слота плюс задержка.
        wait = Decimal(str(delays[index % len(delays)]))
        local_pickup = order.slot.slot_datetime + timedelta(minutes=float(wait))
        repository.mark_picked_up(order.id, local_pickup.astimezone().astimezone(timezone.utc))
        made += 1

    db.commit()
    return made


def demo_order_codes() -> dict[str, str]:
    """Коды демо-заказов для кадров: в работе, готовый и отменённый.

    Нужны, чтобы открыть экран гостя и карточку сканера на живых данных,
    а не на выдуманном номере.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.order import Order, OrderStatus

    db = SessionLocal()
    try:
        found: dict[str, str] = {}
        for key, status in (
            ("active", OrderStatus.IN_PROGRESS),
            ("ready", OrderStatus.READY),
            ("cancelled", OrderStatus.CANCELLED),
        ):
            order = db.scalars(
                select(Order).where(Order.status == status.value).order_by(Order.id)
            ).first()
            found[key] = order.order_code if order else ""
        return found
    finally:
        db.close()


def save(page, path: Path, *, full: bool = False, attempts: int = 4) -> None:
    """Снимок с повтором: файл может быть занят синхронизацией каталога.

    Пишем через временный файл и переносим — так на диске не остаётся
    обрезанного PNG, если запись прервётся.
    """
    import time

    # Playwright определяет формат по расширению, поэтому временный файл
    # тоже .png — иначе он откажется писать.
    temp = path.with_name(path.stem + ".part.png")
    for attempt in range(attempts):
        try:
            page.screenshot(path=str(temp), full_page=full)
            temp.replace(path)
            return
        except OSError as error:
            if attempt == attempts - 1:
                raise
            print(f"    повтор записи {path.name}: {error}")
            time.sleep(0.8)


def settle(page, ms: int = 900) -> None:
    """Ждём шрифты и затухание анимаций — иначе кадр ловит полёт карточек."""
    page.wait_for_timeout(ms)
    page.evaluate("() => document.fonts && document.fonts.ready")


def login(page, username: str, password: str, target: str) -> None:
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"**{target}", timeout=20000)
    settle(page, 1400)


def main() -> int:
    if prepare_demo_data() != 0:
        return 1

    OUT.mkdir(exist_ok=True)
    # Чистим прошлый набор: иначе легко показать старый кадр как новый.
    for old in OUT.glob("*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    shots: list[dict[str, str]] = []

    def shot(page, name: str, title: str, note: str, full: bool = False) -> None:
        path = OUT / f"{name}.png"
        save(page, path, full=full)
        shots.append({"file": path.name, "title": title, "note": note})
        print(f"  {path.name}")

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── Путь гостя: светлая тема ───────────────────────────────────────
        context = new_context(browser, DESKTOP)
        page = context.new_page()
        page.goto(f"{BASE}/", wait_until="networkidle")
        settle(page, 2000)
        # Сначала вид как на экране, потом вся страница: на презентации
        # удобнее начинать с того, что человек видит без прокрутки.
        shot(page, "01-guest-home", "Главный экран",
             "Адрес выдачи, поиск по заведению и блюду, промо-баннер с отсчётом "
             "до ближайшего окна выдачи, лента кухонь и карточки заведений")
        shot(page, "02-guest-home-full", "Главный экран целиком",
             "Тот же экран с прокруткой: витрина «Что берут чаще всего» "
             "и объяснение трёх шагов заказа", full=True)

        page.goto(f"{BASE}/e/2/menu", wait_until="networkidle")
        settle(page, 1600)
        shot(page, "03-guest-menu", "Меню заведения",
             "Баннер с параллаксом, липкие категории и карточки блюд: фото 4:3, "
             "цена, кнопка «+» на углу фото", full=True)

        # Собираем заказ: фото летит в корзину, панель поднимается с отскоком.
        first = page.eval_on_selector(".dish", "n => n.dataset.dish")
        page.click(f'.dish[data-dish="{first}"] button[data-act="more"]')
        page.wait_for_timeout(180)
        save(page, OUT / "04-cart-flight.png")
        shots.append({"file": "04-cart-flight.png", "title": "Добавление блюда",
                      "note": "Фото летит в панель корзины, счётчик позиций пульсирует"})

        page.wait_for_timeout(900)
        dishes = page.eval_on_selector_all(".dish", "n => n.map(x => x.dataset.dish)")
        for dish in dishes[1:3]:
            page.click(f'.dish[data-dish="{dish}"] button[data-act="more"]')
            page.wait_for_timeout(500)
        page.click(f'.dish[data-dish="{first}"] button[data-act="more"]')
        settle(page, 900)
        save(page, OUT / "05-cart-ready.png")
        shots.append({"file": "05-cart-ready.png", "title": "Корзина собрана",
                      "note": "Панель с суммой, числом позиций и кнопкой «Продолжить»"})

        # Шторка времени.
        page.click("#cart-open")
        page.wait_for_timeout(1600)
        shot(page, "06-sheet-time", "Шаг 2: время выдачи",
             "Барабаны часов и минут, как будильник в телефоне: показано только "
             "доступное время, прошедшее выбрать нельзя")

        # Выбираем время прокруткой — так это делает гость.
        page.click('#hour-drum .slot:text-is("13")')
        page.wait_for_timeout(600)
        page.click('#minute-drum .slot:text-is("30")')
        page.wait_for_timeout(600)
        shot(page, "06b-sheet-time-picked", "Шаг 2: время выбрано",
             "Выбранное значение подсвечено акцентом, кнопка показывает день и время")

        page.click("#time-confirm")
        page.wait_for_timeout(1300)
        save(page, OUT / "07-sheet-checkout.png")
        shots.append({"file": "07-sheet-checkout.png", "title": "Шаг 3: оформление",
                      "note": "Имя, телефон, примечание к заказу, способ оплаты и сводка "
                              "с кнопками количества"})

        # Пустая форма — показываем проверку полей.
        page.click("#checkout-submit")
        page.wait_for_timeout(700)
        save(page, OUT / "08-validation.png")
        shots.append({"file": "08-validation.png", "title": "Проверка полей",
                      "note": "Подсказки под полями вместо всплывающего окна"})

        page.fill("#guest-name", "Айгерим")
        page.fill("#guest-phone", "+7 701 111 00 01")
        page.fill("#guest-note", "Без лука, приборы на двоих")
        page.wait_for_timeout(400)
        page.click("#checkout-submit")
        page.wait_for_selector(".success", timeout=20000)
        settle(page, 1600)
        shot(page, "09-order-success", "Заказ принят",
             "Номер заказа, время выдачи, прогресс из четырёх шагов и кнопка шаринга")
        context.close()

        # ── Панели: светлая тема ───────────────────────────────────────────
        context = new_context(browser, DESKTOP)
        page = context.new_page()
        login(page, "kitchen-bowl", STAFF_PASSWORD, "/staff")
        shot(page, "10-kitchen-queue", "Кухня: очередь смены",
             "Талон на каждый заказ: время, отсчёт, статус, состав, примечание гостя "
             "и действие «Начать готовить»", full=True)

        page.click('.crew__tab[data-panel="menu"]')
        settle(page, 1400)
        shot(page, "11-kitchen-menu", "Кухня: меню только для просмотра",
             "У роли «кухня» нет правки: цены и состав видны, кнопок изменения нет",
             full=True)
        context.close()

        context = new_context(browser, DESKTOP)
        page = context.new_page()
        login(page, "admin", ADMIN_PASSWORD, "/staff")
        page.click('.crew__tab[data-panel="settings"]')
        settle(page, 1600)
        shot(page, "12-admin-settings", "Администратор заведения: настройки",
             "Часы, вместимость кухни и эталон для аналитики, профиль заведения "
             "и доступ кухни", full=True)

        page.click(".crew__tab[data-panel='report']")
        settle(page, 2000)
        shot(page, "13-admin-analytics", "Администратор заведения: аналитика",
             "Два критерия кейса: среднее ожидание (цель — 2 минуты) и рост "
             "пропускной способности (цель — от 25 %)", full=True)
        context.close()

        # ── Администратор сервиса ──────────────────────────────────────────
        context = new_context(browser, DESKTOP)
        page = context.new_page()
        login(page, "superadmin", ADMIN_PASSWORD, "/super")
        page.wait_for_timeout(1500)
        shot(page, "14-super-places", "Администратор сервиса: заведения",
             "Сводка по платформе и карточки точек с логинами доступа", full=True)

        page.click('.ops-card button[data-act="password"]')
        page.wait_for_timeout(2200)
        save(page, OUT / "15-super-password.png")
        shots.append({"file": "15-super-password.png", "title": "Новый пароль для точки",
                      "note": "Пароль показывается один раз: в базе хранится только хеш"})
        context.close()

        # ── Выдача, слежение и отмена: кадры новых экранов ─────────────────
        codes = demo_order_codes()

        context = new_context(browser, DESKTOP)
        page = context.new_page()
        login(page, "kitchen-bowl", STAFF_PASSWORD, "/staff")
        page.goto(f"{BASE}/scan", wait_until="networkidle")
        settle(page, 1600)
        shot(page, "22-scan-page", "Выдача: сканер заказов",
             "Камера, ручной ввод номера и загрузка фото QR: работает и там, "
             "где камеры нет вовсе")

        if codes["ready"]:
            page.fill("#scan-input", codes["ready"])
            page.click('#scan-form button[type="submit"]')
            page.wait_for_selector(".scan-card", timeout=15000)
            # Плашка «камера недоступна» в этом окружении честная, но на кадре
            # читается как ошибка: ждём, пока она растает.
            settle(page, 6000)
            shot(page, "23-scan-card", "Выдача: заказ открыт по QR",
                 f"Карточка заказа {codes['ready']}: состав, столик и действие "
                 "«Выдать заказ» — одно нажатие вместо поиска в списке")
        context.close()

        context = new_context(browser, MOBILE, 3)
        page = context.new_page()
        if codes["active"]:
            page.goto(f"{BASE}/order?code={codes['active']}", wait_until="networkidle")
            settle(page, 1600)
            shot(page, "24-order-live", "Гость: заказ готовится",
                 "Живой трекинг: статус, шкала «Принят → Готовится → Готово → Выдано» "
                 "и время выдачи. Статус приходит с кухни сам, без перезагрузки")

        if codes["cancelled"]:
            page.goto(f"{BASE}/order?code={codes['cancelled']}", wait_until="networkidle")
            settle(page, 1600)
            shot(page, "25-order-cancelled", "Гость: заказ отменён",
                 "Отдельный экран с крестиком, составом заказа и кнопкой "
                 "«Заказать заново» — вместо карточки с погасшей шкалой")
        context.close()

        context = new_context(browser, DESKTOP)
        page = context.new_page()
        page.goto(f"{BASE}/e/2/qr?table=5", wait_until="networkidle")
        settle(page, 1600)
        shot(page, "26-qr-poster", "QR-плакат: заведение и столик",
             "Плакат печатается для любой точки и любого столика; метка стола "
             "подставит гостю номер при оформлении")
        context.close()

        # ── Тёмная тема ────────────────────────────────────────────────────
        context = new_context(browser, DESKTOP)
        page = context.new_page()
        page.goto(f"{BASE}/", wait_until="networkidle")
        page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        settle(page, 1900)
        shot(page, "16-dark-home", "Главный экран: тёмная тема",
             "Тот же интерфейс в тёмном оформлении: акцент светлее, фон поверхностей темнее",
             full=True)
        context.close()

        context = new_context(browser, DESKTOP)
        page = context.new_page()
        page.goto(f"{BASE}/e/2/menu", wait_until="networkidle")
        page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        settle(page, 1600)
        shot(page, "17-dark-menu", "Меню: тёмная тема",
             "Карточки блюд в тёмном оформлении", full=True)
        context.close()

        # ── Телефон ────────────────────────────────────────────────────────
        context = new_context(browser, MOBILE, 3)
        page = context.new_page()
        page.goto(f"{BASE}/", wait_until="networkidle")
        settle(page, 1900)
        save(page, OUT / "18-mobile-home.png")
        shots.append({"file": "18-mobile-home.png", "title": "Телефон: главный экран",
                      "note": "Адрес, поиск, баннер и заведения: карточки в одну колонку"})

        page.goto(f"{BASE}/e/2/menu", wait_until="networkidle")
        settle(page, 1500)
        save(page, OUT / "19-mobile-menu.png")
        shots.append({"file": "19-mobile-menu.png", "title": "Телефон: меню",
                      "note": "Блюда в одну колонку с крупным фото"})

        first = page.eval_on_selector(".dish", "n => n.dataset.dish")
        page.click(f'.dish[data-dish="{first}"] button[data-act="more"]')
        page.wait_for_timeout(1400)
        page.click("#cart-open")
        page.wait_for_timeout(1200)
        save(page, OUT / "20-mobile-sheet.png")
        shots.append({"file": "20-mobile-sheet.png", "title": "Телефон: выбор времени",
                      "note": "Шторка поверх меню: корзина остаётся на месте"})

        # Шаг 3: выбираем свободную минуту и открываем оформление — на телефоне
        # его раньше не снимали, а на слайдах нужен ровный ряд из трёх шагов.
        page.click(".slot:not([disabled])")
        page.wait_for_timeout(800)
        page.click("#time-confirm")
        page.wait_for_timeout(1600)
        save(page, OUT / "20b-mobile-checkout.png")
        shots.append({"file": "20b-mobile-checkout.png", "title": "Телефон: оформление заказа",
                      "note": "Имя, телефон и столик: регистрации и пароля нет"})
        context.close()

        context = new_context(browser, MOBILE, 3)
        page = context.new_page()
        login(page, "kitchen-bowl", STAFF_PASSWORD, "/staff")
        save(page, OUT / "21-mobile-kitchen.png")
        shots.append({"file": "21-mobile-kitchen.png", "title": "Телефон: панель кухни",
                      "note": "Очередь смены на телефоне: тот же набор действий"})
        context.close()

        browser.close()

    write_readme(shots)
    print(f"\nготово: {len(shots)} снимков в {OUT}")
    return 0


def write_readme(shots: list[dict[str, str]]) -> None:
    """Галерея кадров: чтобы набор можно было открыть и сразу показать."""
    lines = [
        "# ThreeFast — снимки для презентации",
        "",
        "Сервис предзаказа еды: гость выбирает блюда и минуту выдачи, кухня видит",
        "очередь, заведение ведёт меню и смотрит аналитику, администратор сервиса",
        "заводит новые точки.",
        "",
        f"Всего кадров: {len(shots)}. Собрать заново: `python -m tools.screenshots`.",
        "",
        "---",
        "",
    ]
    for item in shots:
        lines += [
            f"## {item['title']}",
            "",
            item["note"],
            "",
            f"![{item['title']}]({item['file']})",
            "",
        ]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "manifest.json").write_text(
        json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
