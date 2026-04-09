import logging
import time
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential
from diskcache import Cache
from core.interfaces import DataProvider, MarketType, QuantSystemError

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, max_calls=50, period=60):
        self.max_calls, self.period, self._calls = max_calls, period, []
    def acquire(self):
        now = time.time()
        self._calls = [t for t in self._calls if now - t < self.period]
        if len(self._calls) >= self.max_calls:
            time.sleep(self.period - (now - self._calls[0]) + 0.1)
        self._calls.append(time.time())

class iFinDDataProvider(DataProvider):
    def __init__(self, user, password, license_path, cache_dir="./cache/ifind", rate_limit=50, rate_period=60):
        self.user, self.password, self.license_path = user, password, license_path
        self.cache, self.limiter = Cache(cache_dir), RateLimiter(rate_limit, rate_period)
        self._login()
    def _login(self):
        try:
            from iFinDPy import ths_login
            err = ths_login(self.user, self.password, self.license_path)
            if err != 0: raise QuantSystemError(f"iFinD登录失败 code:{err}")
            logger.info("✅ iFinD 初始化成功")
        except ImportError: raise QuantSystemError("请安装 iFinDPy 及同花顺终端")
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _safe_api_call(self, api_func, **kwargs):
        self.limiter.acquire()
        df, err_msg = api_func(**kwargs)
        if df is None or (isinstance(df, pd.DataFrame) and df.empty): return pd.DataFrame()
        return df
    def fetch_ohlcv(self, symbol, timeframe, start, end, adjust=2):
        from iFinDPy import ths_HistoryQuotes
        df = self._safe_api_call(ths_HistoryQuotes, thscode=symbol, indicator='open,high,low,close,volume,amount',
                                 startdate=start.strftime('%Y-%m-%d'), enddate=end.strftime('%Y-%m-%d'),
                                 period=timeframe, adjustflag=str(adjust))
        if not df.empty:
            df = df.rename(columns={'time': 'timestamp'}).set_index('timestamp').sort_index()
            for c in ['open','high','low','close','volume']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    def get_trading_calendar(self, market, start, end):
        from iFinDPy import ths_DateSerial
        ref = '000001.SH' if market==MarketType.A_SHARE else 'IF888888.IF'
        df = self._safe_api_call(ths_DateSerial, thscode=ref, indicator='trade_date',
                                 startdate=start.strftime('%Y-%m-%d'), enddate=end.strftime('%Y-%m-%d'))
        return [d for d in pd.to_datetime(df.iloc[:,0]) if start <= d <= end] if not df.empty else []
    def close(self): self.cache.close()
