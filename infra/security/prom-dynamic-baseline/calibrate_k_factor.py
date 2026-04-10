#!/usr/bin/env python3
"""
K-Factor 动态校准器 (基于历史 FPR 目标反推 σ 倍数)
原理: 假设指标近似正态, 通过历史分位数拟合最优 k, 使误报率(FPR) ≤ 5%
"""

import os
import json
import logging
import numpy as np
import requests
from scipy.stats import norm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("KCalibrator")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
TARGET_FPR = float(os.getenv("TARGET_FPR", "0.05"))
OUTPUT_PATH = "/opt/config/k_factors.json"


def fetch_baseline_data(metric: str) -> np.ndarray:
    q = f"sum(rate(http_requests_total{{path='/route'}}[5m]))"
    r = requests.get(
        f"{PROM_URL}/api/v1/query_range",
        params={
            "query": q,
            "start": int(os.getenv("START_TS", "now()-7d")),
            "end": "now",
            "step": "5m",
            "timeout": "10s",
        },
        timeout=15,
    )
    vals = [
        float(v[1])
        for v in r.json().get("data", {}).get("result", [{}])[0].get("values", [])
    ]
    return np.array(vals)


def compute_optimal_k(values: np.ndarray) -> float:
    mu, sigma = np.mean(values), np.std(values)
    if sigma < 1e-6:
        return 3.0
    # 目标: P(X > μ + kσ) = FPR → k = norm.ppf(1 - FPR)
    # 修正重尾分布: 使用历史 95% 分位数 / σ
    k_empirical = (np.percentile(values, 100 * (1 - TARGET_FPR)) - mu) / sigma
    return max(2.0, min(5.0, round(k_empirical, 2)))


def main():
    data = fetch_baseline_data("rps")
    k = compute_optimal_k(data)
    config = {
        "k_traffic": k,
        "target_fpr": TARGET_FPR,
        "sample_size": len(data),
        "mu": round(float(np.mean(data)), 2),
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(config, f, indent=2)
    log.info(
        f"✅ 最优 K-Factor 计算完成: {k} (基于 {len(data)} 样本, 目标误报率: {TARGET_FPR*100}%)"
    )


if __name__ == "__main__":
    main()
