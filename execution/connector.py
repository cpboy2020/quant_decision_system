# execution/connector.py
import logging
import time
import threading
from typing import Dict, Any, Literal
from enum import Enum
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from core.interfaces import QuantSystemError
from execution.gateway import PaperGateway, Order

logger = logging.getLogger("GatewayConnector")

class GatewayState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"  # 心跳延迟高但未断开

class GatewayConnector:
    def __init__(self, mode: Literal["paper", "qmt", "ctp"], config: Dict[str, Any]):
        self.mode = mode
        self.config = config
        self.state = GatewayState.DISCONNECTED
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        self.gateway = None
        self._max_heartbeat_delay = 5.0  # 阈值：超过此值视为降级
        self._reconnect_count = 0

    def _build_gateway(self):
        logger.info(f"🔨 实例化网关模式：{self.mode.upper()}")
        if self.mode == "paper":
            return PaperGateway(heartbeat=10.0, max_retries=5)
        elif self.mode == "qmt":
            # 预留 QMT 实例化逻辑
            raise NotImplementedError("QMT 网关待集成")
        else:
            raise ValueError(f"不支持的网关模式：{self.mode}")

    def start(self):
        """启动网关并建立连接"""
        try:
            self.state = GatewayState.CONNECTING
            self.gateway = self._build_gateway()
            
            # 注册回调（含日志）
            self.gateway.register_callbacks(
                on_fill=self._on_fill_callback,
                on_status=self._on_status_callback,
                on_error=self._on_error_callback
            )
            
            # 连接尝试（带重试）
            if self.gateway.on_connect():
                self.state = GatewayState.CONNECTED
                logger.info(f"✅ 网关连接成功 | 模式：{self.mode}")
                self._reconnect_count = 0
                self._start_heartbeat_loop()
                return True
            else:
                raise QuantSystemError("on_connect 返回 False")
        except Exception as e:
            logger.critical(f"❌ 网关启动失败 | 错误：{e}", exc_info=True)
            self.state = GatewayState.DISCONNECTED
            return False

    def stop(self):
        """优雅停止"""
        logger.info("🛑 正在停止网关...")
        self._stop_event.set()
        if self.gateway:
            try:
                self.gateway.on_disconnect()
                logger.info("🔌 网关连接已断开")
            except Exception as e:
                logger.warning(f"断开连接异常：{e}")
        self.state = GatewayState.DISCONNECTED

    def _start_heartbeat_loop(self):
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True, name="Heartbeat")
        self._heartbeat_thread.start()

    def _heartbeat_worker(self):
        """心跳监控与自动重连线程"""
        interval = 10.0  # 默认 10s
        consecutive_failures = 0
        max_failures = 3

        while not self._stop_event.is_set():
            if self.state == GatewayState.CONNECTED or self.state == GatewayState.DEGRADED:
                try:
                    start_time = time.time()
                    # 调用网关底层 Ping 方法（假设存在，若无则模拟）
                    self.gateway._ping() if hasattr(self.gateway, '_ping') else time.sleep(0.01)
                    latency = time.time() - start_time

                    if latency > self._max_heartbeat_delay:
                        self.state = GatewayState.DEGRADED
                        logger.warning(f"⚠️ 网关响应迟缓 | 延迟：{latency:.3f}s > 阈值：{self._max_heartbeat_delay}s")
                    else:
                        if self.state == GatewayState.DEGRADED:
                            self.state = GatewayState.CONNECTED
                            logger.info(f"✅ 网关恢复正常 | 延迟：{latency:.3f}s")
                        consecutive_failures = 0  # 重置

                except Exception as e:
                    consecutive_failures += 1
                    logger.error(f"💓 心跳失败 ({consecutive_failures}/{max_failures}) | 原因：{e}")
                    
                    if consecutive_failures >= max_failures:
                        self._handle_disconnect_and_reconnect()
                        consecutive_failures = 0  # 重连后重置计数
            time.sleep(interval)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True
    )
    def _handle_disconnect_and_reconnect(self):
        """断线重连逻辑（指数退避）"""
        logger.warning("🔄 触发断线重连流程...")
        self.state = GatewayState.CONNECTING
        self._reconnect_count += 1
        
        # 重建网关实例以防状态死锁
        self.gateway = self._build_gateway()
        self.gateway.register_callbacks(on_fill=self._on_fill_callback, on_status=self._on_status_callback, on_error=self._on_error_callback)
        
        if self.gateway.on_connect():
            logger.info("🎉 网关重连成功！")
            self.state = GatewayState.CONNECTED
            self._reconnect_count = 0
        else:
            logger.error("💀 重连尝试失败，将触发下一次重试")
            raise QuantSystemError("重连失败")

    # --- 回调函数 ---
    def _on_fill_callback(self, order: Order):
        logger.info(f"📈 成交通知 | {order.symbol} {order.direction} @ {order.avg_fill_price} x {order.filled_volume} | 委托 ID: {order.order_id}")

    def _on_status_callback(self, order: Order):
        if order.status.value in ['REJECTED', 'CANCELLED']:
            logger.warning(f"⚠️ 订单状态变更 | {order.order_id} -> {order.status.value} | 原因：{order.meta.get('reason', 'N/A')}")
        else:
            logger.debug(f"🔄 订单状态 | {order.order_id} -> {order.status.value}")

    def _on_error_callback(self, order: Order, msg: str):
        logger.error(f"❌ 网关错误 | {order.order_id} | {msg}")

    def send_order(self, order): return self.gateway.submit_order(order)
    def cancel_order(self, oid): return self.gateway.cancel_order(oid)