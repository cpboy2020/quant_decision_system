from strategies.base import QuantStrategy
from core.interfaces import Signal, MarketContext

class MomentumStrategy(QuantStrategy):
    REQUIRED_PARAMS = ["fast_window", "slow_window"]
    DEFAULT_PARAMS = {"fast_window": 5, "slow_window": 20, "threshold": 0.6}
    
    def __init__(self, name="momentum_v1", params=None):
        super().__init__(name, params)
    
    def generate_signal(self, context: MarketContext, data: dict) -> Signal:
        cs = data.get("close_series", [])
        if len(cs) < self.params["slow_window"]: return None
        fast = sum(cs[-self.params["fast_window"]:]) / self.params["fast_window"]
        slow = sum(cs[-self.params["slow_window"]:]) / self.params["slow_window"]
        if fast > slow * 1.002:
            return Signal(data.get("symbol",""), "LONG", self._normalize_strength((fast-slow)/slow*100), context.current_dt)
        elif fast < slow * 0.998:
            return Signal(data.get("symbol",""), "SHORT", self._normalize_strength((slow-fast)/slow*100), context.current_dt)
        return None
