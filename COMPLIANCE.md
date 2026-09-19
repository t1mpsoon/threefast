# Соответствие ТЗ: контрольный чек-лист

Документ проверяющему: где в коде реализовано каждое требование ТЗ
и какие решения приняты там, где ТЗ оставляло вопрос открытым.

Дата проверки: 2026-09-19. Среда: Windows, Python 3.14.7, SQLite.

---

## 1. Требования из карточки кейса

| Требование из задания | Статус | Где реализовано | Чем подтверждается |
|---|---|---|---|
| Веб-сайт/сервис предзаказа еды к точному времени | ✅ | `app/routers/public_pages.py`, `app/templates/` | Живой прогон: `smoke_test.py`, раздел «Страницы» |
| Заказ оформляется не более чем за 3 шага | ✅ | Шаги заданы жёстко: меню (1) → шторка времени `partials/sheet_time.html` (2) → шторка оформления `partials/sheet_checkout.html` (3). Отдельных страниц-шагов нет | `test_full_order_flow_via_api`; ручной прогон по разделу 4 README |
| Без обязательной сложной регистрации (логин, пароль, SMS) | ✅ | В клиентском флоу только `guest_name` + `guest_phone`: `app/schemas/order.py` | Регистрация в коде клиента отсутствует полностью; `test_guest_pages_available_without_login` |
| Сокращение ожидания выдачи с 20 до 2 минут | ✅ (механизм + измерение) | Слоты с учётом времени приготовления (`services/slot_service.py`), метрика `average_wait_minutes` (`services/analytics_service.py`) | `test_average_wait_computed_from_slot_time`, `test_wait_target_met_flag` |
| Рост пропускной способности ≥ 25% | ✅ (механизм + измерение) | Настройка `slot_capacity`/`slot_duration_minutes` (Ф-8), метрика `throughput_growth_percent` (Ф-9) | `test_throughput_growth_calculation`, `test_admin_can_update_slot_settings` |
| Технология реализации — Python | ✅ | Весь проект | `requirements.txt` |

---

## 2. Функциональные требования разделов 2.3, 2.8, 2.9

| № | Требование | Реализация |
|---|---|---|
| Ф-1 | Список заведений и меню с фото, рейтингом и загрузкой кухни; 404 для неизвестного заведения; заглушка при пустом меню | `app/routers/places.py`, `menu.py`, `services/place_service.py`, `templates/places.html`, `menu.html`; `test_menu_404_for_unknown_establishment` |
| Ф-2 | Корзина: кнопка «+» превращается в степпер, плавающая панель с суммой и позициями | `app/static/js/cart.js`, `menu.js`; пустой заказ не пропускается дальше |
| Ф-3 | Выбор времени в нижней шторке: слоты капсулами, сгруппированы по получасу, занятые недоступны | `app/routers/slots.py`, `services/slot_service.py`, `js/sheet_time.js`; `test_slots_respect_min_prep_minutes` |
| Ф-4 | Оформление в шторке: имя, телефон, способ оплаты при получении, 409 при гонке, идемпотентность | `app/routers/orders.py`, `services/order_service.py`, `js/sheet_checkout.js`; `test_duplicate_order_via_idempotency_key`, `test_slot_full_returns_409` |
| Ф-5 | Статус заказа по номеру без аккаунта: экран успеха с галочкой и прогресс из 4 сегментов | `GET /api/orders/{code}/status`, `templates/order_status.html`, `partials/progress.html`, `js/order_status.js` |
| Ф-6 | Очередь персонала: строки заказов по времени выдачи, отсчёт, текстовые кнопки перехода | `app/routers/staff.py`, `js/staff_queue.js`; `test_queue_returns_orders_sorted_by_slot`, `test_staff_status_transition_flow` |
| Ф-7 | CRUD меню; блюдо из заказов не удаляется, а скрывается | `app/services/menu_service.py::delete_item`; `test_delete_item_used_in_orders_deactivates_it` |
| Ф-8 | Настройка длительности/вместимости слотов и рабочих часов; существующие брони не отменяются | `PUT /api/staff/settings`, `SlotRepository.update_capacity_for_future`; `test_capacity_change_keeps_existing_bookings` |
| Ф-9 | Аналитика: среднее время ожидания и рост пропускной способности; сообщение при недостатке данных | `app/services/analytics_service.py`, `app/templates/staff/analytics.html`; `test_report_without_data_says_insufficient` |

---

## 3. Бизнес-правила раздела 2.6

