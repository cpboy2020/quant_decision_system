#!/usr/bin/env python3
"""
自适应令牌桶限流器 (Token Bucket + Leaky Backpressure)
机制: 突发峰值放行 → 平稳期匀速漏出 → P99延迟超标自动降频 → 防 DR 集群写入雪崩
"""

import time
import math
import logging
from prometheus_client import Gauge, Counter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


class AdaptiveTokenBucket:
    def __init__(self, capacity: int = 100, base_rate: float = 20.0):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.base_rate = base_rate
        self.current_rate = base_rate
        self.last_refill = time.perf_counter()

        # Prometheus 指标
        self.g_tokens = Gauge("etcd_sync_tokens_remaining", "Remaining sync tokens")
        self.g_rate = Gauge("etcd_sync_current_rate", "Adaptive refill rate (ops/sec)")
        self.c_dropped = Counter(
            "etcd_sync_dropped_total", "Dropped sync events due to rate limit"
        )
        self.c_passed = Counter(
            "etcd_sync_passed_total", "Sync events passed rate limit"
        )

    def try_acquire(self) -> bool:
        now = time.perf_counter()
        # 令牌补充 (Token Bucket 逻辑)
        delta = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + delta * self.current_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            self.g_tokens.set(self.tokens)
            self.c_passed.inc()
            return True
        self.c_dropped.inc()
        return False

    def apply_backpressure(self, p99_latency_ms: float, queue_depth: int = 0):
        """动态背压调节: 延迟/队列深度超标 → 指数衰减 refill_rate"""
        latency_factor = 1.0
        if p99_latency_ms > 200:
            latency_factor = 0.5
        elif p99_latency_ms > 80:
            latency_factor = 0.75
        elif p99_latency_ms < 30 and queue_depth < 5:
            latency_factor = 1.2

        # 平滑过渡防抖动
        target = self.base_rate * latency_factor
        self.current_rate += 0.1 * (target - self.current_rate)  # EMA 平滑
        self.current_rate = max(1.0, min(self.base_rate * 1.5, self.current_rate))
        self.g_rate.set(self.current_rate)


# 集成示例 (替换原 sync 循环中的直接写入)
# limiter = AdaptiveTokenBucket(capacity=150, base_rate=25)
# if limiter.try_acquire():
#     limiter.apply_backpressure(p99_ms)
#     dst.put(key, value)
