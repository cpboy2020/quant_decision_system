import logging
import numpy as np
from typing import Dict
from dataclasses import dataclass
from enum import Enum
from core.interfaces import RiskManager, Signal
logger = logging.getLogger(__name__)

class CircuitState(Enum): NORMAL="normal"; REDUCING="reducing"; HALTED="halted"
@dataclass
class RiskConfig: target_annual_vol=0.12; atr_multiplier=2.5; atr_window=14; max_drawdown_threshold=0.10; drawdown_reduce_threshold=0.05; signal_confidence_threshold=0.4; max_single_position_pct=0.15

@dataclass
class PositionState:
    symbol: str
    direction: str
    entry_price: float
    trailing_stop: float
    highest_price: float
    lowest_price: float
    qty: int

class AdvancedRiskManager(RiskManager):
    def __init__(self, config=RiskConfig()):
        self.cfg, self.circuit_state, self.portfolio_peak_equity = config, CircuitState.NORMAL, 0.0
        self.position_states: Dict[str, PositionState] = {}
    def fuse_signals(self, signals):
        if not signals: return []
        fused = {}
        for s in signals:
            if s.symbol not in fused: fused[s.symbol] = {"net":0.0, "cnt":0, "ts":s.timestamp}
            fused[s.symbol]["net"] += s.strength*(1 if s.direction=="LONG" else -1)
            fused[s.symbol]["cnt"] += 1
        res = []
        for sym, d in fused.items():
            avg = d["net"]/max(d["cnt"],1)
            if abs(avg)>=self.cfg.signal_confidence_threshold: res.append(Signal(sym, "LONG" if avg>0 else "SHORT", min(abs(avg),1.0), d["ts"]))
        return res
    def calculate_position_size(self, signal, volatility_dict, equity, price):
        if signal.symbol not in volatility_dict or price<=0: return 0
        w = {k:1/v for k,v in {k:vi/np.sqrt(252) for k,vi in volatility_dict.items()}.items() if v>1e-6}
        if not w: return 0
        total = sum(w.values()); weight = min(w[signal.symbol]/total, self.cfg.max_single_position_pct)
        return max(int(equity*weight*signal.strength/price), 0)
    def update_trailing_stops(self, symbol, current_price, atr):
        if symbol not in self.position_states: return None
        p = self.position_states[symbol]; atr_val = max(atr,1e-6)
        if p.direction=="LONG":
            p.highest_price = max(p.highest_price, current_price)
            p.trailing_stop = max(p.trailing_stop, current_price - self.cfg.atr_multiplier*atr_val)
            return "FLAT" if current_price<=p.trailing_stop else None
        else:
            p.lowest_price = min(p.lowest_price, current_price)
            p.trailing_stop = min(p.trailing_stop, current_price + self.cfg.atr_multiplier*atr_val)
            return "FLAT" if current_price>=p.trailing_stop else None
    def register_position(self, sym, dir, price, qty, atr):
        self.position_states[sym] = PositionState(sym, dir, price, price-self.cfg.atr_multiplier*atr if dir=="LONG" else price+self.cfg.atr_multiplier*atr, price, price, qty)
    def remove_position(self, sym): self.position_states.pop(sym, None)
    def check_circuit_breaker(self, equity):
        self.portfolio_peak_equity = max(self.portfolio_peak_equity, equity)
        dd = (equity-self.portfolio_peak_equity)/self.portfolio_peak_equity if self.portfolio_peak_equity>0 else 0
        if dd <= -self.cfg.max_drawdown_threshold: self.circuit_state = CircuitState.HALTED
        elif dd <= -self.cfg.drawdown_reduce_threshold: self.circuit_state = CircuitState.REDUCING
        elif dd > -self.cfg.drawdown_reduce_threshold and self.circuit_state!=CircuitState.NORMAL: self.circuit_state = CircuitState.NORMAL
        return self.circuit_state
    def check_signal(self, signals, portfolio, context): return [] if self.circuit_state==CircuitState.HALTED else signals
    def pre_trade_check(self, order, account): return True
