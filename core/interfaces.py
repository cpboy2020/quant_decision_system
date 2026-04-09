import abc
import logging
from datetime import datetime
from typing import Any, Dict, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class QuantSystemError(Exception): pass

class MarketType(Enum):
    A_SHARE = "a_share"; FUTURES_CN = "futures_cn"
    US_STOCK = "us_stock"; HK_STOCK = "hk_stock"; CRYPTO = "crypto"

@dataclass
class MarketContext:
    market: MarketType; current_dt: datetime
    trading_calendar: List[datetime]; contract_specs: Dict[str, Any]

class DataProvider(abc.ABC):
    @abc.abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> Any: ...
    @abc.abstractmethod
    def get_trading_calendar(self, market: MarketType, start: datetime, end: datetime) -> List[datetime]: ...
    @abc.abstractmethod
    def close(self) -> None: ...

class MarketRule(abc.ABC):
    @abc.abstractmethod
    def is_tradable(self, symbol: str, dt: datetime, context: MarketContext) -> bool: ...
    @abc.abstractmethod
    def calculate_commission(self, symbol: str, price: float, volume: float) -> float: ...
    @abc.abstractmethod
    def adjust_order(self, order: Dict[str, Any], context: MarketContext) -> Dict[str, Any]: ...

@dataclass
class Signal:
    symbol: str; direction: str; strength: float
    timestamp: datetime; meta: Dict[str, Any] = None

class Strategy(abc.ABC):
    def __init__(self, name: str, params: Dict[str, Any]):
        self.name, self.params = name, params
    @abc.abstractmethod
    def on_bar(self, context: MarketContext, bar_data: Dict[str, Any]) -> List[Signal]: ...
    def validate_params(self) -> None: pass

class RiskManager(abc.ABC):
    @abc.abstractmethod
    def check_signal(self, signals: List[Signal], portfolio: Dict[str, Any], context: MarketContext) -> List[Signal]: ...
    @abc.abstractmethod
    def pre_trade_check(self, order: Dict[str, Any], account: Dict[str, Any]) -> bool: ...

class ExecutionGateway(abc.ABC):
    @abc.abstractmethod
    def submit_order(self, order: Dict[str, Any]) -> str: ...
    @abc.abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...
    @abc.abstractmethod
    def get_positions(self) -> Dict[str, Any]: ...
    @abc.abstractmethod
    def on_connect(self) -> None: ...
    @abc.abstractmethod
    def on_disconnect(self) -> None: ...
