import pytest
import numpy as np
from datetime import datetime
from strategies.momentum import MomentumStrategy
from core.interfaces import Signal, MarketContext, MarketType

ctx = lambda: MarketContext(MarketType.A_SHARE, datetime.utcnow(), [], {})
data = lambda cs: {"symbol":"TEST", "close":cs[-1], "close_series":cs}

def test_missing_params():
    with pytest.raises(ValueError, match="缺失必需参数"): MomentumStrategy(params={"fast_window":5})

def test_defaults():
    s = MomentumStrategy(); assert s.params["slow_window"]==20 and s.params["threshold"]==0.6

def test_logic_golden_cross():
    s = MomentumStrategy(params={"fast_window":5, "slow_window":15})
    prices = [10.0]*10 + [12.0]*10
    sig = s.generate_signal(ctx(), data(prices))
    assert sig is not None and sig.direction == "LONG" and 0<=sig.strength<=1

def test_logic_death_cross():
    s = MomentumStrategy(params={"fast_window":5, "slow_window":15})
    prices = [12.0]*10 + [10.0]*10
    sig = s.generate_signal(ctx(), data(prices))
    assert sig is not None and sig.direction == "SHORT"

def test_threshold_filter():
    s = MomentumStrategy(params={"fast_window":5, "slow_window":15})
    assert s.generate_signal(ctx(), data([10.0]*20)) is None

def test_nan_handling():
    s = MomentumStrategy(params={"fast_window":5, "slow_window":15})
    prices = [10.0]*5 + [np.nan] + [10.2]*14
    sig = s.generate_signal(ctx(), data(prices))
    assert sig is None or isinstance(sig, Signal)

def test_on_bar_exception_swallows():
    s = MomentumStrategy()
    assert isinstance(s.on_bar(ctx(), {"bad":True}), list) and len(s.on_bar(ctx(), {"bad":True}))==0
