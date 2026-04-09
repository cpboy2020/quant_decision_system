import logging
import threading
from typing import Optional
from prometheus_client import Counter, Gauge, Histogram, start_http_server, CollectorRegistry

logger = logging.getLogger(__name__)

class MetricsCollector:
    def __init__(self, port: int = 9090):
        self.port = port
        self.registry = CollectorRegistry()
        self.order_latency = Histogram("order_latency_seconds", "订单延迟", registry=self.registry)
        self.fill_rate = Gauge("order_fill_rate_pct", "成交率", registry=self.registry)
        self.portfolio_equity = Gauge("portfolio_equity_usd", "组合净值", registry=self.registry)
        self.max_drawdown = Gauge("max_drawdown_pct", "最大回撤", registry=self.registry)
        self.signal_ic = Gauge("model_rolling_ic", "滚动IC", registry=self.registry)
        self.system_health = Gauge("system_health_status", "健康状态", registry=self.registry)
        self._stop_event = threading.Event()

    def start_server(self) -> None:
        try:
            start_http_server(self.port, registry=self.registry)
            logger.info(f"📊 Prometheus Metrics 已暴露 | http://0.0.0.0:{self.port}/metrics")
        except OSError as e:
            logger.critical(f"❌ 端口 {self.port} 绑定失败: {e}")
            raise

    def stop(self) -> None:
        self._stop_event.set()
