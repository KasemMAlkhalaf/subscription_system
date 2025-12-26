
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID
from decimal import Decimal
import logging

from interfaces import SubscriptionManager
from core.exceptions import (
    SubscriptionError, 
    PaymentProcessingError,
    InsufficientFundsError
)
from subscription.plans import PlanCalculator
from payment.processors import PaymentProcessor

logger = logging.getLogger(__name__)


class SubscriptionLifecycleManager(SubscriptionManager):
    """Менеджер жизненного цикла подписок"""
    
    def __init__(self, 
                 payment_processor: PaymentProcessor,
                 plan_calculator: PlanCalculator,
                 notification_service):
        self.payment_processor = payment_processor
        self.plan_calculator = plan_calculator
        self.notification_service = notification_service
        self.retry_policy = {
            'max_retries': 3,
            'retry_delays': [1, 3, 7],  # дни
            'backoff_factor': 2
        }
    
    def create_subscription(self, user_id: UUID, plan_id: UUID,
                           payment_method_id: str, 
                           promo_code: str = None) -> Dict[str, Any]:
        """Создать новую подписку"""
        try:
            # 1. Проверка существующей активной подписки
            existing_sub = self._get_active_subscription(user_id)
            if existing_sub:
                raise SubscriptionError(
                    "User already has an active subscription"
                )
            
            # 2. Получение информации о тарифе
            plan = self.plan_calculator.get_plan(plan_id)
            
            # 3. Применение промо-кода
            discount = self._apply_promo_code(promo_code, plan, user_id)
            
            # 4. Расчет периода
            period_start = datetime.now()
            period_end = period_start + timedelta(days=plan.billing_cycle_days)
            
            # 5. Обработка пробного периода
            trial_period = None
            if plan.trial_period_days > 0:
                trial_period = self._setup_trial_period(
                    plan.trial_period_days,
                    period_start,
                    period_end
                )
            
            # 6. Выполнение первоначального платежа (если не trial)
            transaction = None
            if not trial_period:
                transaction = self.payment_processor.process_payment(
                    user_id=user_id,
                    amount=plan.price - discount,
                    payment_method_id=payment_method_id,
                    description=f"Subscription to {plan.name}"
                )
            
            # 7. Создание подписки в БД
            subscription = self._create_subscription_record(
                user_id=user_id,
                plan_id=plan_id,
                status='active' if trial_period else 'pending',
                period_start=period_start,
                period_end=period_end,
                trial_period=trial_period,
                payment_method_id=payment_method_id
            )
            
            # 8. Отправка уведомлений
            self._send_subscription_created_notifications(
                user_id, subscription, transaction
            )
            
            return {
                'success': True,
                'subscription_id': subscription.id,
                'transaction_id': transaction.id if transaction else None,
                'trial_ends_at': trial_period['end'] if trial_period else None,
                'next_billing_date': period_end
            }
            
        except Exception as e:
            logger.error(f"Failed to create subscription: {str(e)}")
            raise
    
    def cancel_subscription(self, subscription_id: UUID, 
                           immediate: bool = False) -> Dict[str, Any]:
        """Отменить подписку"""
        try:
            subscription = self._get_subscription(subscription_id)
            
            if subscription.status == 'cancelled':
                raise SubscriptionError("Subscription already cancelled")
            
            if immediate:
                # Немедленная отмена с возможным возвратом средств
                return self._cancel_immediately(subscription)
            else:
                # Отмена в конце текущего периода
                return self._cancel_at_period_end(subscription)
                
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {str(e)}")
            raise
    
    def upgrade_subscription(self, subscription_id: UUID, 
                            new_plan_id: UUID) -> Dict[str, Any]:
        """Обновить тариф подписки"""
        try:
            subscription = self._get_subscription(subscription_id)
            current_plan = subscription.plan
            new_plan = self.plan_calculator.get_plan(new_plan_id)
            
            # Проверка возможности апгрейда
            self._validate_upgrade(current_plan, new_plan)
            
            # Расчет пропорциональной стоимости
            prorated_amount = self._calculate_prorated_amount(
                subscription, current_plan, new_plan
            )
            
            # Обработка доплаты
            if prorated_amount > 0:
                transaction = self.payment_processor.process_payment(
                    user_id=subscription.user_id,
                    amount=prorated_amount,
                    payment_method_id=subscription.payment_method_id,
                    description=f"Upgrade from {current_plan.name} to {new_plan.name}"
                )
            else:
                transaction = None
            
            # Обновление подписки
            updated_subscription = self._update_subscription_plan(
                subscription, new_plan_id
            )
            
            # Отправка уведомлений
            self._send_upgrade_notifications(
                subscription.user_id,
                current_plan.name,
                new_plan.name,
                prorated_amount
            )
            
            return {
                'success': True,
                'subscription_id': updated_subscription.id,
                'transaction_id': transaction.id if transaction else None,
                'prorated_amount': prorated_amount,
                'new_plan': new_plan.name
            }
            
        except Exception as e:
            logger.error(f"Failed to upgrade subscription: {str(e)}")
            raise
    
    def renew_subscription(self, subscription_id: UUID) -> Dict[str, Any]:
        """Продлить подписку"""
        try:
            subscription = self._get_subscription(subscription_id)
            
            if subscription.status != 'active':
                raise SubscriptionError(
                    "Only active subscriptions can be renewed"
                )
            
            # Расчет следующего периода
            current_end = subscription.current_period_end
            next_end = current_end + timedelta(
                days=subscription.plan.billing_cycle_days
            )
            
            # Обработка платежа
            transaction = self.payment_processor.process_payment(
                user_id=subscription.user_id,
                amount=subscription.plan.price,
                payment_method_id=subscription.payment_method_id,
                description=f"Renewal of {subscription.plan.name}"
            )
            
            # Обновление периода подписки
            updated_subscription = self._extend_subscription_period(
                subscription, next_end
            )
            
            # Отправка уведомлений
            self._send_renewal_notifications(
                subscription.user_id,
                subscription.plan.name,
                transaction.amount
            )
            
            return {
                'success': True,
                'subscription_id': updated_subscription.id,
                'transaction_id': transaction.id,
                'next_billing_date': next_end,
                'amount': transaction.amount
            }
            
        except Exception as e:
            logger.error(f"Failed to renew subscription: {str(e)}")
            raise
    
    # Вспомогательные методы
    def _apply_promo_code(self, promo_code: str, plan: Any, 
                         user_id: UUID) -> Decimal:
        """Применить промо-код к подписке"""
        if not promo_code:
            return Decimal('0')
        
        # Здесь должна быть логика проверки и применения промо-кода
        # Проверка срока действия, количества использований и т.д.
        return Decimal('0')
    
    def _setup_trial_period(self, trial_days: int, 
                           period_start: datetime,
                           period_end: datetime) -> Dict[str, datetime]:
        """Настроить пробный период"""
        trial_end = period_start + timedelta(days=trial_days)
        
        return {
            'start': period_start,
            'end': trial_end,
            'active': True
        }
    
    def _calculate_prorated_amount(self, subscription: Any,
                                 current_plan: Any,
                                 new_plan: Any) -> Decimal:
        """Рассчитать пропорциональную стоимость при смене тарифа"""
        # Расчет количества оставшихся дней в текущем периоде
        days_used = (datetime.now() - subscription.current_period_start).days
        total_days = (subscription.current_period_end - 
                     subscription.current_period_start).days
        days_remaining = total_days - days_used
        
        # Пропорциональный расчет
        daily_rate_current = current_plan.price / total_days
        daily_rate_new = new_plan.price / total_days
        amount_paid = daily_rate_current * days_used
        amount_due = daily_rate_new * days_remaining
        
        return max(amount_due - amount_paid, Decimal('0'))
    
    def _validate_upgrade(self, current_plan: Any, new_plan: Any) -> None:
        """Проверить возможность апгрейда"""
        if new_plan.price <= current_plan.price:
            raise SubscriptionError(
                "New plan must be more expensive for upgrade"
            )
    
    def _send_subscription_created_notifications(self, user_id: UUID,
                                                subscription: Any,
                                                transaction: Any) -> None:
        """Отправить уведомления о создании подписки"""
        notification_data = {
            'subscription_id': str(subscription.id),
            'plan_name': subscription.plan.name,
            'amount': transaction.amount if transaction else 0,
            'next_billing_date': subscription.current_period_end
        }
        
        self.notification_service.send_notification(
            user_id=user_id,
            event_type='subscription_created',
            data=notification_data
        )