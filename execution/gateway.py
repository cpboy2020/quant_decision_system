import logging, time, threading, uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from core.interfaces import ExecutionGateway, QuantSystemError
logger = logging.getLogger(__name__)

class OrderStatus(Enum): PENDING="pending"; SUBMITTED="submitted"; PARTIAL="partial"; FILLED="filled"; CANCELLED="cancelled"; REJECTED="rejected"
VALID_TRANS = {OrderStatus.PENDING:[OrderStatus.SUBMITTED, OrderStatus.REJECTED], OrderStatus.SUBMITTED:[OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED], OrderStatus.PARTIAL:[OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]}

@dataclass
class Order: order_id=str(uuid.uuid4().hex[:12]); symbol=""; direction=""; order_type="LIMIT"; price=0.0; volume=0; status=OrderStatus.PENDING; filled_volume=0; avg_fill_price=0.0; broker_order_id=""; created_at=datetime.now(); updated_at=datetime.now(); meta={}

class OrderStateMachine:
    def __init__(self): self.orders={}; self._lock=threading.RLock()
    def create(self, o):
        with self._lock:
            if o.order_id in self.orders: raise QuantSystemError(f"重复ID: {o.order_id}")
            self.orders[o.order_id]=o; return o.order_id
    def update(self, oid, new_status, **kw):
        with self._lock:
            o=self.orders.get(oid)
            if not o: raise QuantSystemError(f"订单不存在: {oid}")
            if new_status not in VALID_TRANS.get(o.status, []): raise QuantSystemError(f"非法跃迁: {o.status}->{new_status}")
            o.status=new_status; o.updated_at=datetime.now()
            for k,v in kw.items(): setattr(o,k,v)
            return o

class BaseGateway(ExecutionGateway):
    def __init__(self, name, heartbeat=10.0, max_retries=5):
        self.name, self.heartbeat, self.max_retries = name, heartbeat, max_retries
        self.state_machine = OrderStateMachine()
        self._connected, self._stop = False, threading.Event()
        self._callbacks = {"on_fill": None, "on_status": None, "on_error": None}
        self.logger = logging.getLogger(f"Gateway.{name}")

    def register_callbacks(self, on_fill=None, on_status=None, on_error=None):
        self._callbacks.update(on_fill=on_fill, on_status=on_status, on_error=on_error)

    def on_connect(self):
        self.logger.info(f"🔗 正在连接 {self.name} 网关...")
        self._connected = True
        self.logger.info(f"✅ {self.name} 网关初始化成功 | 心跳间隔: {self.heartbeat}s")
        return True

    def on_disconnect(self): self._stop.set(); self._connected=False; self.logger.info(f"🔌 {self.name} 已安全断开")
    def submit_order(self, order): raise NotImplementedError
    def cancel_order(self, order_id): raise NotImplementedError
    def get_positions(self): return {}

class PaperGateway(BaseGateway):
    def __init__(self, **kw): super().__init__(name="PAPER", **kw); self.positions={}; self.cash=1_000_000.0
    def submit_order(self, order):
        oid = self.state_machine.create(order); order.status=OrderStatus.SUBMITTED
        time.sleep(0.02)
        if order.direction=="BUY" and self.cash < order.price*order.volume:
            self.state_machine.update(oid, OrderStatus.REJECTED, meta={"reason":"INSUFFICIENT_CASH"})
            return oid
        fv = order.volume; ap = order.price*(1.0005 if order.direction=="BUY" else 0.9995)
        comm = ap*fv*(0.001 if order.direction=="SELL" else 0.0003)
        self.state_machine.update(oid, OrderStatus.FILLED, filled_volume=fv, avg_fill_price=ap)
        if order.direction=="BUY": self.cash-=(comm+ap*fv); self.positions[order.symbol]=self.positions.get(order.symbol,0)+fv
        else: self.cash+=(ap*fv-comm); self.positions[order.symbol]=self.positions.get(order.symbol,0)-fv
        if self._callbacks["on_fill"]: self._callbacks["on_fill"](order)
        return oid
    def cancel_order(self, oid): 
        try: self.state_machine.update(oid, OrderStatus.CANCELLED); return True
        except: return False
    def get_positions(self): return {"positions":dict(self.positions), "cash":self.cash}
