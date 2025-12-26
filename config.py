import os
from typing import Optional
from pydantic import BaseSettings, Field, validator
from functools import lru_cache


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Настройки приложения
    APP_NAME: str = "Subscription System"
    DEBUG: bool = Field(default=False, env="DEBUG")
    ENVIRONMENT: str = Field(default="development", env="ENVIRONMENT")
    
    # Настройки базы данных
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DB_POOL_SIZE: int = Field(default=20, env="DB_POOL_SIZE")
    DB_MAX_OVERFLOW: int = Field(default=10, env="DB_MAX_OVERFLOW")
    
    # Настройки платежной системы
    PAYMENT_GATEWAY: str = Field(default="mock", env="PAYMENT_GATEWAY")
    YOOMONEY_SHOP_ID: Optional[str] = Field(None, env="YOOMONEY_SHOP_ID")
    YOOMONEY_SECRET_KEY: Optional[str] = Field(None, env="YOOMONEY_SECRET_KEY")
    PAYMENT_SUCCESS_RATE: float = Field(default=0.95, env="PAYMENT_SUCCESS_RATE")
    
    # Настройки безопасности
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str = Field(default="HS256", env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Настройки Redis (для кэша и блокировок)
    REDIS_URL: Optional[str] = Field(None, env="REDIS_URL")
    REDIS_PASSWORD: Optional[str] = Field(None, env="REDIS_PASSWORD")
    
    # Настройки планировщика
    SCHEDULER_MAX_WORKERS: int = Field(default=10, env="SCHEDULER_MAX_WORKERS")
    BILLING_HOUR: int = Field(default=2, env="BILLING_HOUR")
    BILLING_MINUTE: int = Field(default=0, env="BILLING_MINUTE")
    
    # Настройки уведомлений
    SMTP_HOST: Optional[str] = Field(None, env="SMTP_HOST")
    SMTP_PORT: Optional[int] = Field(None, env="SMTP_PORT")
    SMTP_USER: Optional[str] = Field(None, env="SMTP_USER")
    SMTP_PASSWORD: Optional[str] = Field(None, env="SMTP_PASSWORD")
    
    # Настройки логирования
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FILE: str = Field(default="subscription_system.log", env="LOG_FILE")
    
    # Настройки повторных попыток
    MAX_PAYMENT_RETRIES: int = Field(default=3, env="MAX_PAYMENT_RETRIES")
    RETRY_DELAY_DAYS: list = Field(default=[1, 3, 7], env="RETRY_DELAY_DAYS")
    
    class Config:
        env_file = ".env"
        case_sensitive = True
    
    @validator("DATABASE_URL")
    def validate_database_url(cls, v):
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v
    
    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        allowed = ["development", "testing", "production"]
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v


@lru_cache()
def get_settings() -> Settings:
    """Получить кэшированные настройки"""
    return Settings()


# Экспорт настроек
settings = get_settings()