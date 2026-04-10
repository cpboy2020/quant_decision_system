#!/usr/bin/env python3
"""
etcd 同步延迟监控桥: 集成 prometheus_client, 暴露同步延迟直方图与成功率
"""

import os
import time
import logging
import etcd3
from prometheus_client import Histogram, Counter, Gauge, start_http_server
import threading

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("EtcdSyncBridge-Metrics")

# Prometheus 指标
SYNC_LATENCY = Histogram(
    "etcd_sync_latency_seconds",
    "Latency for etcd cross-cluster sync",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
)
SYNC_TOTAL = Counter("etcd_sync_events_total", "Total sync events", ["status"])
QUEUE_DEPTH = Gauge("etcd_sync_queue_depth", "Current watch queue depth")


class MetricsSyncBridge:
    def __init__(self, src_host, dst_host, watch_prefix, dr_prefix):
        self.src = etcd3.client(host=src_host, port=2379)
        self.dst = etcd3.client(host=dst_host, port=2379)
        self.watch_prefix = watch_prefix
        self.dr_prefix = dr_prefix

    def sync_event(self, key, value, revision, is_delete):
        dr_key = key.replace(self.watch_prefix, self.dr_prefix, 1)
        start = time.perf_counter()
        try:
            if is_delete:
                self.dst.delete(dr_key)
            else:
                self.dst.put(dr_key, value)
            SYNC_LATENCY.observe(time.perf_counter() - start)
            SYNC_TOTAL.labels(status="success").inc()
            log.info(
                f"✅ 同步成功 | Key: {key} | 延迟: {time.perf_counter()-start:.4f}s"
            )
        except Exception as e:
            SYNC_TOTAL.labels(status="error").inc()
            log.error(f"❌ 同步失败 | {e}")

    def start(self):
        log.info(f"👀 启动带指标暴露的同步桥 | 监听: {self.watch_prefix}")
        start_http_server(9110)  # 暴露指标至 :9110/metrics

        events_iter, cancel = self.src.watch_prefix(self.watch_prefix)
        for event in events_iter:
            QUEUE_DEPTH.set(
                len(
                    list(
                        self.src.watch_prefix(
                            self.watch_prefix, start_revision=event.mod_revision + 1
                        )
                    )[0]
                )
            )
            self.sync_event(
                event.key.decode(), event.value, event.mod_revision, event.deleted
            )


if __name__ == "__main__":
    MetricsSyncBridge(
        src_host=os.getenv("SRC_ETCD", "etcd-primary.svc"),
        dst_host=os.getenv("DST_ETCD", "etcd-dr.svc"),
        watch_prefix="/river/online_decomposer/",
        dr_prefix="/dr/river/online_decomposer/",
    ).start()
