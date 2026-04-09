import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from core.interfaces import Strategy, Signal, MarketContext

class QuantStrategy(Strategy, ABC):
    REQUIRED_PARAMS: List[str] = []
    DEFAULT_PARAMS: Dict[str, Any] = {}
    
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.logger = logging.getLogger(f"Strategy.{name}")
        self._validate_params()
    
    def _validate_params(self):
        missing = [p for p in self.REQUIRED_PARAMS if p not in self.params]
        if missing: raise ValueError(f"[{self.name}] 缺失必需参数: {missing}")
    
    @abstractmethod
    def generate_signal(self, context: MarketContext, data: Dict[str, Any]) -> Optional[Signal]: pass
    
    def on_bar(self, context: MarketContext, data: Dict[str, Any]) -> List[Signal]:
        try:
            sig = self.generate_signal(context, data)
            return [sig] if sig else []
        except Exception as e:
            self.logger.error(f"策略异常: {e}", exc_info=True)
            return []
    
    def _normalize_strength(self, v, mn=0.0, mx=1.0): return max(mn, min(mx, v))