| Правило | Реализация | Тест |
|---|---|---|
| А-1 (доступность слотов) | `SlotService.build_slots` | `test_slot_available_when_under_capacity`, `test_slot_unavailable_when_full` |
| А-2 (резервирование в транзакции) | `SlotRepository.try_reserve` — `UPDATE ... WHERE booked_count < capacity` | `test_concurrent_orders_do_not_overbook_slot` (5 потоков, вместимость 1) |
| Б-1 (минимальное время до слота) | `SlotService.validate_slot_choice(min_prep_minutes=MAX(prep_time))` | `test_slot_too_soon_excluded_by_min_prep_time` |
| Б-2 (переходы статусов) | `models/order.py::ALLOWED_TRANSITIONS`, `OrderService.change_status` | `test_invalid_status_transition_rejected`, `test_valid_status_chain_confirmed_to_picked_up` |
| Б-3 (авто-истечение) | `OrderService.expire_stale_orders`, `services/scheduler.py` | `test_order_expires_after_ready_timeout`, `test_fresh_ready_order_not_expired` |
| В-1 (сумма и снапшот цен) | `OrderService.calculate_total`, `OrderItem.item_price_snapshot` | `test_order_total_calculation`, `test_price_snapshot_survives_menu_price_change` |
| Г-1 (сортировка слотов) | `SlotService.build_slots` (сортировка по времени) | `test_slots_sorted_by_time` |

---

## 4. Definition of Done (раздел 2.18)

| Пункт | Статус | Подтверждение |
|---|---|---|
| Флоу ровно в 3 шага, без логина/пароля/SMS | ✅ | Разделы 4 и 5 README; `smoke_test.py` |
| Слоты учитывают вместимость и время приготовления | ✅ | `tests/test_slot_service.py` |
| Заказ нельзя создать поверх заполненного слота (проверено конкурентно) | ✅ | `tests/test_concurrency.py` — 1 заказ из 5 одновременных на слот вместимостью 1 |
| Повторная отправка формы не создаёт дубль | ✅ | `test_duplicate_order_via_idempotency_key`, `test_concurrent_same_idempotency_key_creates_single_order` |
| Панель персонала: валидные переходы разрешены, невалидные отклоняются | ✅ | `tests/test_staff_api.py` |
| Дашборд показывает среднее ожидание и % роста | ✅ | `tests/test_analytics.py` |
| Некорректный ввод обрабатывается без падения | ✅ | `tests/test_orders_api.py` (negative-блок) |
| Traceback не показывается пользователю | ✅ | `test_error_page_has_no_traceback`, глобальные обработчики в `app/main.py` |
| Секреты только в `.env`, не в коде | ✅ | `test_source_files_have_no_hardcoded_secret`, `.gitignore` |
| Запуск с чистого окружения по инструкции | ✅ | Раздел 3 README; проверено на новом venv |
| README с инструкцией и тестовыми учётными данными | ✅ | `README.md`, раздел 3 |
| Тесты написаны и проходят | ✅ | **135 тестов, все проходят** (`pytest tests -q`) |

---

## 5. Раздел 5 ТЗ: план тестирования — все пункты

| Тест из ТЗ | Файл | Статус |
|---|---|---|
| `test_slot_available_when_under_capacity` | `tests/test_slot_service.py` | ✅ |
| `test_slot_unavailable_when_full` | `tests/test_slot_service.py` | ✅ |
| `test_order_total_calculation` | `tests/test_order_service.py` | ✅ |
| `test_invalid_status_transition_rejected` | `tests/test_order_service.py` | ✅ |
| `test_create_order_reduces_slot_capacity` | `tests/test_order_service.py` | ✅ |
| `test_second_order_on_full_slot_rejected` | `tests/test_order_service.py` | ✅ |
| `test_full_order_flow_via_api` | `tests/test_orders_api.py` | ✅ |
| `test_staff_status_transition_flow` | `tests/test_staff_api.py` | ✅ |
| `test_create_order_with_invalid_phone` | `tests/test_orders_api.py` | ✅ |
| `test_create_order_with_empty_cart` | `tests/test_orders_api.py` | ✅ |
| `test_unauthorized_staff_access` | `tests/test_staff_api.py` | ✅ |
| `test_duplicate_order_via_idempotency_key` | `tests/test_orders_api.py` | ✅ |
| `test_order_expires_after_ready_timeout` | `tests/test_order_service.py` | ✅ |
| `test_concurrent_status_update_conflict` | `tests/test_staff_api.py` | ✅ |

---

## 6. Отклонения от ТЗ и их обоснование

### 6.1. `passlib[bcrypt]` → `bcrypt` (раздел 2.16)

