"""Простой in-memory rate limiting (раздел 2.14 ТЗ, помечен как [ПРЕДЛОЖЕНИЕ]).

Ограничивает создание заказов с одного IP. Для MVP-хакатона достаточно
процессной памяти; при масштабировании заменяется на Redis без изменения API.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW_SECONDS = 60


class RateLimiter:
    """Скользящее окно: не более `limit` событий на ключ за WINDOW_SECONDS."""

    def __init__(self, limit: int, window_seconds: int = WINDOW_SECONDS) -> None:
        self.limit = max(limit, 1)
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Возвращает (разрешено, секунд_до_освобождения)."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            if len(self._events) > 5000:
                self._prune(moment)
            bucket = self._events[key]
            threshold = moment - self.window_seconds
            while bucket and bucket[0] <= threshold:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = int(self.window_seconds - (moment - bucket[0])) + 1
                return False, max(retry_after, 1)
            bucket.append(moment)
            return True, 0

    def _prune(self, moment: float) -> None:
        """Удаляет ключи, у которых все события вышли за окно (иначе память растёт)."""
        threshold = moment - self.window_seconds
        for key in [k for k, b in self._events.items() if not b or b[-1] <= threshold]:
            del self._events[key]

    def penalize(self, key: str, weight: int = 1, now: float | None = None) -> None:
        """Записывает событие без проверки — для промахов, которые копят блокировку.

        Нужно там, где важен не каждый запрос, а только неудачный: поиск заказа
        по коду. Гость, который смотрит свой заказ, лимит не тратит.
        """
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._events[key]
            threshold = moment - self.window_seconds
            while bucket and bucket[0] <= threshold:
                bucket.popleft()
            bucket.extend([moment] * max(weight, 1))

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Сколько секунд ждать: 0, если лимит ещё не выбран."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._events.get(key)
            if not bucket:
                return 0
            threshold = moment - self.window_seconds
            while bucket and bucket[0] <= threshold:
                bucket.popleft()
            if len(bucket) < self.limit:
                return 0
            return max(int(self.window_seconds - (moment - bucket[0])) + 1, 1)

    def reset(self, key: str | None = None) -> None:
        """Сброс состояния — используется в тестах."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
