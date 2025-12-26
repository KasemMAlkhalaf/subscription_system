import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from core.database import init_db, get_session
from api.routes import subscription, payment, admin
from scheduler.task_scheduler import TaskScheduler, SubscriptionScheduler
from payment.gateways import PaymentGatewayFactory
from subscription.lifecycle import SubscriptionLifecycleManager
from subscription.billing import BillingEngine

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('subscription_system.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управление жизненным циклом приложения
    """
    # Инициализация при запуске
    logger.info("Starting Subscription System...")
    
    # Инициализация базы данных
    await init_db()
    
    # Инициализация зависимостей
    dependencies = await init_dependencies()
    app.state.dependencies = dependencies
    
    # Запуск планировщика задач
    scheduler = dependencies['task_scheduler']
    scheduler.start()
    
    yield
    
    # Очистка при остановке
    logger.info("Stopping Subscription System...")
    scheduler.stop()


async def init_dependencies():
    """Инициализация всех зависимостей приложения"""
    dependencies = {}
    
    # 1. Инициализация платежного шлюза
    gateway = PaymentGatewayFactory.create_gateway(
        gateway_type="mock",  # или "yoomoney" для продакшена
        success_rate=0.95
    )
    dependencies['payment_gateway'] = gateway
    
    # 2. Инициализация сервисов
    # ... (инициализация других сервисов)
    
    # 3. Инициализация планировщика
    task_scheduler = TaskScheduler(max_workers=10)
    dependencies['task_scheduler'] = task_scheduler
    
    return dependencies


# Создание FastAPI приложения
app = FastAPI(
    title="Subscription Management System",
    description="Профессиональная система управления подписками с поддержкой платежей",
    version="1.0.0",
    lifespan=lifespan
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутеров
app.include_router(subscription.router)
# app.include_router(payment.router)
# app.include_router(admin.router)


@app.get("/")
async def root():
    """Корневой endpoint"""
    return {
        "message": "Subscription Management System",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )