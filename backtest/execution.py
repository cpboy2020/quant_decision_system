import logging
from typing import Dict, List
from dataclasses import dataclass, field
logger = logging.getLogger(__name__)

class SlippageModel:
    def __init__(self, fixed_pct=0.001, impact_coeff=0.0002):
        self.fixed_pct, self.impact_coeff = fixed_pct, impact_coeff
    def get_exec_price(self, price, direction, qty, avg_vol):
        base = price*(1+self.fixed_pct) if direction=="BUY" else price*(1-self.fixed_pct)
        impact = self.impact_coeff*(qty/max(avg_vol,1))
        return base*(1+impact) if direction=="BUY" else base*(1-impact)

@dataclass
class Portfolio:
    cash: float = 1_000_000.0
    positions: Dict[str, int] = field(default_factory=dict)
    available_qty: Dict[str, int] = field(default_factory=dict)
    trades: List[Dict] = field(default_factory=list)
    def update_t_plus_1(self, is_end_of_day):
        if is_end_of_day: self.available_qty = dict(self.positions)
    def check_buy(self, symbol, qty, margin_req=0.0): return self.cash >= margin_req
    def execute_trade(self, symbol, direction, exec_price, qty, commission, slippage_cost, dt):
        if direction=="BUY":
            self.cash -= (exec_price*qty + commission + slippage_cost)
            self.positions[symbol] = self.positions.get(symbol,0)+qty
        else:
            self.cash += (exec_price*qty - commission - slippage_cost)
            self.positions[symbol] = self.positions.get(symbol,0)-qty
            if self.positions[symbol]==0: del self.positions[symbol]
        self.trades.append({"timestamp":dt,"symbol":symbol,"direction":direction,"price":exec_price,"qty":qty,"commission":commission,"slippage":slippage_cost})
