"""Планировщик фоновых задач (правило Б-3: авто-истечение невостребованных заказов).

APScheduler вместо Celery/RabbitMQ — для MVP этого достаточно (раздел 2.19 ТЗ).
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.logging_utils import get_logger
from app.services.order_service import OrderService

logger = get_logger("scheduler")

JOB_ID = "expire_stale_orders"


def expire_stale_orders_job() -> int:
    """Один проход задачи: помечает невостребованные заказы как expired."""
    db = SessionLocal()
    try:
        expired = OrderService(db).expire_stale_orders()
        if expired:
            logger.info("Фоновая задача: помечено expired заказов — %s", expired)
        return expired
    except Exception:  # pragma: no cover - зависит от состояния БД
        db.rollback()
        logger.exception("Ошибка фоновой задачи авто-истечения заказов")
        return 0
    finally:
        db.close()


def create_scheduler(interval_seconds: int = 60) -> AsyncIOScheduler:
    """Создаёт (но не запускает) планировщик с задачей авто-истечения."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        expire_stale_orders_job,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id=JOB_ID,
        name="Авто-истечение невостребованных заказов",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
