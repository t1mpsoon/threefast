"""Pydantic-схемы запросов/ответов API."""

from app.schemas.auth import LoginRequest, StaffUserCreate, StaffUserOut, TokenResponse
from app.schemas.menu import (
    EstablishmentBrief,
    MenuItemCreate,
    MenuItemOut,
    MenuItemUpdate,
    MenuResponse,
)
from app.schemas.order import (
    AnalyticsResponse,
    OrderCreateRequest,
    OrderCreateResponse,
    OrderItemIn,
    OrderItemOut,
    OrderStatusResponse,
    StaffOrderOut,
    StatusUpdateRequest,
    StatusUpdateResponse,
)
from app.schemas.slot import SlotListResponse, SlotOut, SlotSettingsUpdate

__all__ = [
    "AnalyticsResponse",
    "EstablishmentBrief",
    "LoginRequest",
    "MenuItemCreate",
    "MenuItemOut",
    "MenuItemUpdate",
    "MenuResponse",
    "OrderCreateRequest",
    "OrderCreateResponse",
    "OrderItemIn",
    "OrderItemOut",
    "OrderStatusResponse",
    "SlotListResponse",
    "SlotOut",
    "SlotSettingsUpdate",
    "StaffOrderOut",
    "StaffUserCreate",
    "StaffUserOut",
    "StatusUpdateRequest",
    "StatusUpdateResponse",
    "TokenResponse",
]
