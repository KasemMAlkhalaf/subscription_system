import schedule
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional
from dataclasses import dataclass
from uuid import UUID, uuid4
from concurrent.futures import ThreadPoolExecutor

from interfaces import Scheduler

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """Запланированная задача"""
    id: str
    task: Callable
    schedule_type: str  # 'daily', 'hourly', 'interval'
    schedule_params: Dict
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    is_active: bool = True


class TaskScheduler(Scheduler):
    """Планировщик задач на основе schedule"""
    
    def __init__(self, max_workers: int = 10):
        self.scheduler = schedule.Scheduler()
        self.tasks: Dict[str, ScheduledTask] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
    
    def schedule_daily_task(self, task: Callable, hour: int, 
                           minute: int = 0) -> str:
        """Запланировать ежедневную задачу"""
        task_id = str(uuid4())
        
        with self.lock:
            # Создание задачи в schedule
            job = self.scheduler.every().day.at(f"{hour:02d}:{minute:02d}").do(
                self._wrap_task, task_id, task
            )
            
            # Сохранение информации о задаче
            scheduled_task = ScheduledTask(
                id=task_id,
                task=task,
                schedule_type='daily',
                schedule_params={'hour': hour, 'minute': minute},
                next_run=self._calculate_next_run(hour, minute)
            )
            
            self.tasks[task_id] = scheduled_task
            logger.info(f"Scheduled daily task {task_id} at {hour:02d}:{minute:02d}")
        
        return task_id
    
    def schedule_recurring_task(self, task: Callable, 
                               interval: timedelta) -> str:
        """Запланировать повторяющуюся задачу"""
        task_id = str(uuid4())
        
        with self.lock:
            # Конвертация interval в параметры schedule
            if interval.total_seconds() < 60:
                # Меньше минуты - в секундах
                job = self.scheduler.every(interval.total_seconds()).seconds.do(
                    self._wrap_task, task_id, task
                )
                schedule_type = 'seconds'
            elif interval.total_seconds() < 3600:
                # Меньше часа - в минутах
                minutes = interval.total_seconds() // 60
                job = self.scheduler.every(minutes).minutes.do(
                    self._wrap_task, task_id, task
                )
                schedule_type = 'minutes'
            elif interval.total_seconds() < 86400:
                # Меньше дня - в часах
                hours = interval.total_seconds() // 3600
                job = self.scheduler.every(hours).hours.do(
                    self._wrap_task, task_id, task
                )
                schedule_type = 'hours'
            else:
                # Дни
                days = interval.total_seconds() // 86400
                job = self.scheduler.every(days).days.do(
                    self._wrap_task, task_id, task
                )
                schedule_type = 'days'
            
            # Сохранение информации о задаче
            scheduled_task = ScheduledTask(
                id=task_id,
                task=task,
                schedule_type=schedule_type,
                schedule_params={'interval': interval},
                next_run=datetime.now() + interval
            )
            
            self.tasks[task_id] = scheduled_task
            logger.info(f"Scheduled recurring task {task_id} every {interval}")
        
        return task_id
    
    def cancel_task(self, task_id: str) -> bool:
        """Отменить задачу"""
        with self.lock:
            if task_id not in self.tasks:
                logger.warning(f"Task {task_id} not found")
                return False
            
            # Отмена в schedule
            # Note: schedule не предоставляет прямого API для отмены задач по ID
            # В реальной реализации нужно хранить reference на job
            self.tasks[task_id].is_active = False
            logger.info(f"Cancelled task {task_id}")
            
            return True
    
    def start(self) -> None:
        """Запустить планировщик в отдельном потоке"""
        if self.is_running:
            logger.warning("Scheduler is already running")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("Task scheduler started")
    
    def stop(self) -> None:
        """Остановить планировщик"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info("Task scheduler stopped")
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус задачи"""
        with self.lock:
            if task_id not in self.tasks:
                return None
            
            task = self.tasks[task_id]
            return {
                'id': task.id,
                'schedule_type': task.schedule_type,
                'schedule_params': task.schedule_params,
                'last_run': task.last_run.isoformat() if task.last_run else None,
                'next_run': task.next_run.isoformat() if task.next_run else None,
                'is_active': task.is_active
            }
    
    def _run_scheduler(self) -> None:
        """Основной цикл планировщика"""
        while self.is_running:
            try:
                # Запуск запланированных задач
                self.scheduler.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error in scheduler loop: {str(e)}")
                time.sleep(5)  # Задержка перед повторной попыткой
    
    def _wrap_task(self, task_id: str, task: Callable) -> None:
        """Обертка для выполнения задачи с обработкой ошибок"""
        if not self._should_run_task(task_id):
            return
        
        try:
            logger.info(f"Starting task {task_id}")
            start_time = datetime.now()
            
            # Выполнение задачи в отдельном потоке
            future = self.executor.submit(task)
            future.result(timeout=300)  # Таймаут 5 минут
            
            # Обновление времени последнего выполнения
            with self.lock:
                if task_id in self.tasks:
                    self.tasks[task_id].last_run = datetime.now()
                    self.tasks[task_id].next_run = self._calculate_next_task_run(
                        self.tasks[task_id]
                    )
            
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"Task {task_id} completed in {execution_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {str(e)}")
    
    def _should_run_task(self, task_id: str) -> bool:
        """Проверить, должна ли задача выполняться"""
        with self.lock:
            if task_id not in self.tasks:
                return False
            return self.tasks[task_id].is_active
    
    def _calculate_next_run(self, hour: int, minute: int) -> datetime:
        """Рассчитать следующее время выполнения для ежедневной задачи"""
        now = datetime.now()
        next_run = datetime(now.year, now.month, now.day, hour, minute)
        
        if next_run < now:
            next_run += timedelta(days=1)
        
        return next_run
    
    def _calculate_next_task_run(self, task: ScheduledTask) -> Optional[datetime]:
        """Рассчитать следующее время выполнения задачи"""
        if task.schedule_type == 'daily':
            params = task.schedule_params
            return self._calculate_next_run(params['hour'], params['minute'])
        elif task.schedule_type in ['seconds', 'minutes', 'hours', 'days']:
            if task.last_run:
                interval_map = {
                    'seconds': timedelta(seconds=1),
                    'minutes': timedelta(minutes=1),
                    'hours': timedelta(hours=1),
                    'days': timedelta(days=1)
                }
                return task.last_run + interval_map.get(task.schedule_type, timedelta(days=1))
        
        return None


