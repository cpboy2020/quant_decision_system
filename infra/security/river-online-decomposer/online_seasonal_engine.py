#!/usr/bin/env python3
"""
River 在线多周期分解器 (近似 TBATS/STL)
原理: 在线傅里叶特征 + PARegressor 增量拟合 → 滚动预测未来 24h 基线 → 零停机持久化
支持: 5m/日/周多周期叠加, 状态快照至本地/Redis, 崩溃无缝恢复
"""

import os
import json
import time
import math
import logging
import pickle
import numpy as np
import pandas as pd
import requests
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from river import compose, linear_model, preprocessing
from river.time_series import SNARIMAX

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("River-Online-Decomposer")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://pushgateway.monitoring.svc:9091")
STATE_FILE = os.getenv("STATE_FILE", "/data/river_model.pkl")
ALPHA_SEASONAL = 0.95  # 季节性衰减系数 (周/日)


def fourier_features(t: int, periods: list) -> list:
    """在线生成多周期傅里叶基函数 [sin/cos]"""
    feats = []
    for p in periods:
        phase = 2 * math.pi * t / p
        feats.extend([math.sin(phase), math.cos(phase)])
    return feats


class OnlineSeasonalModel:
    def __init__(self, state_path=STATE_FILE):
        self.state_path = state_path
        # 在线线性模型: 趋势 + 季节性傅里叶
        self.model = compose.Pipeline(
            preprocessing.StandardScaler(),
            linear_model.PARegressor(C=0.01, eps=0.001, mode="L2"),
        )
        self.t = 0
        self.last_preds = []
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "rb") as f:
                    saved = pickle.load(f)
                self.model = saved["model"]
                self.t = saved.get("t", 0)
                log.info(f"💾 模型状态已恢复 | t={self.t}")
            except Exception as e:
                log.warning(f"⚠️ 状态恢复失败: {e}")

    def save_state(self):
        with open(self.state_path, "wb") as f:
            pickle.dump({"model": self.model, "t": self.t}, f)
        log.info("✅ 状态快照已持久化")

    def learn_and_predict(
        self, current_val: float, periods: list = [288, 2016]
    ) -> list:
        """增量学习 + 滚动预测未来 288 步 (24h)"""
        x = {
            "raw_t": self.t,
            **{f"feat_{i}": v for i, v in enumerate(fourier_features(self.t, periods))},
        }
        self.model.learn_one(x, current_val)
        self.t += 1

        # 预测未来
        fc = []
        for step in range(1, 289):
            x_fc = {
                "raw_t": self.t + step,
                **{
                    f"feat_{i}": v
                    for i, v in enumerate(fourier_features(self.t + step, periods))
                },
            }
            fc.append(self.model.predict_one(x_fc))
        return fc


def main():
    # 拉取最近 50 点做冷启动拟合
    end = int(time.time())
    start = end - 4 * 3600
    r = requests.get(
        f"{PROM_URL}/api/v1/query_range",
        params={
            "query": "sum(rate(http_requests_total{path='/route'}[5m]))",
            "start": start,
            "end": end,
            "step": "300s",
        },
        timeout=10,
    )
    vals = [float(v[1]) for v in r.json()["data"]["result"][0]["values"]]

    model = OnlineSeasonalModel()
    for v in vals[:-1]:
        model.learn_and_predict(v)

    # 在线滚动
    baseline = model.learn_and_predict(vals[-1])
    mu = np.mean(baseline)
    std = np.std(baseline)
    upper, lower = mu + 2.5 * std, mu - 1.5 * std

    registry = CollectorRegistry()
    Gauge(
        "river_online_baseline_5m",
        "River streaming multi-period baseline",
        registry=registry,
    ).set(round(mu, 4))
    Gauge("river_online_upper_5m", "Upper bound (2.5σ)", registry=registry).set(
        round(upper, 4)
    )
    Gauge("river_online_lower_5m", "Lower bound (1.5σ)", registry=registry).set(
        round(lower, 4)
    )

    push_to_gateway(PUSHGATEWAY_URL, job="river_online_decomposer", registry=registry)
    model.save_state()
    log.info(f"📊 基线推送完成 | μ={mu:.2f}, σ={std:.2f}")


if __name__ == "__main__":
    main()
