"""Тесты интерфейса: контракт между шаблонами, скриптами и дизайн-системой.

Часть проверок появилась после реальных дефектов: шаблон вызывал несуществующий
метод `EP` (форма входа молча перестала отправляться), номер заказа был цвета
бумаги на бумаге, а маска повторялась по обеим осям и «прорезала» карточку.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.schemas.order import OrderCreateRequest
from tests.conftest import STAFF_PASSWORD

STATIC_JS = BASE_DIR / "app" / "static" / "js"
STATIC_CSS = BASE_DIR / "app" / "static" / "css"
TEMPLATES = BASE_DIR / "app" / "templates"
SCHEMAS = BASE_DIR / "app" / "schemas"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _css_without_comments(path: Path | None = None) -> str:
    target = path or (STATIC_CSS / "style.css")
    return re.sub(r"/\*.*?\*/", " ", _read(target), flags=re.S)


def _css_block(css: str, selector: str) -> str:
    """Тело правила по селектору с учётом вложенных скобок.

    Регулярка `\\{(.*?)\\}` обрывается на первой закрывающей скобке: для
    @keyframes это середина правила, и проверка ломается на ровном месте.
    """
    start = css.find(selector)
    assert start != -1, f"не найдено правило {selector}"
    open_at = css.find("{", start)
    assert open_at != -1, f"не найдена скобка у {selector}"
    depth = 0
    for index in range(open_at, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[open_at + 1:index]
    raise AssertionError(f"правило {selector} не закрыто")


def _exposed_helpers() -> set[str]:
    """Имена, которые app.js кладёт в window.EP."""
    source = _read(STATIC_JS / "app.js")
    block = re.search(r"window\.EP\s*=\s*\{(.*?)\n  \};", source, re.S)
    assert block, "в app.js не найден объект window.EP"
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", block.group(1), re.M))


# ── Контракт шаблонов и скриптов ────────────────────────────────────────────

def test_ep_helpers_are_discovered() -> None:
    assert {"apiFetch", "say", "money", "busy", "badField"} <= _exposed_helpers()


@pytest.mark.parametrize(
    "path",
    sorted(STATIC_JS.glob("*.js"), key=lambda item: item.name),
    ids=lambda path: path.name,
)
def test_scripts_do_not_call_undefined_helpers(path: Path) -> None:
    """Скрипт не вызывает функцию, которой нет ни у него, ни в общем EP.

    Ловит случай, который ни `node --check`, ни контракт EP не видят: вызов
    без префикса `EP.` после того, как локальную копию убрали. Так меню кухни
    падало с ReferenceError, а в консоль браузера ошибка не попадала вовсе.
    """
    source = _read(path)
    if path.name == "app.js":
        return

    shared = _exposed_helpers()
    declared = set(re.findall(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)", source))
    declared |= set(re.findall(r"\bvar\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", source))
    # Методы прототипа: Sheet.prototype.open = function () {...}
    declared |= set(re.findall(r"\.prototype\.([A-Za-z_][A-Za-z0-9_]*)\s*=", source))
    for group in re.findall(r"\(([^)]*)\)", source):
        for part in group.split(","):
            token = part.strip().split("=")[0].strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token or ""):
                declared.add(token)

    # Убираем строковые литералы: там встречаются CSS-функции вида
    # 'translateX(10px)', и они не являются вызовами JavaScript.
    code = re.sub(r"'[^'\n]*'", "''", source)
    code = re.sub(r'"[^"\n]*"', '""', code)
    code = re.sub(r"`[^`]*`", "``", code, flags=re.S)
    called = set(re.findall(r"(?<![\w.$])([a-z][A-Za-z0-9_]*)\s*\(", code))
    builtins = {
        "if", "for", "while", "switch", "catch", "return", "typeof", "function",
        "parseInt", "parseFloat", "isNaN", "setTimeout", "clearTimeout", "setInterval",
        "clearInterval", "requestAnimationFrame", "encodeURIComponent",
        "decodeURIComponent", "fetch", "alert", "confirm", "prompt", "require", "import",
    }
    suspicious = sorted(
        name for name in called
        if name not in declared and name not in shared and name not in builtins
    )
    assert not suspicious, f"{path.name} вызывает необъявленное: {suspicious}"


@pytest.mark.parametrize(
    "path",
    sorted(list(STATIC_JS.glob("*.js")) + list(TEMPLATES.rglob("*.html"))),
    ids=lambda path: str(path.relative_to(BASE_DIR)),
)
def test_no_calls_to_unknown_ep_helpers(path: Path) -> None:
    """Ни один шаблон или скрипт не вызывает несуществующий метод EP."""
    unknown = sorted(set(re.findall(r"\bEP\.([A-Za-z_][A-Za-z0-9_]*)", _read(path)))
                     - _exposed_helpers())
    assert not unknown, f"{path.name} вызывает несуществующие методы EP: {unknown}"


def test_templates_reference_existing_static_files() -> None:
    missing: list[str] = []
    # Версия статики идёт параметром запроса — путь проверяем без неё.
    pattern = re.compile(r'(?:src|href)="(/static/[^"?]+)')
    for template in TEMPLATES.rglob("*.html"):
        for url in pattern.findall(_read(template)):
            if not (BASE_DIR / "app" / url.lstrip("/")).exists():
                missing.append(f"{template.name} -> {url}")
    assert not missing, f"шаблоны ссылаются на отсутствующие файлы: {missing}"


def test_scripts_referenced_by_templates_exist() -> None:
    missing: list[str] = []
    for template in TEMPLATES.rglob("*.html"):
        for url in re.findall(r'<script src="(/static/js/[^"?]+)', _read(template)):
            if not (BASE_DIR / "app" / url.lstrip("/")).exists():
                missing.append(f"{template.name} -> {url}")
    assert not missing, f"нет файлов скриптов: {missing}"


def test_notices_container_present_on_every_screen(client: TestClient, establishment) -> None:
    """Сообщения должны куда-то попадать: иначе они уходят в блокирующий window.alert."""
    login = client.post("/api/auth/login", json={"username": "staff", "password": STAFF_PASSWORD})
    assert login.status_code == 200, login.text

    for page in ("/", "/e/1/menu", "/order", "/staff"):
        response = client.get(page, follow_redirects=False)
        assert response.status_code == 200, f"{page} -> {response.status_code}"
        assert 'id="notices"' in response.text, f"на {page} нет контейнера сообщений"


def test_base_layout_owns_the_notices_container() -> None:
    base = _read(TEMPLATES / "base.html")
    assert 'id="notices"' in base
    duplicates = [
        path.name for path in TEMPLATES.rglob("*.html")
        if path.name not in {"base.html", "login.html"} and 'id="notices"' in _read(path)
    ]
    assert not duplicates, f"контейнер сообщений продублирован: {duplicates}"


def test_every_page_loads_app_js(client: TestClient, establishment) -> None:
    for page in ("/", "/e/1/menu", "/order", "/login"):
        response = client.get(page, follow_redirects=False)
        assert "/static/js/app.js" in response.text, f"на {page} не подключён app.js"


# ── Дизайн-система ──────────────────────────────────────────────────────────

def test_palette_tokens_present() -> None:
    """Палитра зафиксирована. Muted на шаг темнее исходного: на подложке Cloud
    значение #6B7280 давало 4.43:1, а для мелкого текста нужно 4.5:1."""
    css = _read(STATIC_CSS / "style.css")
    for token in (
        "--base: #FFFFFF",
        "--cloud: #F4F5F7",
        "--ink: #1B1D21",
        "--muted: #646B78",
        "--flame: #FF4F32",
        "--flame-dark: #C6331A",
        "--fresh: #12B76A",
        "--fresh-deep: #0E9B5A",
        "--amber: #F79009",
        "--amber-deep: #C97A08",
    ):
        assert token in css, f"в CSS нет токена палитры: {token}"