ТЗ само помечало версии как `[ТРЕБУЕТ ПРОВЕРКИ]`. Проверка на Python 3.14 показала,
что `passlib` 1.7.4 неработоспособен:

```
(trapped) error reading bcrypt version
AttributeError: module 'bcrypt' has no attribute '__about__'
ValueError: password cannot be longer than 72 bytes...
```

Причина: passlib обращается к `bcrypt.__about__`, удалённому в bcrypt 4.x, а его
pure-python backend несовместим с Python 3.11+. Функциональность сохранена полностью —
`bcrypt` используется напрямую в `app/security.py` (хэширование + проверка).

### 6.2. Версии зависимостей не пинованы жёстко

ТЗ просило проверить актуальные совместимые версии. `requirements.txt` использует
нижние границы (`fastapi>=0.115` и т.д.), фактически проверены:
fastapi 0.141.1, pydantic 2.13.5, sqlalchemy 2.0.54, bcrypt 5.0.0, alembic 1.20.0.
Для продакшн-развёртывания версии имеет смысл зафиксировать (`pip freeze`).

### 6.3. Дополнительные решения там, где ТЗ помечало `[ПРЕДЛОЖЕНИЕ]`

| Вопрос из ТЗ | Принятое решение |
|---|---|
| Способ оплаты | Оба варианта — «наличными при получении» и «картой при получении»: платёжный шлюз не подключён по разделу 2.19, оплата идёт на кассе |
| Количество заведений | Витрина поддерживает несколько заведений: в начальных данных три точки с фото, кухней и рейтингом (`app/init_db.py::PLACES`) |
| Идентификация при выдаче | Короткий номер `EX-XXXX` из алфавита без похожих символов (исключены 0/O, 1/I/L, 2/Z, 5/S, 8/B) |
| Хранение корзины | Клиентское (localStorage) — заказ в БД не создаётся до подтверждения, как и требует Ф-2 |
| Авто-истечение заказа | 20 минут настраиваются через `ORDER_EXPIRE_AFTER_READY_MINUTES` |
| Rate limiting | Реализован: не более 5 заказов с одного IP в минуту, плюс отдельный лимит на подбор кода заказа — 12 неудачных попыток за 5 минут (`app/utils/rate_limit.py`) |
| Администратор сервиса | Не относится ни к одному заведению: колонка `establishment_id` необязательна (миграция `0005_superadmin_no_place`), его экран — список заведений |
| Фото блюд и заведений | ТЗ не упоминает фото, но витрина без них не работает: поля `photo`, `description`, `cuisine`, `rating` добавлены миграцией `0002_showcase`, файлы лежат локально в `app/static/img` |

### 6.4. Что добавлено сверх ТЗ (без усложнения)

- **Страница ошибок** (`error.html`) вместо голого JSON для браузерных запросов.
- **Отмена заказа гостем** по номеру (`POST /api/orders/{code}/cancel`) — закрывает
  ветку `confirmed → cancelled` из правила Б-2 со стороны гостя.
- **Витрина из нескольких заведений** с загрузкой кухни и временем до готовности
  (`services/place_service.py`) — главный экран вместо редиректа на одно кафе.
- **Микро-интеракции клиентского флоу**: скелетоны, пружина степпера, плашка «+1»,
  нижние шторки со свайпом — брифинг по дизайну, не ТЗ.
- **Автоматическая проверка отсутствия дрейфа схемы** (`tools/check_migrations.py`).
- **`smoke_test.py`** — сквозная проверка живого приложения по HTTP.

## 7. Результаты прогонов

| Проверка | Команда | Результат |
|---|---|---|
| Автотесты | `python -m pytest tests -q` | **135 passed** за ~29 сек |
| Сквозной сценарий | `python smoke_test.py` | **все проверки пройдены** |
| Миграции | `python check_migrations.py` | «Дрейфа схемы нет: миграции и модели совпадают» |
| Живой сервер | `uvicorn app.main:app --port 8010` | полный флоу 3 шагов, смена статусов, аналитика — успешно |
| Логирование | `logs/app.log` | записи создаются, телефон маскируется (`7701***67`), секретов нет |
| Идемпотентность БД | `python -m app.init_db` дважды | повторный запуск не создаёт дублей (1 заведение, 11 блюд, 2 пользователя) |

---

## 8. Что осталось за рамками (осознанно)

Перечислено в разделе 11 README: реальный платёжный шлюз, нативное мобильное
приложение, SMS/push-рассылки, PostgreSQL/Redis/очереди, i18n, ML-прогнозы.
Все пункты либо прямо исключены разделом 2.19 ТЗ, либо требовали бы внешних
сервисов, не указанных в задании.
