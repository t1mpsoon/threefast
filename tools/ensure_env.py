"""Создаёт постоянный SECRET_KEY в .env, если он пуст (чтобы сессии переживали перезапуск)."""
import re, secrets
from pathlib import Path

p = Path(__file__).resolve().parent.parent / ".env"
if p.exists():
    t = p.read_text(encoding="utf-8")
    if re.search(r"^SECRET_KEY=\s*$", t, re.M):
        p.write_text(re.sub(r"^SECRET_KEY=\s*$", "SECRET_KEY=" + secrets.token_urlsafe(48), t, flags=re.M), encoding="utf-8")
