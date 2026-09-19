"""Общие типы для схем и параметров запроса.

`RecordId` закрывает сразу две проблемы: отрицательные идентификаторы (которых
в базе не бывает) и значения больше 2^63−1. Второе важнее, чем кажется: SQLite
хранит целые как 64-битные, и `GET /api/establishments/10**20/menu` падал с
OverflowError — то есть клиент получал 500 вместо понятного 422.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

# Верхняя граница — максимум знакового 64-битного целого.
MAX_SQLITE_INT = 2**63 - 1

RecordId = Annotated[int, Field(ge=1, le=MAX_SQLITE_INT)]
