from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from interfaces import BillingService
from core.exceptions import (
    BillingError,
    PaymentProcessingError,
    InsufficientFundsError
)
from payment.processors import PaymentProcessor
from subscription.lifecycle import SubscriptionLifecycleManager

logger = logging.getLogger(__name__)


class BillingEngine(BillingService):
    """Движок биллинга для обработки периодических платежей"""
    
    def __init__(self, 
                 payment_processor: PaymentProcessor,
                 subscription_manager: SubscriptionLifecycleManager,
                 max_workers: int = 5):
        self.payment_processor = payment_processor
        self.subscription_manager = subscription_manager
        self.max_workers = max_workers
        self.retry_config = {
            'max_attempts': 3,
            'initial_delay': 1,  # час
            'backoff_factor': 2,
            'max_delay': 24  # часа
        }
    
    def process_recurring_payments(self) -> List[Dict[str, Any]]:
        """Обработать все подошедшие периодические платежи"""
        results = []
        
        try:
            # 1. Получение подписок для списания
            subscriptions = self._get_subscriptions_due_for_payment()
            logger.info(f"Found {len(subscriptions)} subscriptions due for payment")
            
            # 2. Параллельная обработка платежей
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_sub = {
                    executor.submit(self._process_subscription_payment, sub): sub
                    for sub in subscriptions
                }
                
                for future in as_completed(future_to_sub):
                    subscription = future_to_sub[future]
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(
                            f"Failed to process subscription {subscription.id}: {str(e)}"
                        )
                        results.append({
                            'subscription_id': subscription.id,
                            'success': False,
                            'error': str(e)
                        })
            
            # 3. Логирование и статистика
            successful = sum(1 for r in results if r['success'])
            logger.info(
                f"Billing completed: {successful}/{len(results)} successful"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Billing process failed: {str(e)}")
            raise BillingError(f"Billing process failed: {str(e)}")
    
    def retry_failed_payments(self, max_retries: int = 3) -> List[Dict[str, Any]]:
        """Повторить неудачные платежи"""
        results = []
        
        try:
            # 1. Получение неудачных транзакций
            failed_transactions = self._get_failed_transactions(max_retries)
            
            # 2. Обработка каждой транзакции
            for transaction in failed_transactions:
                try:
                    result = self._retry_payment(transaction)
                    results.append(result)
                except Exception as e:
                    logger.error(
                        f"Failed to retry transaction {transaction.id}: {str(e)}"
                    )
                    results.append({
                        'transaction_id': transaction.id,
                        'success': False,
                        'error': str(e)
                    })
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to retry payments: {str(e)}")
            raise BillingError(f"Failed to retry payments: {str(e)}")
    
    def generate_invoice(self, transaction_id: str) -> bytes:
        """Сгенерировать счет в PDF формате"""
        try:
            # 1. Получение данных транзакции
            transaction = self._get_transaction(transaction_id)
            if not transaction:
                raise BillingError(f"Transaction {transaction_id} not found")
            
            # 2. Получение данных пользователя и подписки
            user = transaction.user
            subscription = transaction.subscription
            
            # 3. Генерация HTML шаблона счета
            html_content = self._generate_invoice_html(
                transaction, user, subscription
            )
            
            # 4. Конвертация в PDF (используем WeasyPrint или аналогичную библиотеку)
            pdf_content = self._html_to_pdf(html_content)
            
            return pdf_content
            
        except Exception as e:
            logger.error(f"Failed to generate invoice: {str(e)}")
            raise BillingError(f"Failed to generate invoice: {str(e)}")
    
    # Вспомогательные методы
    def _process_subscription_payment(self, subscription: Any) -> Dict[str, Any]:
        """Обработать платеж для одной подписки"""
        try:
            # 1. Проверка блокировок и конкурентного доступа
            if not self._acquire_lock(subscription.id):
                return {
                    'subscription_id': subscription.id,
                    'success': False,
                    'error': 'Could not acquire lock'
                }
            
            try:
                # 2. Выполнение платежа
                transaction = self.payment_processor.process_payment(
                    user_id=subscription.user_id,
                    amount=subscription.plan.price,
                    payment_method_id=subscription.payment_method_id,
                    description=f"Auto-renewal of {subscription.plan.name}",
                    metadata={
                        'subscription_id': str(subscription.id),
                        'billing_cycle': subscription.current_period_end
                    }
                )
                
                # 3. Продление подписки
                next_period_end = subscription.current_period_end + timedelta(
                    days=subscription.plan.billing_cycle_days
                )
                
                updated_subscription = self._extend_subscription(
                    subscription.id, next_period_end
                )
                
                # 4. Отправка уведомлений
                self._send_payment_success_notification(
                    subscription.user_id,
                    transaction
                )
                
                return {
                    'subscription_id': subscription.id,
                    'success': True,
                    'transaction_id': transaction.id,
                    'amount': transaction.amount,
                    'next_billing_date': next_period_end
                }
                
            except InsufficientFundsError:
                # 5. Обработка недостатка средств
                return self._handle_insufficient_funds(subscription)
                
            except PaymentProcessingError as e:
                # 6. Обработка ошибок платежной системы
                return self._handle_payment_error(subscription, str(e))
                
            finally:
                # 7. Освобождение блокировки
                self._release_lock(subscription.id)
                
        except Exception as e:
            logger.error(
                f"Unexpected error processing subscription {subscription.id}: {str(e)}"
            )
            return {
                'subscription_id': subscription.id,
                'success': False,
                'error': str(e)
            }
    
    def _handle_insufficient_funds(self, subscription: Any) -> Dict[str, Any]:
        """Обработать недостаток средств"""
        # 1. Увеличение счетчика попыток
        subscription.retry_count += 1
        
        # 2. Проверка максимального количества попыток
        if subscription.retry_count >= subscription.plan.max_retries:
            # Отмена подписки
            self._cancel_subscription_for_non_payment(subscription)
            
            return {
                'subscription_id': subscription.id,
                'success': False,
                'error': 'Subscription cancelled due to non-payment',
                'cancelled': True
            }
        
        # 3. Запланировать повторную попытку
        retry_date = datetime.now() + timedelta(
            days=self.retry_config['initial_delay'] * 
                 (self.retry_config['backoff_factor'] ** (subscription.retry_count - 1))
        )
        
        self._schedule_retry(subscription.id, retry_date)
        
        # 4. Отправить уведомление
        self._send_payment_failed_notification(
            subscription.user_id,
            subscription,
            'insufficient_funds'
        )
        
        return {
            'subscription_id': subscription.id,
            'success': False,
            'error': 'Insufficient funds',
            'retry_scheduled': retry_date,
            'retry_count': subscription.retry_count
        }
    
    def _handle_payment_error(self, subscription: Any, 
                             error_message: str) -> Dict[str, Any]:
        """Обработать ошибку платежной системы"""
        # Логирование ошибки
        logger.error(
            f"Payment gateway error for subscription {subscription.id}: {error_message}"
        )
        
        # Отправка уведомления администратору
        self._send_admin_alert(
            'payment_gateway_error',
            {
                'subscription_id': str(subscription.id),
                'user_id': str(subscription.user_id),
                'error': error_message
            }
        )
        
        return {
            'subscription_id': subscription.id,
            'success': False,
            'error': f'Payment gateway error: {error_message}'
        }
    
    def _acquire_lock(self, subscription_id: str) -> bool:
        """Получить блокировку для обработки подписки"""
        # Реализация с использованием Redis или базы данных
        # для предотвращения конкурентного списания
        return True  # Заглушка
    
    def _send_payment_success_notification(self, user_id: str, 
                                          transaction: Any) -> None:
        """Отправить уведомление об успешном платеже"""
        notification_data = {
            'transaction_id': str(transaction.id),
            'amount': transaction.amount,
            'date': datetime.now().isoformat()
        }
        
        # Здесь должна быть интеграция с сервисом уведомлений
        pass