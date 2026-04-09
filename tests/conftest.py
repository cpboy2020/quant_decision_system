import os, sys, pytest, numpy as np, pandas as pd
from datetime import datetime
from core.interfaces import MarketContext, MarketType

@pytest.fixture(scope="session", autouse=True)
def inject_project_path():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path: sys.path.insert(0, root)
    yield
    if root in sys.path: sys.path.remove(root)

@pytest.fixture
def mock_market_context():
    def _f(symbol="000001.SZ", current_dt=None, market=MarketType.A_SHARE):
        return MarketContext(market, current_dt or datetime.utcnow(), [], {f"{symbol}_prev_close":10.0, f"{symbol}_close":10.2})
    return _f

@pytest.fixture
def mock_bar_data():
    def _f(symbol="TEST", close_series=None, **extra):
        cs = close_series or [10.0]*20
        return {"symbol":symbol, "open":cs[-1]*0.998, "high":cs[-1]*1.005, "low":cs[-1]*0.995, "close":cs[-1], "volume":100000, "close_series":cs, **extra}
    return _f
