#!/usr/bin/env python3
"""
Optuna 在线限流参数搜索器 (P99延迟 × 丢弃率 联合惩罚)
原理: 拉取 7d 历史背压曲线 → TPE 采样 (capacity, base_rate) → 向量化仿真评估 → Patch ConfigMap
"""

import os
import json
import time
import logging
import numpy as np
import optuna
from prometheus_api_client import PrometheusConnect
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("OptunaRateLimiter")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
CM_NS = "istio-system"
CM_NAME = "etcd-limiter-config"
HOURS_HISTORY = 48


class BackpressureSimulator:
    def __init__(self):
        self.prom = PrometheusConnect(url=PROM_URL, disable_ssl=True)
        self.fetch_historical_metrics()

    def fetch_historical_metrics(self):
        end = int(time.time())
        start = end - HOURS_HISTORY * 3600
        lat_q = "histogram_quantile(0.99, sum(rate(etcd_sync_latency_seconds_bucket[5m])) by (le))"
        drop_q = "sum(rate(etcd_sync_dropped_total[5m]))"

        lat_res = self.prom.custom_query_range(lat_q, start, end, "300")
        drop_res = self.prom.custom_query_range(drop_q, start, end, "300")

        self.p99 = np.array([float(v[1]) for v in lat_res[0]["values"]])
        self.drops = np.array([float(v[1]) for v in drop_res[0]["values"]])
        log.info(
            f"📥 已加载 {len(self.p99)} 个 5m 粒度背压样本 | P99 μ={self.p99.mean():.3f}s, Drops μ={self.drops.mean():.2f}/s"
        )

    def simulate_objective(self, trial: optuna.Trial) -> float:
        cap = trial.suggest_int("capacity", 50, 600, step=10)
        rate = trial.suggest_float("base_rate", 5.0, 60.0, log=True)

        # 向量化令牌桶仿真
        tokens = np.full_like(self.p99, cap, dtype=float)
        arrival = self.drops + rate * 0.8  # 假设实际到达率略低于设定值（留缓冲）
        consumed = np.minimum(arrival, tokens)
        tokens = tokens - consumed + np.maximum(arrival - tokens, 0) * 0.2  # 漏桶回填
        tokens = np.clip(tokens, 0, cap)

        # 惩罚函数: 延迟超标权重 3.0, 丢弃率权重 5.0 (零容忍)
        latency_pen = np.sum(np.maximum(self.p99 - 0.15, 0)) * 3.0
        drop_pen = np.sum(np.maximum(consumed - rate, 0)) * 5.0
        return latency_pen + drop_pen


def patch_configmap(params: dict):
    config.load_incluster_config()
    api = client.CoreV1Api()
    try:
        api.patch_namespaced_config_map(
            CM_NAME, CM_NS, body={"data": json.dumps(params)}
        )
        log.info(
            f"✅ ConfigMap {CM_NAME} 已热更新 | capacity={params['capacity']}, rate={params['base_rate']:.2f}"
        )
    except Exception as e:
        log.error(f"❌ Patch 失败: {e}")


def main():
    log.info(f"🔍 启动 TPE 搜索 | 历史窗口: {HOURS_HISTORY}h")
    sim = BackpressureSimulator()
    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=42)
    )
    study.optimize(
        sim.simulate_objective, n_trials=80, n_jobs=-1, show_progress_bar=True
    )

    best = study.best_params
    log.info(f"🎯 最优参数发现: {best} | Loss: {study.best_value:.2f}")
    patch_configmap(best)


if __name__ == "__main__":
    main()
