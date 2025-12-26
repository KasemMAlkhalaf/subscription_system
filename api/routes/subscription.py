
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from core.auth import get_current_user, require_roles
from core.models import UserRole
from interfaces import SubscriptionManager, BillingService
from api.schemas import (
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionCancelRequest,
    SubscriptionUpgradeRequest,
    BillingResponse,
    InvoiceResponse
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.post("/", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    request: SubscriptionCreateRequest,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    subscription_manager: SubscriptionManager = Depends()
):
    """
    Создать новую подписку
    """
    try:
        result = subscription_manager.create_subscription(
            user_id=current_user.id,
            plan_id=request.plan_id,
            payment_method_id=request.payment_method_id,
            promo_code=request.promo_code
        )
        
        # Запуск фоновой задачи для отправки уведомлений
        background_tasks.add_task(
            _send_welcome_notification,
            current_user.id,
            result['subscription_id']
        )
        
        return SubscriptionResponse(
            subscription_id=result['subscription_id'],
            status="active",
            plan_id=request.plan_id,
            current_period_start=datetime.now(),
            current_period_end=result['next_billing_date'],
            trial_ends_at=result.get('trial_ends_at')
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{subscription_id}/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    subscription_id: UUID,
    request: SubscriptionCancelRequest,
    current_user = Depends(get_current_user),
    subscription_manager: SubscriptionManager = Depends()
):
    """
    Отменить подписку
    """
    try:
        result = subscription_manager.cancel_subscription(
            subscription_id=subscription_id,
            immediate=request.immediate
        )
        
        return SubscriptionResponse(
            subscription_id=subscription_id,
            status="cancelled",
            cancelled_at=datetime.now(),
            cancel_at_period_end=not request.immediate
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{subscription_id}/upgrade", response_model=SubscriptionResponse)
async def upgrade_subscription(
    subscription_id: UUID,
    request: SubscriptionUpgradeRequest,
    current_user = Depends(get_current_user),
    subscription_manager: SubscriptionManager = Depends()
):
    """
    Обновить тариф подписки
    """
    try:
        result = subscription_manager.upgrade_subscription(
            subscription_id=subscription_id,
            new_plan_id=request.new_plan_id
        )
        
        return SubscriptionResponse(
            subscription_id=subscription_id,
            status="active",
            plan_id=request.new_plan_id,
            prorated_amount=result.get('prorated_amount')
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/{subscription_id}/renew", response_model=SubscriptionResponse)
async def renew_subscription(
    subscription_id: UUID,
    current_user = Depends(get_current_user),
    subscription_manager: SubscriptionManager = Depends()
):
    """
    Вручную продлить подписку
    """
    try:
        result = subscription_manager.renew_subscription(subscription_id)
        
        return SubscriptionResponse(
            subscription_id=subscription_id,
            status="active",
            current_period_end=result['next_billing_date'],
            last_renewal=datetime.now()
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{subscription_id}/invoice", response_model=InvoiceResponse)
async def get_invoice(
    subscription_id: UUID,
    transaction_id: Optional[UUID] = None,
    current_user = Depends(get_current_user),
    billing_service: BillingService = Depends()
):
    """
    Получить счет для подписки
    """
    try:
        if transaction_id:
            invoice_bytes = billing_service.generate_invoice(str(transaction_id))
        else:
            # Получение последней транзакции для подписки
            last_transaction = _get_last_subscription_transaction(subscription_id)
            if not last_transaction:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No transactions found for subscription"
                )
            invoice_bytes = billing_service.generate_invoice(str(last_transaction.id))
        
        # Конвертация в base64 для API
        import base64
        invoice_base64 = base64.b64encode(invoice_bytes).decode('utf-8')
        
        return InvoiceResponse(
            invoice_data=invoice_base64,
            format="pdf",
            filename=f"invoice_{subscription_id}_{datetime.now().date()}.pdf"
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/admin/process-billing", response_model=BillingResponse)
@require_roles([UserRole.ADMIN, UserRole.MANAGER])
async def process_billing(
    background_tasks: BackgroundTasks,
    billing_service: BillingService = Depends()
):
    """
    Запустить процесс биллинга вручную (только для администраторов)
    """
    try:
        # Запуск в фоновой задаче, т.к. процесс может быть длительным
        background_tasks.add_task(
            billing_service.process_recurring_payments
        )
        
        return BillingResponse(
            message="Billing process started",
            started_at=datetime.now()
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# Вспомогательные функции
async def _send_welcome_notification(user_id: UUID, subscription_id: UUID):
    """Отправить приветственное уведомление"""
    # Реализация отправки уведомления
    pass

def _get_last_subscription_transaction(subscription_id: UUID):
    """Получить последнюю транзакцию подписки"""
    # Реализация запроса к БД
    pass