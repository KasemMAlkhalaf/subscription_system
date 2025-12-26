
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, \
    Numeric, Enum as SQLEnum, Text, Index, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base, validates
from sqlalchemy.sql import func

Base = declarative_base()


class UserRole(Enum):
    """Роли пользователей"""
    ADMIN = "admin"
    USER = "user"
    MANAGER = "manager"


class User(Base):
    """Модель пользователя"""
    __tablename__ = 'users'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    balance = Column(Numeric(10, 2), default=0.0, nullable=False)
    currency = Column(String(3), default='RUB', nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Связи
    subscriptions = relationship("Subscription", back_populates="user")
    payment_methods = relationship("PaymentMethod", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    
    # Индексы
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_role', 'role'),
        CheckConstraint('balance >= 0', name='check_balance_non_negative'),
    )
    
    @validates('email')
    def validate_email(self, key, email):
        if '@' not in email:
            raise ValueError("Invalid email format")
        return email.lower()


class SubscriptionPlan(Base):
    """Модель тарифного плана"""
    __tablename__ = 'subscription_plans'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='RUB', nullable=False)
    billing_cycle_days = Column(Integer, nullable=False)  # 30, 365 и т.д.
    trial_period_days = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    features = Column(JSONB, default=dict)  # {"storage": "10GB", "users": 5}
    max_retries = Column(Integer, default=3, nullable=False)
    metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Связи
    subscriptions = relationship("Subscription", back_populates="plan")
    
    # Индексы
    __table_args__ = (
        Index('idx_plan_price', 'price'),
        Index('idx_plan_active', 'is_active'),
        CheckConstraint('price >= 0', name='check_price_non_negative'),
        CheckConstraint('billing_cycle_days > 0', name='check_billing_cycle_positive'),
    )


class Subscription(Base):
    """Модель подписки"""
    __tablename__ = 'subscriptions'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    plan_id = Column(PG_UUID(as_uuid=True), ForeignKey('subscription_plans.id'), nullable=False)
    status = Column(String(50), nullable=False, index=True)  # active, cancelled, expired
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    cancelled_at = Column(DateTime)
    trial_start = Column(DateTime)
    trial_end = Column(DateTime)
    payment_method_id = Column(String(100))  # ID в платежной системе
    auto_renew = Column(Boolean, default=True, nullable=False)
    retry_count = Column(Integer, default=0, nullable=False)
    metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Связи
    user = relationship("User", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan", back_populates="subscriptions")
    transactions = relationship("Transaction", back_populates="subscription")
    
    # Индексы
    __table_args__ = (
        Index('idx_subscription_status', 'status'),
        Index('idx_subscription_period_end', 'current_period_end'),
        Index('idx_user_subscription', 'user_id', 'status'),
        UniqueConstraint('user_id', 'plan_id', name='unique_active_user_plan',
                        postgresql_where=(status == 'active')),
    )


class PaymentMethod(Base):
    """Модель метода оплаты"""
    __tablename__ = 'payment_methods'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    gateway = Column(String(50), nullable=False)  # yoomoney, stripe, etc
    method_type = Column(String(50), nullable=False)  # card, wallet, etc
    external_id = Column(String(255), nullable=False)  # ID в платежной системе
    is_default = Column(Boolean, default=False, nullable=False)
    is_valid = Column(Boolean, default=True, nullable=False)
    metadata = Column(JSONB, default=dict)
    last_used = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Связи
    user = relationship("User", back_populates="payment_methods")
    
    # Индексы
    __table_args__ = (
        Index('idx_payment_method_user', 'user_id', 'is_default'),
        Index('idx_payment_method_external', 'gateway', 'external_id'),
        UniqueConstraint('gateway', 'external_id', name='unique_external_payment_method'),
    )


class Transaction(Base):
    """Модель транзакции"""
    __tablename__ = 'transactions'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    subscription_id = Column(PG_UUID(as_uuid=True), ForeignKey('subscriptions.id'), index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='RUB', nullable=False)
    status = Column(String(50), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # subscription, renewal, refund
    gateway = Column(String(50))
    gateway_transaction_id = Column(String(255))
    description = Column(Text)
    error_message = Column(Text)
    metadata = Column(JSONB, default=dict)
    processed_at = Column(DateTime, default=func.now(), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Связи
    user = relationship("User", back_populates="transactions")
    subscription = relationship("Subscription", back_populates="transactions")
    
    # Индексы
    __table_args__ = (
        Index('idx_transaction_user_date', 'user_id', 'created_at'),
        Index('idx_transaction_status', 'status'),
        Index('idx_gateway_transaction', 'gateway', 'gateway_transaction_id'),
        CheckConstraint('amount != 0', name='check_amount_non_zero'),
    )


class PromoCode(Base):
    """Модель промо-кода"""
    __tablename__ = 'promo_codes'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    discount_type = Column(String(20), nullable=False)  # percentage, fixed
    discount_value = Column(Numeric(10, 2), nullable=False)
    max_uses = Column(Integer)
    used_count = Column(Integer, default=0, nullable=False)
    max_discount = Column(Numeric(10, 2))
    min_purchase_amount = Column(Numeric(10, 2))
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime)
    is_active = Column(Boolean, default=True, nullable=False)
    plan_ids = Column(JSONB)  # Список UUID планов, к которым применяется
    metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Индексы
    __table_args__ = (
        Index('idx_promo_code_active', 'is_active', 'valid_from', 'valid_to'),
        CheckConstraint('discount_value > 0', name='check_discount_positive'),
        CheckConstraint('used_count <= max_uses OR max_uses IS NULL', 
                       name='check_max_uses'),
    )


class Notification(Base):
    """Модель уведомления"""
    __tablename__ = 'notifications'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # payment, subscription, system
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    channel = Column(String(50), default='email')  # email, sms, push, in_app
    status = Column(String(50), default='pending')  # pending, sent, failed
    priority = Column(Integer, default=0)  # 0-low, 1-medium, 2-high
    metadata = Column(JSONB, default=dict)
    sent_at = Column(DateTime)
    read_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Индексы
    __table_args__ = (
        Index('idx_notification_user_status', 'user_id', 'status'),
        Index('idx_notification_type', 'type'),
    )


class AuditLog(Base):
    """Модель лога аудита"""
    __tablename__ = 'audit_logs'
    
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(PG_UUID(as_uuid=True), ForeignKey('users.id'), index=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255))
    old_values = Column(JSONB)
    new_values = Column(JSONB)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    metadata = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Индексы
    __table_args__ = (
        Index('idx_audit_user_action', 'user_id', 'action'),
        Index('idx_audit_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_created', 'created_at'),
    )