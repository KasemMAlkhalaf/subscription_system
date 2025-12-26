from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable, TypeVar, Generic
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from dataclasses import dataclass
from uuid import UUID

T = TypeVar('T')
R = TypeVar('R', covariant=True)


# ============================================================================
# Базовые интерфейсы
# ============================================================================

class Entity(ABC):
    """Базовый класс для всех сущностей"""
    
    @property
    @abstractmethod
    def id(self) -> UUID:
        pass
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        return hash(self.id)


@runtime_checkable
class Repository(Protocol[T]):
    """Интерфейс репозитория"""
    
    def add(self, entity: T) -> None:
        ...
    
    def get(self, id: UUID) -> T | None:
        ...
    
    def update(self, entity: T) -> None:
        ...
    
    def delete(self, id: UUID) -> None:
        ...
    
    def list(self, **filters) -> list[T]:
        ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Интерфейс Unit of Work"""
    
    def commit(self) -> None:
        ...
    
    def rollback(self) -> None:
        ...
    
    def __enter__(self):
        ...
    
    def __exit__(self, *args):
        ...


# ============================================================================
# Доменные модели
# ============================================================================

class SubscriptionStatus(StrEnum):
    """Статусы подписки"""
    ACTIVE = "active"
    PENDING = "pending"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class PaymentStatus(StrEnum):
    """Статусы платежей"""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class TransactionType(StrEnum):
    """Типы транзакций"""
    SUBSCRIPTION_CREATE = "subscription_create"
    RENEWAL = "renewal"
    UPGRADE = "upgrade"
    DOWNGRADE = "downgrade"
    REFUND = "refund"
    MANUAL = "manual"


@dataclass(frozen=True)
class Money:
    """Value Object для денежных сумм"""
    amount: Decimal
    currency: str = "RUB"
    
    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
    
    def __add__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError("Cannot add money in different currencies")
        return Money(self.amount + other.amount, self.currency)
    
    def __sub__(self, other: 'Money') -> 'Money':
        if self.currency != other.currency:
            raise ValueError("Cannot subtract money in different currencies")
        return Money(self.amount - other.amount, self.currency)
    
    def __mul__(self, multiplier: Decimal) -> 'Money':
        return Money(self.amount * multiplier, self.currency)
    
    def __lt__(self, other: 'Money') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare money in different currencies")
        return self.amount < other.amount
    
    def __gt__(self, other: 'Money') -> bool:
        if self.currency != other.currency:
            raise ValueError("Cannot compare money in different currencies")
        return self.amount > other.amount


@dataclass
class TimePeriod:
    """Период времени для подписок"""
    value: int
    unit: str  # 'days', 'months', 'years'
    
    def to_days(self) -> int:
        if self.unit == 'days':
            return self.value
        elif self.unit == 'months':
            return self.value * 30
        elif self.unit == 'years':
            return self.value * 365
        else:
            raise ValueError(f"Unknown unit: {self.unit}")


# ============================================================================
# Интерфейсы предметной области
# ============================================================================

class PaymentGateway(ABC):
    """Интерфейс платежного шлюза"""
    
    @abstractmethod
    def charge(self, amount: Money, payment_method_id: str, 
               customer_id: str) -> tuple[bool, str]:
        """Выполнить списание средств"""
        pass
    
    @abstractmethod
    def refund(self, transaction_id: str, amount: Money) -> tuple[bool, str]:
        """Вернуть средства"""
        pass
    
    @abstractmethod
    def create_payment_method(self, token: str, 
                             customer_data: dict) -> tuple[bool, str, str]:
        """Создать метод оплаты"""
        pass
    
    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Верифицировать вебхук"""
        pass


class SubscriptionManager(ABC):
    """Менеджер управления подписками"""
    
    @abstractmethod
    def create_subscription(self, user_id: UUID, plan_id: UUID,
                           payment_method_id: str, promo_code: str = None) -> dict:
        """Создать новую подписку"""
        pass
    
    @abstractmethod
    def cancel_subscription(self, subscription_id: UUID, 
                           immediate: bool = False) -> dict:
        """Отменить подписку"""
        pass
    
    @abstractmethod
    def upgrade_subscription(self, subscription_id: UUID, 
                            new_plan_id: UUID) -> dict:
        """Обновить тариф подписки"""
        pass
    
    @abstractmethod
    def renew_subscription(self, subscription_id: UUID) -> dict:
        """Продлить подписку"""
        pass


class BillingService(ABC):
    """Сервис биллинга"""
    
    @abstractmethod
    def process_recurring_payments(self) -> list[dict]:
        """Обработать периодические платежи"""
        pass
    
    @abstractmethod
    def retry_failed_payments(self, max_retries: int = 3) -> list[dict]:
        """Повторить неудачные платежи"""
        pass
    
    @abstractmethod
    def generate_invoice(self, transaction_id: UUID) -> bytes:
        """Сгенерировать счет"""
        pass


class NotificationService(ABC):
    """Сервис уведомлений"""
    
    @abstractmethod
    def send_notification(self, user_id: UUID, event_type: str, 
                         data: dict) -> bool:
        """Отправить уведомление"""
        pass
    
    @abstractmethod
    def schedule_notification(self, user_id: UUID, event_type: str,
                            data: dict, send_at: datetime) -> UUID:
        """Запланировать уведомление"""
        pass


class Scheduler(ABC):
    """Планировщик задач"""
    
    @abstractmethod
    def schedule_daily_task(self, task: callable, hour: int, minute: int) -> str:
        """Запланировать ежедневную задачу"""
        pass
    
    @abstractmethod
    def schedule_recurring_task(self, task: callable, interval: timedelta) -> str:
        """Запланировать повторяющуюся задачу"""
        pass
    
    @abstractmethod
    def cancel_task(self, task_id: str) -> bool:
        """Отменить задачу"""
        pass