class SubscriptionScheduler:
    """Специализированный планировщик для задач подписок"""
    
    def __init__(self, 
                 billing_engine: BillingService,
                 notification_service,
                 task_scheduler: TaskScheduler):
        self.billing_engine = billing_engine
        self.notification_service = notification_service
        self.task_scheduler = task_scheduler
        self.scheduled_tasks = {}
    
    def setup_scheduled_tasks(self) -> None:
        """Настроить все запланированные задачи системы подписок"""
        
        # 1. Ежедневное списание средств в 02:00
        billing_task_id = self.task_scheduler.schedule_daily_task(
            self._run_billing, hour=2, minute=0
        )
        self.scheduled_tasks['billing'] = billing_task_id
        
        # 2. Повтор неудачных платежей каждый час
        retry_task_id = self.task_scheduler.schedule_recurring_task(
            self._run_payment_retries, interval=timedelta(hours=1)
        )
        self.scheduled_tasks['payment_retries'] = retry_task_id
        
        # 3. Проверка истекающих подписок ежедневно в 09:00
        expiration_task_id = self.task_scheduler.schedule_daily_task(
            self._check_expiring_subscriptions, hour=9, minute=0
        )
        self.scheduled_tasks['expiration_check'] = expiration_task_id
        
        # 4. Уведомления о пробном периоде каждый день в 10:00
        trial_notification_task_id = self.task_scheduler.schedule_daily_task(
            self._send_trial_notifications, hour=10, minute=0
        )
        self.scheduled_tasks['trial_notifications'] = trial_notification_task_id
        
        logger.info("All subscription tasks scheduled")
    
    def _run_billing(self) -> None:
        """Запустить процесс биллинга"""
        try:
            logger.info("Starting scheduled billing process")
            results = self.billing_engine.process_recurring_payments()
            logger.info(f"Billing completed: {len(results)} subscriptions processed")
        except Exception as e:
            logger.error(f"Billing task failed: {str(e)}")
    
    def _run_payment_retries(self) -> None:
        """Запустить повтор неудачных платежей"""
        try:
            logger.info("Starting payment retry process")
            results = self.billing_engine.retry_failed_payments()
            logger.info(f"Payment retries completed: {len(results)} retried")
        except Exception as e:
            logger.error(f"Payment retry task failed: {str(e)}")
    
    def _check_expiring_subscriptions(self) -> None:
        """Проверить истекающие подписки"""
        try:
            # Получить подписки, которые истекают через 3 дня
            expiring_subs = self._get_subscriptions_expiring_soon(days=3)
            
            for subscription in expiring_subs:
                self.notification_service.send_notification(
                    user_id=subscription.user_id,
                    event_type='subscription_expiring',
                    data={
                        'subscription_id': str(subscription.id),
                        'plan_name': subscription.plan.name,
                        'expires_at': subscription.current_period_end.isoformat()
                    }
                )
            
            logger.info(f"Sent expiration notifications for {len(expiring_subs)} subscriptions")
        except Exception as e:
            logger.error(f"Expiration check task failed: {str(e)}")
    
    def _send_trial_notifications(self) -> None:
        """Отправить уведомления о пробном периоде"""
        try:
            # Получить подписки с пробным периодом, истекающим через 1-2 дня
            ending_trials = self._get_trials_ending_soon(days=2)
            
            for subscription in ending_trials:
                days_left = (subscription.trial_end - datetime.now()).days
                
                self.notification_service.send_notification(
                    user_id=subscription.user_id,
                    event_type='trial_ending',
                    data={
                        'subscription_id': str(subscription.id),
                        'plan_name': subscription.plan.name,
                        'trial_ends_at': subscription.trial_end.isoformat(),
                        'days_left': days_left
                    }
                )
            
            logger.info(f"Sent trial notifications for {len(ending_trials)} subscriptions")
        except Exception as e:
            logger.error(f"Trial notification task failed: {str(e)}")