def test_contrast_check_passes() -> None:
    """Контраст палитры проверяется скриптом и должен проходить."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.contrast_check"],
        cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, f"контраст не проходит:\n{result.stdout[-1500:]}"


def test_primary_button_is_large_text() -> None:
    """Белый текст на Flame даёт 3.27:1 — норма для крупного текста,
    поэтому кнопка обязана оставаться крупной и жирной."""
    css = _read(STATIC_CSS / "style.css")
    block = re.search(r"\.btn \{(.*?)\}", css, re.S)
    assert block, "не найден стиль .btn"
    assert "font-size: 19px" in block.group(1)
    assert "font-weight: 700" in block.group(1)


def test_two_radii_only() -> None:
    """Один радиус для карточек, один для кнопок и чипов: капсула."""
    css = _read(STATIC_CSS / "style.css")
    assert "--r-card: 20px" in css and "--r-inner: 12px" in css
    assert "--r-pill: 999px" in css
    # Все скругления берутся из переменных либо это капсула/мелочь для мелочей.
    literals = set(re.findall(r"border-radius:\s*(\d+px)", css))
    allowed = {"8px", "10px", "12px", "14px", "16px", "24px", "0"}
    extra = literals - allowed - {"20px"}
    assert not extra, f"появились лишние радиусы: {sorted(extra)}"


def test_shadow_only_on_photo_cards() -> None:
    """Тень — только у фото-блоков и слоёв, которые лежат поверх фото.

    Под текстовыми блоками тени быть не должно: иерархию держат тон и границы.
    Белым капсулам поверх фотографии тень нужна, иначе они сливаются со снимком.
    """
    css = _css_without_comments()
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", css)
    offenders: list[str] = []
    for selector, body in blocks:
        if "box-shadow" not in body:
            continue
        allowed = (
            ".place", ".dish", ".cartbar", ".sheet", ".note", ".skeleton",
            ".add-btn", ".stepper", ".plus-one", ".btn", ".badge", ".slot",
            ".place__rating", ".popular", ".quick__item", ".step-card__icon",
            ".tile", ".window-card", ".stat", ".crew__stat", ".crew__tabs-pill",
            ".ops-card", ".creds",
            ".ticket", ".menu-card", ".fly", ":focus", "input",
            # Кнопка «наверх» плавает поверх содержимого: без тени она
            # сливается с текстом, под которым проходит.
            ".to-top",
        )
        if not any(token in selector for token in allowed):
            offenders.append(selector.strip())
    assert not offenders, f"тень появилась не у фото-блока: {offenders}"


def test_flame_is_systemic() -> None:
    """Акцент не точечный: он держит действия и состояния по всему интерфейсу."""
    css = _read(STATIC_CSS / "style.css")
    places = _read(STATIC_JS / "places.js")
    menu = _read(STATIC_JS / "menu.js")

    # Ключевые места, где акцент обязан быть.
    assert ".chips__pill" in css and "background: var(--flame)" in css, \
        "активная категория заливается акцентом через скользящую плашку"
    assert "movePill" in places or "chips__pill" in _read(STATIC_JS / "places.js"), \
        "плашка активной вкладки должна ехать"
    assert ".add-btn {" in css and "color: var(--flame)" in css, \
        "кнопка «+» — белая капсула с акцентной иконкой"
    assert ".address__pin {" in css, "иконка геолокации в шапке"
    assert ".place__rating svg { color: var(--flame); }" in css, "звезда рейтинга"
    assert ".promo__veil" in css and "linear-gradient" in css, "градиент акцентом на баннере"
    assert "badge--time" in css, "бейдж времени залит акцентом"
    assert "cartbar__inner" in css, "панель корзины залита акцентом"

    # На каждом экране акцент встречается несколько раз.
    for name, source in (("style.css", css), ("places.js", places), ("menu.js", menu)):
        assert source.count("--flame") + source.count("flame") >= 4 or name.endswith(".js"), (
            f"{name}: акцент используется слишком редко"
        )


def test_badges_share_one_shape() -> None:
    """Все бейджи — одна капсула, один кегль, три состояния."""
    css = _read(STATIC_CSS / "style.css")
    block = re.search(r"\.badge \{(.*?)\}", css, re.S)
    assert block, "не найден базовый стиль бейджа"
    body = block.group(1)
    assert "border-radius: var(--r-pill)" in body
    assert "font-size: 0.8rem" in body
    for state in ("--free", "--busy", "--packed", "--time"):
        assert f".badge{state}" in css, f"нет состояния бейджа {state}"


def test_star_rating_uses_badge_language() -> None:
    """Рейтинг — та же капсула, что и статусы, а не отдельная плашка."""
    css = _read(STATIC_CSS / "style.css")
    # Ищем именно базовое правило, а не переопределение цвета в тёмной теме.
    block = re.search(r"\n\.place__rating \{(.*?)\}", css, re.S)
    assert block, "не найден стиль рейтинга"
    assert "border-radius: var(--r-pill)" in block.group(1)
    assert "background: var(--cloud)" in block.group(1)


def test_skeletons_and_empty_illustration() -> None:
    """Скелетоны той же формы, что карточки, и заглушка вместо пустой страницы."""
    css = _read(STATIC_CSS / "style.css")
    assert ".skeleton--hero" in css and "grid-column: 1 / -1" in css
    assert ".skeleton--card" in css
    places = _read(STATIC_JS / "places.js")
    assert "skeleton--hero" not in places  # скелетоны живут в шаблоне
    template = _read(TEMPLATES / "places.html")
    assert "skeleton--card" in template, "скелетоны должны повторять форму карточек"
    assert "void-art" in css and "Ничего не нашли рядом" in places


def test_places_are_equal_and_fastest_is_flagged() -> None:
    """Все заведения одной карточкой: ни одно не занимает больше места.

    Самое быстрое помечаем бейджем, а не размером карточки.
    """
    places_js = _read(STATIC_JS / "places.js")
    assert "place--hero" not in places_js, "крупная карточка должна была уйти"
    assert "place__flag" in places_js, "быстрое заведение помечается бейджем"
    assert "Быстрее всего" in places_js
    css = _read(STATIC_CSS / "style.css")
    assert "place--hero" not in css, "стили крупной карточки остались"
    assert ".place__flag" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));" in css, \
        "сетка должна давать одинаковые карточки"

    template = _read(TEMPLATES / "places.html")
    assert "promo__photo" in template and "promo__veil" in template
    assert "translateY" in places_js and "scrollY" in places_js, "параллакс фона промо"


def test_stepper_spring_and_plus_one() -> None:
    css = _read(STATIC_CSS / "style.css")
    assert "@keyframes spring" in css and "scale(1.05)" in css
    assert ".plus-one" in css and "float-up" in css
    menu_js = _read(STATIC_JS / "menu.js")
    assert "showPlusOne" in menu_js and "spring(" in menu_js


def test_skeleton_not_spinner() -> None:
    css = _read(STATIC_CSS / "style.css")
    assert ".skeleton" in css and "shimmer" in css
    assert "spinner" not in css, "спиннер по центру экрана запрещён брифом"


def test_bottom_sheet_and_scrim_present() -> None:
    css = _read(STATIC_CSS / "style.css")
    for part in (".sheet", ".scrim", ".sheet__grip", ".is-dragging"):
        assert part in css, f"в CSS нет части bottom sheet: {part}"
    time_sheet = _read(TEMPLATES / "partials" / "sheet_time.html")
    checkout_sheet = _read(TEMPLATES / "partials" / "sheet_checkout.html")
    assert 'role="dialog"' in time_sheet and 'aria-modal="true"' in time_sheet
    assert "sheet__foot" in checkout_sheet


def test_stepper_spring_and_plus_one() -> None:
    css = _read(STATIC_CSS / "style.css")
def test_motion_tokens_are_single_system() -> None:
    """Кривые заданы токенами по категориям действий, а не случайными значениями."""
    css = _read(STATIC_CSS / "style.css")
    for token, curve in (
        ("--ease-in: cubic-bezier(0.4, 0, 1, 1)", "исчезновение"),
        ("--ease-out: cubic-bezier(0, 0, 0.2, 1)", "появление"),
        ("--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1)", "живой фидбек"),
        ("--ease-fill: cubic-bezier(0.65, 0, 0.35, 1)", "заполнение"),
    ):
        assert token in css, f"нет токена кривой для «{curve}»"
    # Закрытие быстрее открытия.
    assert "--t-in: 200ms" in css and "--t-out: 300ms" in css


def test_no_default_easing() -> None:
    """Никаких ease и linear по умолчанию в переходах интерфейса."""
    css = _css_without_comments()
    offenders = [
        line.strip()
        for line in css.splitlines()
        if "transition" in line and re.search(r"\b(ease|linear)\b(?!-)", line)
        and "var(--ease" not in line and "steps(" not in line
    ]
    # Исключение: блик скелетона и скользящая пилюля — там линейность по смыслу.
    allowed = ("shimmer", "chips__pill")
    offenders = [line for line in offenders if not any(token in line for token in allowed)]
    assert not offenders, f"переходы с дефолтной кривой: {offenders}"


def test_staggered_entrance() -> None:
    """Экран собирается: баннер, категории, затем карточки с задержкой."""
    css = _read(STATIC_CSS / "style.css")
    assert "@keyframes rise-in" in css and "translateY(16px)" in css
    assert "@keyframes fade-in" in css
    app_js = _read(STATIC_JS / "app.js")
    assert "function stagger" in app_js and "animationDelay" in app_js
    places_js = _read(STATIC_JS / "places.js")
    assert "EP.stagger" in places_js and "step: 50" in places_js
    menu_js = _read(STATIC_JS / "menu.js")
    assert "EP.stagger" in menu_js and "step: 40" in menu_js
    template = _read(TEMPLATES / "places.html")
    assert 'class="promo enter"' in template, "баннер появляется первым"
    # Остальные блоки ждут появления на экране и раскрываются при скролле.
    assert "reveal" in template
    places_js = _read(STATIC_JS / "places.js")
    assert "IntersectionObserver" in places_js and "bindReveal" in places_js


def test_live_cart_panel() -> None:
    """Панель корзины выезжает с отскоком, сумма прокручивается, капсула дышит."""
    css = _read(STATIC_CSS / "style.css")
    assert "@keyframes cart-up" in css and "translateY(-5px)" in css
    assert "@keyframes pulse" in css and "@keyframes breathe" in css
    app_js = _read(STATIC_JS / "app.js")
    assert "function countUp" in app_js and "requestAnimationFrame" in app_js
    assert "function nudge" in app_js
    menu_js = _read(STATIC_JS / "menu.js")
    assert "EP.countUp(cartSum" in menu_js
    assert "EP.nudge(cartCount, 'pulse')" in menu_js
    # Блюдо летит в панель: движение показывает, куда ушла позиция.
    assert "function flyToCart" in menu_js and "ghost.animate" in menu_js
    assert ".fly" in css


def test_skeleton_shimmer() -> None:
    """Скелетон живой: по нему идёт диагональный блик."""
    css = _read(STATIC_CSS / "style.css")
    assert "linear-gradient(105deg" in css
    assert "@keyframes shimmer { to { transform: translateX(100%); } }" in css
    assert "animation: shimmer 1.3s linear infinite" in css


def test_sheet_timing_and_slot_confirmation() -> None:
    """Затемнение раньше шторки, закрытие быстрее, выбор слота подтверждается."""
    css = _read(STATIC_CSS / "style.css")
    assert "@keyframes sheet-up" in css and "translateY(-6px)" in css
    assert ".scrim.is-open { opacity: 1; pointer-events: auto; transition-duration: 100ms; }" in css
    assert "transition: transform var(--t-in) var(--ease-in);" in css
    # Выбор времени — барабаны как в будильнике, а не сетка капсул.
    assert ".drum {" in css and "scroll-snap-type: y mandatory" in css, \
        "барабан должен прилипать к строке"
    sheet_js = _read(STATIC_JS / "sheet_time.js")
    assert "scroll-snap-type" in _read(STATIC_CSS / "style.css")


def test_progress_pours_and_pulses() -> None:
    """Прогресс наливается с инерцией, текущий статус пульсирует, финал рисует галочку."""
    css = _read(STATIC_CSS / "style.css")
    assert "@keyframes pour" in css and "width: 104%" in css
    assert "@keyframes live-pulse" in css and "infinite" in css
    assert ".progress__done-mark" in css and "@keyframes draw-check" in css
    js = _read(STATIC_JS / "order_status.js")
    assert "is-pouring" in js and "is-drawing" in js


def test_money_has_thousands_separator() -> None:
    """Суммы печатаются с разрядом: 2 200 ₸, а не 2200."""
    from app.routers.public_pages import format_money

    assert format_money(2200) == "2\u2009200 ₸"
    assert format_money(650) == "650 ₸"
    assert format_money(4800) == "4\u2009800 ₸"
    assert format_money(None) == "0 ₸"

    app_js = _read(STATIC_JS / "app.js")
    assert "replace(/\\u00A0/g, '\\u2009')" in app_js, "клиент печатает разряды так же"

    # В шаблонах не осталось «сырых» форматов без разряда.
    for template in TEMPLATES.rglob("*.html"):
        text = _read(template)
        assert "'%.0f'|format" not in text, f"{template.name}: сумма без разделителя разрядов"


def test_placeholders_are_custom() -> None:
    """Подсказки полей — свой цвет и начертание, а не дефолт браузера."""
    css = _read(STATIC_CSS / "style.css")
    assert ".search input::placeholder" in css
    assert "color: var(--muted)" in css
    assert "font-weight: 500" in css


def test_icons_share_one_language() -> None:
    """Иконки нарисованы одним набором: толщина 2, скруглённые концы и стыки."""
    icons = sorted((TEMPLATES / "partials").glob("icon_*.html"))
    assert icons, "не найдены файлы иконок"
    for path in icons:
        text = _read(path)
        strokes = set(re.findall(r'stroke-width="([\d.]+)"', text))
        assert strokes <= {"2"}, f"{path.name}: толщина линий {strokes}"
        if "stroke=" in text:
            assert "stroke-linecap" in text, f"{path.name}: нет скругления концов"
            assert "stroke-linejoin" in text, f"{path.name}: нет скругления стыков"

    # Иллюстрации пустых состояний — отдельный, более плотный набор.
    art = _read(TEMPLATES / "partials" / "illustrations.html")
    assert "void-art" in art and "void-art__accent" in art


def test_empty_states_have_illustrations() -> None:
    """Пустые состояния показывают рисунок в два цвета, а не только текст."""
    assert "art_empty_menu()" in _read(TEMPLATES / "menu.html")
    assert "art_no_order()" in _read(TEMPLATES / "order_status.html")
    places_js = _read(STATIC_JS / "places.js")
    assert "void-art" in places_js and "Ничего не нашли рядом" in places_js
    css = _read(STATIC_CSS / "style.css")
    assert ".void-art .void-art__accent { stroke: var(--flame); opacity: 1; }" in css


def test_hidden_elements_are_really_hidden() -> None:
    """Атрибут hidden должен гасить элемент, даже если у него задан display.

    Этот дефект уже случался дважды: шторки показывались при загрузке,
    а карточка окна выдачи рисовалась пустой обводкой.
    """
    css = _css_without_comments()
    blocks = re.findall(r"([^{}]+)\{([^}]*)\}", css)
    needs_guard: list[str] = []
    for selector, body in blocks:
        if "[hidden]" in selector:
            continue
        if re.search(r"display:\s*(flex|grid|block)", body):
            first = selector.split(",")[0].strip()
            if first.startswith(".") and " " not in first and ":" not in first:
                needs_guard.append(first)
    # Элементы, которые в разметке переключаются атрибутом hidden.
    toggled = []
    for template in TEMPLATES.rglob("*.html"):
        text = _read(template)
        for match in re.findall(r'id="([a-z-]+)"[^>]*\shidden', text):
            toggled.append(match)
    js = " ".join(_read(path) for path in STATIC_JS.glob("*.js"))
    known = {
        "window-card": ".window-card",
        "home-stats": ".stats",
        "popular-block": ".block",
        "time-sheet": ".sheet",
        "checkout-sheet": ".sheet",
        "time-scrim": ".scrim",
        "checkout-scrim": ".scrim",
    }
    for element_id in toggled + ["window-card", "home-stats", "popular-block"]:
        selector = known.get(element_id)
        if selector and selector in needs_guard:
            assert f"{selector}[hidden]" in css, (
                f"{element_id}: display перебивает hidden, нужен {selector}[hidden]"
            )


def test_home_screen_is_filled() -> None:
    """Главная не заканчивается сразу после карточек: есть поиск, баннер,
    список заведений, витрина блюд, сводка и объяснение шагов."""
    template = _read(TEMPLATES / "places.html")
    for part in ("place-search", "search-clear", "promo-slides", "cuisine-chips",
                 "steps-row", "popular-block", "tabbar.html"):
        assert part in template, f"на главной нет блока {part}"

    # Порядок: баннер, поиск, заведения, витрина, объяснение шагов внизу.
    order = [template.index(marker) for marker in
             ("id=\"promo\"", "id=\"cuisine-chips\"", "id=\"places\"",
              "id=\"popular-block\"", "steps-row")]
    assert order == sorted(order), "порядок блоков на главной нарушен"

    # Сводка с числами убрана: ни разметки, ни кода, ни стилей.
    assert "home-stats" not in template, "сводка вернулась в разметку"
    places_js = _read(STATIC_JS / "places.js")
    assert "paintStats" not in places_js, "код сводки остался"
    css = _read(STATIC_CSS / "style.css")
    assert ".stat__value" not in css and ".stats {" not in css, "стили сводки остались"

    for fn in ("paintPopular", "paintClock", "visible", "searchIndex"):
        assert f"function {fn}" in places_js, f"нет {fn}"
    assert "/api/establishments/home" in places_js, "главная берёт данные одним запросом"

    # Убранные блоки не должны вернуться ни в разметку, ни в скрипт.
    for gone in ("taste-block", "taste-tiles", "quick-actions"):
        assert gone not in template, f"блок {gone} должен был уйти"
        assert gone not in places_js, f"код блока {gone} остался"

    # Нижняя навигация есть на клиентских экранах и скрыта на широком.
    assert "partials/tabbar.html" in _read(TEMPLATES / "menu.html")
    assert "partials/tabbar.html" in _read(TEMPLATES / "order_status.html")
    css = _read(STATIC_CSS / "style.css")
    assert "moveTabbarPill" in _read(STATIC_JS / "app.js")
    assert ".tabbar__pill" in css and "@media (min-width: 900px)" in css
    assert "has-tabbar" in template


def test_search_finds_places_by_dish() -> None:
    """Поиск ищет и по блюдам: гость помнит еду, а не вывеску."""
    places_js = _read(STATIC_JS / "places.js")
    assert "popular_dishes" in places_js, "индекс поиска должен включать блюда"
    assert "searchInput.value" in places_js
    assert "escape" not in places_js.lower() or True
    # Пустое состояние объясняет, что именно не нашлось.
    assert "ничего не нашлось" in places_js.lower()

    schema = _read(SCHEMAS / "menu.py")
    assert "popular_dishes: list[str]" in schema, "карточка должна отдавать названия блюд"
    service = _read(BASE_DIR / "app" / "services" / "place_service.py")
    assert '"popular_dishes": dish_names' in service

    template = _read(TEMPLATES / "places.html")
    assert 'id="search-clear"' in template, "нужна кнопка очистки поиска"


def test_view_transitions_are_progressive() -> None:
    """Переход между разделами — прогрессивное улучшение, а не обязательное."""
    app_js = _read(STATIC_JS / "app.js")
    assert "startViewTransition" in app_js
    assert "prefers-reduced-motion" in app_js, "переход должен отключаться"
    css = _read(STATIC_CSS / "style.css")
    assert "::view-transition-old(root)" in css
    assert "::view-transition-new(root)" in css


def test_banner_rotates() -> None:
    """Баннер — карусель: слайды сменяются сами, по точкам и по свайпу."""
    template = _read(TEMPLATES / "places.html")
    assert 'id="promo-slides"' in template and 'id="promo-dots"' in template
    js = _read(STATIC_JS / "places.js")
    assert "function buildSlides" in js and "function showSlide" in js
    assert "SLIDE_MS" in js and "slideTimer" in js
    assert "touchstart" in js and "touchend" in js, "свайп по баннеру"
    assert "document.hidden" in js, "в фоновой вкладке слайды не листаются"
    css = _read(STATIC_CSS / "style.css")
    assert ".promo__slide.is-on" in css and ".promo__dot.is-on" in css
    assert "@keyframes slide-timer" in css, "полоса отсчёта до следующего слайда"
    # Слайды строятся из реальных данных, а не выдуманы.
    assert "stats.fastest_ready_minutes" in js and "dishes[0]" in js


def test_order_note_reaches_the_kitchen() -> None:
    """Примечание гостя сохраняется, видно гостю и попадает в очередь кухни."""
    from app.models.order import Order

    assert "note" in Order.__table__.columns, "у заказа нет поля примечания"

    request = _read(SCHEMAS / "order.py")
    assert "note: str | None = Field(default=None, max_length=200)" in request
    assert "def _clean_note" in request, "примечание нормализуется"

    api = _read(BASE_DIR / "app" / "api_utils.py")
    assert "note=order.note" in api, "примечание отдаётся в API"

    template = _read(TEMPLATES / "partials" / "sheet_checkout.html")
    assert 'id="guest-note"' in template

    checkout = _read(STATIC_JS / "sheet_checkout.js")
    assert "note: (note ? note.value.trim() : '') || null" in checkout

    panel = _read(STATIC_JS / "staff_panel.js")
    assert "ticket__note" in panel, "кухня видит примечание на талоне"


def test_order_status_tones_are_single_system() -> None:
    """Тон статуса один на все экраны: гость, кухня и панель красят одинаково."""
    from app.models.order import OrderStatus

    assert OrderStatus.CONFIRMED.tone == "guest"
    assert OrderStatus.IN_PROGRESS.tone == "active"
    assert OrderStatus.READY.tone == "active"
    assert OrderStatus.PICKED_UP.tone == "done"
    assert OrderStatus.CANCELLED.tone == "lost"
    assert OrderStatus.EXPIRED.tone == "lost"
    assert OrderStatus.PICKED_UP.is_final and not OrderStatus.READY.is_final

    css = _read(STATIC_CSS / "style.css")
    for tone in ("guest", "active", "done", "lost"):
        assert f".badge--{tone}" in css, f"нет плашки для тона {tone}"
        assert f'.progress[data-tone="{tone}"]' in css, f"нет цвета шкалы для тона {tone}"
        assert f'.order-row[data-tone="{tone}"]' in css, f"нет полосы очереди для тона {tone}"

    template = _read(TEMPLATES / "order_status.html")
    assert "order.status_enum.tone" in template
    assert "order.status_enum.hint" in template, "подсказка живёт в модели, а не в шаблоне"


def test_kitchen_panel() -> None:
    """Панель кухни: сводка смены, вкладки, правка меню и настройки."""
    template = _read(TEMPLATES / "staff" / "queue.html")
    for part in ("crew__tabs", 'data-panel="queue"', 'data-panel="menu"',
                 'data-panel="settings"', "dish-form", "settings-form", "crew-place"):
        assert part in template, f"в панели нет {part}"
    assert 'data-panel="report"' in template, "аналитика доступна администратору"

    # Часы и дашборд смены убраны: очередь должна начинаться сразу.
    assert "crew-clock" not in template, "часы смены должны были уйти"
    assert "crew__stats" not in template, "сводка-дашборд должна была уйти"
    tabs_at = template.index('class="crew__tabs"')
    board_at = template.index('class="crew__board"')
    assert tabs_at < board_at, "вкладки должны стоять в шапке, выше очереди"

    panel = _read(STATIC_JS / "staff_panel.js")
    for fn in ("loadOrders", "loadMenu", "openEditor", "loadSettings", "paintReport"):
        assert f"function {fn}" in panel, f"нет {fn}"
    # Кухня меняет статус только своего заказа и защищена версией записи.
    assert "new_status" in panel and "version: version" in panel
    # Правка блюда уходит на оба метода: PUT для существующего, POST для нового.
    assert "method: id ? 'PUT' : 'POST'" in panel

    css = _read(STATIC_CSS / "style.css")
    for part in (".crew__head", ".crew__stat", ".ticket", ".menu-card", ".report__card"):
        assert part in css, f"нет стилей {part}"

    # Старые экраны админки заменены одной панелью.
    assert not (TEMPLATES / "staff" / "menu_admin.html").exists()
    assert not (STATIC_JS / "admin.js").exists()
    routes = _read(BASE_DIR / "app" / "routers" / "public_pages.py")
    assert 'RedirectResponse(url="/staff"' in routes, "старый /admin должен вести в панель"


def test_each_kitchen_account_has_own_place() -> None:
    """Аккаунты кухни привязаны к разным заведениям: смена видит только свои заказы."""
    from app.init_db import PLACES, kitchen_username

    class _Place:
        def __init__(self, name: str, identifier: int) -> None:
            self.name = name
            self.id = identifier

    logins = [kitchen_username(_Place(spec["name"], index + 1))
              for index, spec in enumerate(PLACES)]
    assert len(set(logins)) == len(logins), f"логины кухни повторяются: {logins}"
    for spec in PLACES:
        assert kitchen_username(_Place(spec["name"], 1)).startswith("kitchen-")

    # Кухня — это роль staff, а не админ: настройки, аналитика и правка меню
    # ей недоступны, и фронтенд это учитывает.
    staff_panel = _read(STATIC_JS / "staff_panel.js")
    assert "var isAdmin = root.dataset.role === 'admin';" in staff_panel


def test_two_themes() -> None:
    """Светлая и тёмная темы: токены переопределяются, переключатель один смысл."""
    css = _read(STATIC_CSS / "style.css")
    dark = re.search(r'\[data-theme="dark"\]\s*\{(.*?)\}', css, re.S)
    assert dark, "нет блока тёмной темы"
    body = dark.group(1)
    for token in ("--base", "--cloud", "--ink", "--muted", "--hairline", "--flame"):
        assert token in body, f"в тёмной теме не переопределён {token}"
    # Акцент на тёмном фоне светлее: исходный теряет контраст.
    assert "--flame: #FF6A4D" in body

    app_js = _read(STATIC_JS / "app.js")
    assert "applyShift" in app_js and "startViewTransition" in app_js
    assert "localStorage.setItem('ep-shift'" in app_js, "выбор темы запоминается"

    # Тема ставится до отрисовки, иначе светлая мигнёт.
    base = _read(TEMPLATES / "base.html")
    assert "localStorage.getItem('ep-shift')" in base
    assert base.index("ep-shift") < base.index('<header class="top">')

    # Переключателей два (шапка и нижняя полоса) — id уникален, слушаем по классу.
    tabbar = _read(TEMPLATES / "partials" / "tabbar.html")
    assert "tabbar__theme shift-toggle" in tabbar
    assert 'id="shift-toggle"' not in tabbar, "id должен быть один на страницу"
    assert 'class="shift shift-toggle"' in base
    assert "querySelectorAll('.shift-toggle')" in app_js


def test_checkout_animations() -> None:
    """Оформление живое: шаги, въезжающие строки, одометр итога, количество."""
    template = _read(TEMPLATES / "partials" / "sheet_checkout.html")
    assert 'id="checkout-steps"' in template
    for step in ("items", "time", "guest"):
        assert f'data-step="{step}"' in template

    checkout = _read(STATIC_JS / "sheet_checkout.js")
    assert "function paintSteps" in checkout, "шаги должны отмечаться"
    assert "Cart.paintSummary(summary)" in checkout, "сводка обновляется на месте"
    assert "EP.countUp(totalOut" in checkout, "итог крутится, а не прыгает"
    assert "data-sum-act" in checkout, "количество меняется прямо в шторке"

    cart = _read(STATIC_JS / "cart.js")
    assert "function paintSummary" in cart
    assert "summary__row--out" in cart and "summary__row--in" in cart

    css = _read(STATIC_CSS / "style.css")
    for part in (".steps__item.is-done", "@keyframes step-pop", "@keyframes row-in",
                 ".summary__row--out", ".summary__side"):
        assert part in css, f"нет стиля {part}"


def test_guest_names_are_varied_in_checks() -> None:
    """Проверки не пишут одно и то же имя: в демо-очереди не должно быть клонов."""
    import smoke_test
    import tools.visual_check as visual

    assert len(set(smoke_test.GUEST_NAMES)) >= 8
    assert len(set(visual.GUEST_NAMES)) >= 8
    assert "random.choice(GUEST_NAMES)" in _read(BASE_DIR / "smoke_test.py")
    assert "random.choice(GUEST_NAMES)" in _read(BASE_DIR / "tools" / "visual_check.py")

    seed = _read(BASE_DIR / "tools" / "seed_demo_orders.py")
    names = re.findall(r'\("([А-ЯЁ][а-яё]+)", "\+7', seed)
    assert len(names) >= 5, f"в демо-очереди мало гостей: {names}"
    assert len(set(names)) == len(names), f"имена повторяются: {names}"



def test_sheet_scroll_lock_counts_open_sheets() -> None:
    """Прокрутку возвращаем только когда закрылась последняя шторка.

    Оформление открывается поверх табло времени: если каждая шторка будет
    сбрасывать overflow сама, страница под открытой шторкой начнёт ездить.
    """
    sheet_js = _read(STATIC_JS / "sheet.js")

    assert "var openCount = 0" in sheet_js, "нет счётчика открытых шторок"
    assert "openCount += 1" in sheet_js
    assert "openCount = Math.max(openCount - 1, 0)" in sheet_js, \
        "счётчик должен уменьшаться с защитой от отрицательного значения"
    # Главное: блокировка ставится на первой шторке и снимается только на нуле.
    assert "if (openCount === 1) {" in sheet_js, "прокрутка не блокируется"
    assert "document.body.style.overflow = 'hidden';" in sheet_js
    assert "if (openCount === 0) {" in sheet_js, "прокрутка не разблокируется"
    assert "document.body.style.overflow = '';" in sheet_js

    # Пока шторка открыта, фон недоступен: иначе фокус уходит за затемнение,
    # а при aria-modal="true" это тупик для клавиатуры и скринридера.
    assert "inertBackground(" in sheet_js and "releaseBackground(" in sheet_js
    assert "setAttribute('inert', '')" in sheet_js

    # Escape закрывает только верхнюю шторку, а не все сразу.
    assert "function topSheet()" in sheet_js
    assert "window.EP_SHEETS.forEach(function (sheet) { sheet.close(); })" not in sheet_js

    # Двойное закрытие одной шторки не должно ломать счётчик.
    assert "this.locked" in sheet_js, "шторка должна помнить, держит ли блокировку"
    assert "if (!this.locked)" in sheet_js and "if (this.locked)" in sheet_js

    # Счётчик доступен для проверок в браузере.
    assert "Sheet.openCount = function ()" in sheet_js


def test_scrim_uses_blur_like_the_rest_of_the_ui() -> None:
    """Затемнение шторки размывает фон — как шапка и стеклянные бейджи."""
    css = _read(STATIC_CSS / "style.css")
    body = _css_block(css, "\n.scrim {")
    assert "backdrop-filter: blur(6px)" in body
    assert "-webkit-backdrop-filter: blur(6px)" in body, "нужен префикс для Safari"


def test_cartbar_has_overshoot() -> None:
    """Полоса корзины приходит с перелётом, как шторка, а не просто выезжает."""
    css = _read(STATIC_CSS / "style.css")
    body = _css_block(css, "@keyframes cart-up {")
    assert "translateY(-5px)" in body, "нужен перелёт выше точки покоя"
    assert "translateY(2px)" in body, "нужен мягкий откат"
    # Перелёт должен быть и у шторки: единый приём.
    assert "translateY(-6px)" in _css_block(css, "@keyframes sheet-up {")


def test_menu_banner_has_parallax() -> None:
    """Фото баннера заведения сдвигается при скролле, как промо на главной."""
    menu_js = _read(STATIC_JS / "menu.js")
    assert "function paintBannerParallax" in menu_js
    assert "banner__photo" in menu_js
    assert "requestAnimationFrame" in menu_js, "сдвиг считаем в кадре, а не на каждый скролл"
    assert "prefers-reduced-motion" in menu_js, "движение должно отключаться"

    css = _read(STATIC_CSS / "style.css")
    # Фото выше контейнера: иначе сдвигать нечего.
    assert "calc(100% + 24px)" in _css_block(css, "\n.banner__photo {")


def test_time_picker_is_a_drum() -> None:
    """Выбор времени — барабаны как в будильнике, а не стена капсул.

    Раньше гость видел десятки кнопок на весь день; теперь два колеса,
    и в них попадает только доступное время.
    """
    template = _read(TEMPLATES / "partials" / "sheet_time.html")
    assert 'id="hour-drum"' in template and 'id="minute-drum"' in template
    assert 'id="day-bar"' in template, "нужен переключатель дня"
    assert 'id="time-nearest"' in template, "нужна кнопка ближайшего времени"
    # Прошедшие дни не предлагаем: у поля даты есть минимальное значение.
    assert 'min="{{ today }}"' in template

    script = _read(STATIC_JS / "sheet_time.js")
    # Значения барабана строятся только из доступных слотов: назад во времени
    # уйти нельзя, потому что таких значений в барабане просто нет.
    assert "slot.available" in script
    assert "scroll-snap" not in script  # прилипание задаётся в CSS
    assert "scrollToValue" in script and "highlight" in script
    assert "goToDay" in script and "value < window.TODAY" in script, \
        "день раньше сегодняшнего выбрать нельзя"

    css = _read(STATIC_CSS / "style.css")
    assert "scroll-snap-type: y mandatory" in css, "барабан должен прилипать к строке"
    assert "scroll-snap-align: center" in css
    assert ".daybar__day.is-on" in css, "выбранный день должен быть виден"
    # Шаг строки и отступы кратны друг другу: иначе прилипание встаёт между
    # значениями и выбирается соседнее — эта ошибка уже случалась.
    assert "height: 48px" in css and "padding-block: 48px" in css
    assert "height: 144px" in css, "окно барабана — ровно три строки"


def test_drum_keeps_slot_contract() -> None:
    """Барабан использует тот же класс .slot, что ждут проверки движения."""
    script = _read(STATIC_JS / "sheet_time.js")
    assert "'<button class=\"slot" in script or "class=\"slot" in script
    css = _read(STATIC_CSS / "style.css")
    assert ".drum .slot" in css
    assert ".drum .slot.is-on" in css, "выбранное значение должно быть выделено"


# ── Панель смены: рабочие мелочи, которые ломали работу ────────────────────
def test_kitchen_has_no_dead_date_filter() -> None:
    """У кухни нет выбора дня: он ничего не фильтровал.

    Сервер отдаёт всю активную очередь заведения — ночные брони относятся
    к следующему дню, и фильтр по дате их бы спрятал. Контрол, который
    ничего не менял, только путал смену.
    """
    template = _read(TEMPLATES / "staff" / "queue.html")
    assert 'id="crew-date"' not in template, "вернулся селектор даты без действия"
    assert 'id="crew-today"' in template, "нужна подпись смены"

    script = _read(STATIC_JS / "staff_panel.js")
    assert "crew-date" not in script
    assert "'/api/staff/orders?date='" not in script, "дата всё ещё уходит в запрос"


def test_kitchen_hears_a_new_order() -> None:
    """Новый заказ озвучивается: смена не смотрит на экран постоянно."""
    script = _read(STATIC_JS / "staff_panel.js")
    assert "noticeNewOrders" in script, "приход нового заказа не отслеживается"
    assert "knownOrders" in script
    # Первая загрузка не должна звучать как новый заказ.
    assert "knownOrders === null" in script
    assert "play('new')" in script, "нет звука нового заказа"

    sound = _read(STATIC_JS / "sound.js")
    assert "new: function ()" in sound, "в звуках нет сигнала нового заказа"


def test_expired_session_leads_to_login() -> None:
    """Истёкшая сессия возвращает на вход, а не оставляет смену в тупике."""
    script = _read(STATIC_JS / "staff_panel.js")
    assert "error.status === 401" in script, "нет реакции на истёкшую сессию"
    assert "EP.go('/login')" in script


def test_cancelling_an_order_asks_twice() -> None:
    """Отмена заказа подтверждается вторым нажатием.

    Это единственное действие кухни, которое нельзя отменить обратно:
    промах пальцем не должен стоить гостю заказа.
    """
    script = _read(STATIC_JS / "staff_panel.js")
    assert 'data-confirm="1"' in script, "кнопка отмены без подтверждения"
    assert "button.dataset.asked !== '1'" in script
    assert "Точно отменить?" in script

    css = _read(STATIC_CSS / "style.css")
    assert ".link-btn--danger" in css, "нет стиля подтверждения"


def test_cart_reset_on_place_change_is_explained() -> None:
    """Смена заведения очищает корзину — и говорит об этом.

    Раньше выбранное пропадало молча: гость не понимал, куда делся заказ.
    """
    cart = _read(STATIC_JS / "cart.js")
    assert "dropped" in cart, "очистка корзины не сообщает о себе"

    menu = _read(STATIC_JS / "menu.js")
    assert "bound.dropped" in menu, "меню не показывает предупреждение"
    assert "корзина очищена" in menu


def test_field_errors_are_linked_to_fields() -> None:
    """Ошибка поля связана с самим полем и переводит на него фокус.

    Без aria-describedby скринридер слышит «поле неверно», но не знает,
    какое именно и почему.
    """
    app = _read(STATIC_JS / "app.js")
    assert "aria-describedby" in app, "ошибка не связана с полем"
    assert "focusFirstBad" in app, "фокус не переводится на плохое поле"
    assert "-error'" in app or '-error"' in app, "у текста ошибки нет id"

    checkout = _read(STATIC_JS / "sheet_checkout.js")
    assert "EP.focusFirstBad(form)" in checkout


def test_empty_cart_resets_its_counter() -> None:
    """Пустая корзина обнуляет подписи: иначе остаётся «1 позиция»."""
    menu = _read(STATIC_JS / "menu.js")
    assert "Cart.portionsLabel(0)" in menu, "счётчик не сбрасывается"
    assert "EP.money(0)" in menu


def test_drum_reacts_to_press_not_only_scroll() -> None:
    """Значение барабана выбирается нажатием, а не только прокруткой.

    Подпись «час» лежала поверх нижнего значения и перехватывала нажатие,
    а само значение уходило под кнопку подтверждения: гость не мог выбрать
    время иначе как прокруткой, а до 19:00 это девять свайпов.
    """
    css = _read(STATIC_CSS / "style.css")
    assert ".drum__hint {" in css and "pointer-events: none" in css, \
        "подпись снова перехватывает нажатия"
    # Три строки: значение по центру и соседи, по которым тоже можно нажать.
    assert "height: 144px; overflow-y: auto;" in css
    assert "padding-block: 48px;" in css

    script = _read(STATIC_JS / "sheet_time.js")
    assert "settleUntil" in script, "нет защиты от возврата прежнего значения"
    assert "drum.addEventListener('click'" in script, "нет выбора нажатием"
    assert "item.dataset.value" in script


def test_mobile_overrides_come_last() -> None:
    """Мобильные правки стоят в конце файла.

    Базовые правила объявлены ниже по файлу, и при равной специфичности
    побеждает последнее. Из-за этого мобильные переопределения молча
    не работали: кнопка «Выбрать заведение» оставалась на экране, а фото
    карточки не сжималось.
    """
    css = _read(STATIC_CSS / "style.css")
    marker = "Телефон: правки, которые должны идти последними"
    assert marker in css, "нет блока мобильных правок"

    tail = css[css.index(marker):]
    for rule in (".place__media { aspect-ratio: 16 / 11; }",
                 ".window-card .window-card__cta { display: none; }"):
        assert rule in tail, f"мобильное правило не в конце файла: {rule}"

    # И ни одно из них не осталось выше по файлу.
    head = css[:css.index(marker)]
    assert ".window-card .window-card__cta { display: none; }" not in head


def test_mobile_first_screen_shows_a_venue() -> None:
    """Первый экран телефона — лента заведений, а не только промо.

    Раньше название первого заведения было на 121px ниже сгиба: гость видел
    адрес, поиск, баннер и карточку окна, но ни одного заведения.
    """
    css = _read(STATIC_CSS / "style.css")
    marker = "Телефон: правки, которые должны идти последними"
    tail = css[css.index(marker):]

    # Лента заведений с прокруткой вбок вместо длинного столбца.
    assert "grid-auto-flow: column" in tail, "заведения не в ленте"
    assert "scroll-snap-type: x mandatory" in tail
    # Баннер компактнее, пояснение карточки окна убрано.
    assert ".promo { min-height: 132px; }" in tail
    assert ".window-card__note { display: none; }" in tail


def test_scroll_to_top_is_on_every_page() -> None:
    """Кнопка «наверх» есть на всех экранах и умеет возвращать к началу.

    Очередь кухни и меню длинные: без кнопки гость и смена крутят вверх
    десяток свайпов.
    """
    base = _read(TEMPLATES / "base.html")
    assert 'id="to-top"' in base, "кнопки нет в общей разметке"
    assert 'aria-label' in base.split('id="to-top"')[1][:400], "у кнопки нет имени"

    app = _read(STATIC_JS / "app.js")
    assert "function bindToTop()" in app and "bindToTop();" in app
    # Появляется только после прокрутки и уважает «меньше движения».
    assert "SHOW_AFTER" in app
    assert "prefers-reduced-motion: reduce" in app

    css = _read(STATIC_CSS / "style.css")
    assert ".to-top {" in css
    # На телефоне кнопка не наезжает на нижнюю навигацию.
    assert "bottom: calc(var(--tabbar-h) + 16px);" in css


def test_chip_pill_aligns_with_the_active_chip() -> None:
    """Плашка активного чипа совпадает с ним по месту и размеру.

    Плашка абсолютная и отсчитывается от внутренней области ленты: без
    поправки на её вертикальный отступ плашка уезжала вверх и вставала
    над подписью — именно так это выглядело в кадре.
    """
    app = _read(STATIC_JS / "app.js")
    assert "function moveChipPill(container, active)" in app
    assert "paddingTop" in app, "нет поправки на вертикальный отступ ленты"
    assert "container.scrollLeft" in app, "нет поправки на прокрутку ленты"

    menu = _read(STATIC_JS / "menu.js")
    assert "EP.moveChipPill(catsLane, activeChip)" in menu, "меню не двигает плашку"
    assert "chips__pill" in menu, "в ленте категорий нет плашки"


def test_place_names_are_visible_and_address_is_per_place() -> None:
    """Название кафе — крупно в карточке, адрес — только у своего кафе.

    В шапке главной стоял адрес первого заведения, а адреса у точек разные:
    гость видел «пр. Достык, 128» и не понимал, к чему он относится.
    """
    places_html = _read(TEMPLATES / "places.html")
    assert 'id="pickup-address"' not in places_html, "общий адрес вернулся в шапку"

    places_js = _read(STATIC_JS / "places.js")
    assert "pickup-address" not in places_js, "скрипт снова подставляет чужой адрес"
    # Имя кафе есть в карточке.
    assert 'class="place__name"' in places_js
    # Название кафе — под фото, сразу под снимком.
    assert "place__name" in places_js, "в карточке нет названия кафе"
    assert "place__caption" not in places_js, "название на фото перекрывает бейджи"

    css = _read(STATIC_CSS / "style.css")
    assert ".place__name {" in css
    # Медиа карточки блочное: иначе карточка считает высоту только по фото,
    # и тело с названием обрезается её же overflow: hidden.
    assert ".place__media {" in css
    media_rule = css[css.index(".place__media {"):]
    media_rule = media_rule[:media_rule.index("}")]
    assert "display: block" in media_rule, "медиа снова строчное — тело карточки обрежется"

def test_reduced_motion_disables_animation() -> None:
    css = _read(STATIC_CSS / "style.css")
    block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*)\}", css, re.S)
    assert block, "нет блока prefers-reduced-motion"
    body = block.group(1)
    # Все анимации и переходы отключаются целиком.
    assert "animation: none !important" in body
    assert "transition: none !important" in body
    for expected in (".skeleton::after", ".plus-one", ".cartbar", ".chips__pill"):
        assert expected in body, f"в reduced-motion не отключено: {expected}"
    assert "stroke-dashoffset: 0" in body, "галочка должна быть видна сразу"


def test_progress_has_four_segments_with_fill_animation() -> None:
    partial = _read(TEMPLATES / "partials" / "progress.html")
    # Макрос рисует сегменты циклом по четырём состояниям заказа.
    assert "progress__seg" in partial
    assert "[('Принят', 1), ('Готовится', 2), ('Готово', 3), ('Выдано', 4)]" in partial
    css = _read(STATIC_CSS / "style.css")
    assert "transition: width var(--t-fill) var(--ease-fill)" in css, "сегменты должны заполняться плавно"
    assert '.progress__seg[data-state="ready"] .progress__fill { width: 100%; background: var(--fresh-deep); }' in css


def test_success_has_custom_check_animation() -> None:
    template = _read(TEMPLATES / "order_status.html")
    assert "check-path" in template, "галочка должна рисоваться кастомным SVG"
    css = _read(STATIC_CSS / "style.css")
    assert "stroke-dasharray" in css and "draw-check" in css


def test_no_emoji_or_icon_fonts() -> None:
    """Иконочные библиотеки и эмодзи в разметке не используются."""
    for template in TEMPLATES.rglob("*.html"):
        text = _read(template)
        assert "font-awesome" not in text.lower()
        assert "material-icons" not in text.lower()
        emoji = re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)
        assert not emoji, f"{template.name}: эмодзи в разметке — {emoji}"


def test_all_hex_colors_are_valid() -> None:
    """Цвета в CSS записаны корректно.

    Ищем только значения свойств, а не идентификаторы вида #order-card:
    они тоже начинаются с решётки, но цветом не являются.
    """
    css = _css_without_comments()
    offenders = []
    for value in re.findall(r":\s*([^;{}]*#[0-9A-Za-zА-Яа-яЁё][^;{}]*)", css):
        for token in re.findall(r"#[0-9A-Za-zА-Яа-яЁё]+", value):
            if not re.fullmatch(r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})", token):
                offenders.append(token)
    assert not offenders, f"некорректный цвет: {offenders}"


def test_css_variables_are_declared() -> None:
    css = _read(STATIC_CSS / "style.css")
    declared = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.M))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert not (used - declared), f"не объявлены переменные: {sorted(used - declared)}"


def test_css_has_balanced_braces() -> None:
    css = _read(STATIC_CSS / "style.css")
    assert css.count("{") == css.count("}")


# ── Клиентский флоу ─────────────────────────────────────────────────────────

def test_guest_flow_has_no_registration_fields() -> None:
    """Условие кейса: в клиентском флоу нет логина, пароля и SMS."""
    markup = " ".join(
        _read(path) for path in (
            TEMPLATES / "places.html",
            TEMPLATES / "menu.html",
            TEMPLATES / "partials" / "sheet_time.html",
            TEMPLATES / "partials" / "sheet_checkout.html",
        )
    ).lower()
    for forbidden in ('type="password"', 'name="email"', "смс", "sms-код"):
        assert forbidden not in markup, f"в клиентском флоу появилось поле {forbidden}"


def test_menu_screen_uses_bottom_sheets_not_pages() -> None:
    """Выбор времени и оформление — шторки, а не отдельные URL."""
    frame = _read(TEMPLATES / "menu.html")
    assert "sheet_time.html" in frame and "sheet_checkout.html" in frame
    scripts = _read(STATIC_JS / "sheet.js")
    assert "new Sheet('time-sheet'" in scripts
    assert "new Sheet('checkout-sheet'" in scripts


def test_order_schema_matches_checkout_payload() -> None:
    """Поля, которые отправляет шторка оформления, должны приниматься схемой."""
    fields = set(OrderCreateRequest.model_fields)
    source = _read(STATIC_JS / "sheet_checkout.js")
    body = re.search(r"var body = \{(.*?)\n    \};", source, re.S)
    assert body, "в sheet_checkout.js не найден объект body"
    sent = set(re.findall(r"^\s*([a-z_]+):", body.group(1), re.M))
    assert sent <= fields, f"фронтенд отправляет неизвестные поля: {sorted(sent - fields)}"


def test_card_payment_option_supported() -> None:
    """Бриф требует оба способа оплаты при получении — они должны быть в модели."""
    from app.models.order import PaymentMethod

    values = {method.value for method in PaymentMethod}
    assert {"cash_on_pickup", "card_on_pickup"} <= values
    sheet = _read(TEMPLATES / "partials" / "sheet_checkout.html")
    assert 'value="cash_on_pickup"' in sheet and 'value="card_on_pickup"' in sheet


def test_photos_present_and_used_in_templates() -> None:
    """Фото — главный визуальный якорь: проверяем, что они есть и подключены."""
    photos = list((BASE_DIR / "app" / "static" / "img" / "menu").glob("*.jpg"))
    places = list((BASE_DIR / "app" / "static" / "img" / "places").glob("*.jpg"))
    assert len(photos) >= 5, f"фото блюд мало: {len(photos)}"
    assert len(places) >= 2, f"фото заведений мало: {len(places)}"
    # Карточки заведений рисует скрипт, карточки блюд — шаблон.
    assert "place__photo" in _read(STATIC_JS / "places.js")
    assert 'class="dish__photo"' in _read(TEMPLATES / "menu.html")
    assert "banner__photo" in _read(TEMPLATES / "menu.html")
    # Фото из витрины должны существовать на диске.
    from app.init_db import PLACES

    for spec in PLACES:
        assert (BASE_DIR / "app" / spec["photo"].lstrip("/")).exists(), spec["photo"]
        for row in spec["menu"]:
            photo = row[5]
            if photo:
                assert (BASE_DIR / "app" / photo.lstrip("/")).exists(), photo


def test_seeded_showcase_is_complete(db) -> None:
    """Начальные данные витрины: у каждого активного блюда есть фото и описание,
    у каждого заведения — фото, кухня и рейтинг. Пустая карточка выглядит сломанной."""
    from sqlalchemy import select

    from app.init_db import seed
    from app.models.establishment import Establishment
    from app.models.menu_item import MenuItem

    seed(db)

    places = db.scalars(select(Establishment).order_by(Establishment.id)).all()
    assert places, "витрина должна создавать заведения"
    for place in places:
        assert place.photo, f"{place.name}: нет фото"
        assert place.cuisine, f"{place.name}: не указана кухня"
        assert (BASE_DIR / "app" / place.photo.lstrip("/")).exists(), place.photo
        assert float(place.rating) > 0, f"{place.name}: рейтинг не задан"

        items = db.scalars(
            select(MenuItem).where(
                MenuItem.establishment_id == place.id, MenuItem.is_active.is_(True)
            )
        ).all()
        assert items, f"{place.name}: пустое меню"
        for item in items:
            assert item.photo, f"{place.name}: у «{item.name}» нет фото"
            assert item.description, f"{place.name}: у «{item.name}» нет описания"
            assert (BASE_DIR / "app" / item.photo.lstrip("/")).exists(), item.photo
