
import json
import hmac
import hashlib
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal
import requests
from datetime import datetime

from interfaces import PaymentGateway, Money
from core.exceptions import PaymentError, PaymentValidationError


class BasePaymentGateway(PaymentGateway, ABC):
    """Базовый класс платежного шлюза"""
    
    def __init__(self, api_key: str, secret_key: str, is_test: bool = False):
        self.api_key = api_key
        self.secret_key = secret_key
        self.is_test = is_test
        self.base_url = self._get_base_url()
    
    @abstractmethod
    def _get_base_url(self) -> str:
        """Получить базовый URL API"""
        pass
    
    @abstractmethod
    def _get_headers(self) -> Dict[str, str]:
        """Получить заголовки для запросов"""
        pass
    
    def _make_request(self, method: str, endpoint: str, 
                     data: Optional[Dict] = None) -> Dict[str, Any]:
        """Выполнить HTTP запрос"""
        url = f"{self.base_url}/{endpoint}"
        headers = self._get_headers()
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise PaymentError(f"Payment gateway request failed: {str(e)}")


class YooMoneyGateway(BasePaymentGateway):
    """Шлюз YooMoney"""
    
    def __init__(self, shop_id: str, secret_key: str, is_test: bool = False):
        super().__init__(shop_id, secret_key, is_test)
        self.shop_id = shop_id
    
    def _get_base_url(self) -> str:
        if self.is_test:
            return "https://api.yookassa.ru/v3"
        return "https://api.yookassa.ru/v3"
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Basic {self.api_key}",
            "Idempotence-Key": str(datetime.now().timestamp()),
            "Content-Type": "application/json"
        }
    
    def charge(self, amount: Money, payment_method_id: str, 
               customer_id: str) -> Tuple[bool, str]:
        """Выполнить платеж через YooMoney"""
        try:
            # Создание платежа
            payment_data = {
                "amount": {
                    "value": str(amount.amount),
                    "currency": amount.currency
                },
                "payment_method_id": payment_method_id,
                "capture": True,
                "description": f"Payment for user {customer_id}",
                "metadata": {
                    "user_id": customer_id
                }
            }
            
            response = self._make_request("POST", "payments", payment_data)
            
            if response.get("status") == "succeeded":
                return True, response["id"]
            else:
                return False, response.get("description", "Payment failed")
                
        except Exception as e:
            return False, str(e)
    
    def refund(self, transaction_id: str, amount: Money) -> Tuple[bool, str]:
        """Создать возврат средств"""
        try:
            refund_data = {
                "payment_id": transaction_id,
                "amount": {
                    "value": str(amount.amount),
                    "currency": amount.currency
                }
            }
            
            response = self._make_request("POST", "refunds", refund_data)
            
            if response.get("status") == "succeeded":
                return True, response["id"]
            else:
                return False, response.get("description", "Refund failed")
                
        except Exception as e:
            return False, str(e)
    
    def create_payment_method(self, token: str, 
                             customer_data: Dict) -> Tuple[bool, str, str]:
        """Создать сохраненный метод оплаты"""
        # В реальной реализации здесь была бы интеграция с YooMoney
        # Для демонстрации возвращаем фиктивный ID
        fake_id = f"pm_{datetime.now().timestamp()}"
        return True, fake_id, "Method created successfully"
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Верификация вебхука YooMoney"""
        # В реальной реализации проверяем подпись
        computed_signature = hmac.new(
            self.secret_key.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)


class MockPaymentGateway(BasePaymentGateway):
    """Мок платежного шлюза для тестирования"""
    
    def __init__(self, success_rate: float = 0.95):
        self.success_rate = success_rate
        self.transactions = {}
        self._counter = 0
    
    def _get_base_url(self) -> str:
        return "https://mock.payment.gateway"
    
    def _get_headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}
    
    def charge(self, amount: Money, payment_method_id: str, 
               customer_id: str) -> Tuple[bool, str]:
        """Имитация списания средств"""
        import random
        
        self._counter += 1
        transaction_id = f"mock_tx_{self._counter}"
        
        # Имитация случайных сбоев
        if random.random() > self.success_rate:
            error_reasons = [
                "Insufficient funds",
                "Card expired",
                "Payment gateway timeout",
                "Invalid payment method"
            ]
            return False, random.choice(error_reasons)
        
        # Имитация успешного платежа
        self.transactions[transaction_id] = {
            "amount": amount.amount,
            "currency": amount.currency,
            "customer_id": customer_id,
            "status": "completed",
            "timestamp": datetime.now().isoformat()
        }
        
        return True, transaction_id
    
    def refund(self, transaction_id: str, amount: Money) -> Tuple[bool, str]:
        """Имитация возврата средств"""
        if transaction_id not in self.transactions:
            return False, "Transaction not found"
        
        self.transactions[transaction_id]["status"] = "refunded"
        refund_id = f"mock_refund_{self._counter}"
        
        return True, refund_id
    
    def create_payment_method(self, token: str, 
                             customer_data: Dict) -> Tuple[bool, str, str]:
        """Создать мок метод оплаты"""
        method_id = f"mock_pm_{self._counter}"
        return True, method_id, "Mock payment method created"
    
    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        """Всегда возвращает True для тестов"""
        return True


class PaymentGatewayFactory:
    """Фабрика платежных шлюзов"""
    
    @staticmethod
    def create_gateway(gateway_type: str, **kwargs) -> PaymentGateway:
        """Создать экземпляр платежного шлюза"""
        gateways = {
            "yoomoney": YooMoneyGateway,
            "mock": MockPaymentGateway
        }
        
        if gateway_type not in gateways:
            raise ValueError(f"Unknown gateway type: {gateway_type}")
        
        return gateways[gateway_type](**kwargs)