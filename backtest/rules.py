import logging
from core.interfaces import MarketRule
logger = logging.getLogger(__name__)

class AshareRule(MarketRule):
    def __init__(self, limit_pct=0.10, lot_size=100, stamp_tax=0.001):
        self.limit_pct, self.lot_size, self.stamp_tax = limit_pct, lot_size, stamp_tax
        self.commission_rate = 0.0003
    def is_tradable(self, symbol, dt, context):
        prev = context.contract_specs.get(f"{symbol}_prev_close", 0)
        price = context.contract_specs.get(f"{symbol}_close", 0)
        if price >= prev*(1+self.limit_pct)*0.999 or price <= prev*(1-self.limit_pct)*1.001: return False
        return True
    def calculate_commission(self, symbol, price, volume): return price*volume*self.commission_rate
    def adjust_order(self, order, context):
        order["target_qty"] = (int(order.get("target_qty",0))//self.lot_size)*self.lot_size
        return order

class FuturesRule(MarketRule):
    def __init__(self, margin_pct=0.12, multiplier=10, commission_per_lot=3.0):
        self.margin_pct, self.multiplier, self.commission_per_lot = margin_pct, multiplier, commission_per_lot
    def is_tradable(self, symbol, dt, context): return True
    def calculate_commission(self, symbol, price, volume): return (volume/self.multiplier)*self.commission_per_lot
    def adjust_order(self, order, context):
        order["target_qty"] = (int(order.get("target_qty",0))//self.multiplier)*self.multiplier
        return order
