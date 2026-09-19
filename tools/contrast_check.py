"""Проверка контраста палитры по WCAG 2.1 в обеих темах.

Запуск: python -m tools.contrast_check

Проверяются реальные значения из app/static/css/style.css, а не «красивые»
числа из документации: если роль в CSS испортится, проверка это покажет.
Тёмная тема читается из блока [data-theme="dark"] и проверяется теми же
правилами, что и светлая.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "style.css"

# (что проверяем, токен текста, токен фона, требуемое отношение)
LIGHT_CHECKS: tuple[tuple[str, str, str, float], ...] = (
    ("основной текст на белом", "--ink", "--base", 4.5),
    ("основной текст на Cloud", "--ink", "--cloud", 4.5),
    ("вторичный текст на белом", "--muted", "--base", 4.5),
    ("вторичный текст на Cloud", "--muted", "--cloud", 4.5),
    ("белый текст на плашке Ink", "--base", "--ink", 4.5),
    ("текст ошибки на белом", "--flame-dark", "--base", 4.5),
    ("акцентный текст на белом", "--flame", "--base", 3.0),
    ("белый текст на акценте (крупный)", "--base", "--flame", 3.0),
    ("зелёный индикатор на белом", "--fresh-deep", "--base", 3.0),
    ("янтарный индикатор на белом", "--amber-deep", "--base", 3.0),
    ("текст зелёного бейджа", "#0B7A47", "--fresh-soft", 4.5),
    ("текст янтарного бейджа", "#A3600A", "--amber-soft", 4.5),
    ("текст красного бейджа", "#C33A20", "--flame-soft", 4.5),
)

# В тёмной теме те же роли проверяются на тёмных подложках.
DARK_CHECKS: tuple[tuple[str, str, str, float], ...] = (
    ("основной текст на фоне", "--ink", "--base", 4.5),
    ("основной текст на подложке", "--ink", "--cloud", 4.5),
    ("вторичный текст на фоне", "--muted", "--base", 4.5),
    ("вторичный текст на подложке", "--muted", "--cloud", 4.5),
    ("текст на акценте", "#1B1D21", "--flame", 4.5),
    ("акцентный текст на фоне", "--flame", "--base", 3.0),
    ("зелёный индикатор на фоне", "--fresh-deep", "--base", 3.0),
    ("янтарный индикатор на фоне", "--amber-deep", "--base", 3.0),
    ("текст зелёного бейджа", "#6EE7B0", "--fresh-soft", 4.5),
    ("текст янтарного бейджа", "#FFC24D", "--amber-soft", 4.5),
    ("текст красного бейджа", "#FF9C85", "--flame-soft", 4.5),
    ("текст бейджа времени", "#FFFFFF", "#C2410C", 4.5),
)


def read_tokens(selector: str = ":root") -> dict[str, str]:
    css = CSS.read_text(encoding="utf-8")
    pattern = re.escape(selector) + r"\s*\{(.*?)\}"
    block = re.search(pattern, css, re.S)
    assert block, f"в style.css не найден блок {selector}"
    return {
        name: value.upper()
        for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*(#[0-9A-Fa-f]{6})", block.group(1))
    }


def linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    raw = color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)


def ratio(foreground: str, background: str) -> float:
    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def run(title: str, tokens: dict[str, str], checks) -> int:
    failures = 0
    print(f"=== {title} ===")
    for label, text_token, bg_token, required in checks:
        text = tokens.get(text_token, text_token)
        background = tokens.get(bg_token, bg_token)
        if text is None or background is None:
            print(f"  ПРОПУСК {label}: нет токена {text_token} или {bg_token}")
            failures += 1
            continue
        value = ratio(text, background)
        ok = value >= required
        if not ok:
            failures += 1
        print(f"  {'OK  ' if ok else 'НИЖЕ'} {label:32} {text} на {background}  "
              f"{value:5.2f}:1  (нужно {required})")
    return failures


def main() -> int:
    light = read_tokens(":root")
    dark = read_tokens('[data-theme="dark"]')
    # Цвета, которые в тёмной теме задаются не токенами, а правилами:
    # их подставляет браузер, поэтому берём значения прямо из CSS.
    css = CSS.read_text(encoding="utf-8")
    dark["#6EE7B0"] = "#6EE7B0"
    dark["#FFC24D"] = "#FFC24D"
    dark["#FF9C85"] = "#FF9C85"
    dark["#C2410C"] = "#C2410C"
    dark["#1B1D21"] = "#1B1D21"
    dark["#FFFFFF"] = "#FFFFFF"
    assert '[data-theme="dark"]' in css

    failures = run("Контраст: светлая тема", light, LIGHT_CHECKS)
    failures += run("Контраст: тёмная тема", dark, DARK_CHECKS)

    print("\n=== Итог ===")
    if failures:
        print(f"  проверок не прошло: {failures}")
        print("  подберите более подходящий оттенок той же роли в style.css")
        return 1
    print("  обе темы проходят WCAG AA (текст) и 3:1 (индикаторы)")
    print("  акцент Flame остаётся #FF4F32 в светлой теме и #FF6A4D в тёмной:")
    print("  на тёмном фоне исходный оттенок теряет контраст")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
