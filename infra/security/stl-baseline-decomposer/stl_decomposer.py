#!/usr/bin/env python3
"""
STL 多周期基线分解器: 趋势 + 季节(日/周) + 残差 → 动态基线 → 推送 Pushgateway
适用于: 流量 RPS、请求延迟、错误率等具有强周期性的时序指标
"""

import os
import json
import time
import logging
import numpy as np
import pandas as pd
import requests
from statsmodels.tsa.seasonal import STL
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("STL-Decomposer")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
PUSHGATEWAY_URL = os.getenv("PUSHGATEWAY_URL", "http://pushgateway.monitoring.svc:9091")
METRIC = 'sum(rate(http_requests_total{path="/route"}[5m]))'
JOB_NAME = "stl_baseline_decomposer"
DAYS_BACK = 28  # 覆盖 4 周周期


def fetch_metric() -> pd.Series:
    end = int(time.time())
    start = end - (DAYS_BACK * 86400)
    params = {"query": METRIC, "start": start, "end": end, "step": "300s"}  # 5m 间隔
    r = requests.get(f"{PROM_URL}/api/v1/query_range", params=params, timeout=15)
    vals = r.json().get("data", {}).get("result", [{}])[0].get("values", [])
    if not vals:
        return pd.Series(dtype=float)

    df = pd.DataFrame(vals, columns=["ts", "v"]).set_index("ts")
    df.index = pd.to_datetime(df.index, unit="s")
    return df["v"].astype(float).fillna(0.0)


def compute_stl_baseline(series: pd.Series) -> dict:
    # 5m 数据日周期点数为 288。STL 支持 robust 模式抗异常值
    stl = STL(series, period=288, robust=True)
    res = stl.fit()

    trend = res.trend
    seasonal = res.seasonal
    residual = res.resid
    std_resid = residual.std()

    # 动态基线: μ = trend + seasonal + k*σ_resid (k=2.0 for ~95% CI)
    baseline = trend + seasonal + 2.0 * std_resid

    return {
        "baseline_last": round(baseline.iloc[-1], 4),
        "trend_slope": round(trend.diff().iloc[-1], 4),
        "seasonal_amp": round((seasonal.max() - seasonal.min()) / 2, 4),
        "residual_std": round(std_resid, 4),
    }


def push_to_pushgateway(baseline: dict):
    registry = CollectorRegistry()
    Gauge(
        "stl_dynamic_baseline",
        "STL computed dynamic baseline threshold",
        ["metric", "period"],
        registry=registry,
    ).set(baseline["baseline_last"])
    Gauge(
        "stl_trend_slope_5m", "5m trend direction", ["metric"], registry=registry
    ).set(baseline["trend_slope"])
    Gauge(
        "stl_seasonal_amplitude",
        "Seasonal swing magnitude",
        ["metric"],
        registry=registry,
    ).set(baseline["seasonal_amp"])
    Gauge("stl_residual_std", "Noise level", ["metric"], registry=registry).set(
        baseline["residual_std"]
    )
    push_to_gateway(PUSHGATEWAY_URL, job=JOB_NAME, registry=registry)
    log.info("✅ 基线指标已推送至 Pushgateway")


def main():
    log.info(f"🔍 拉取 {DAYS_BACK} 天时序数据...")
    series = fetch_metric()
    if len(series) < 300:
        log.warning("⚠️ 数据不足 300 点, 跳过 STL 分解")
        return

    baseline = compute_stl_baseline(series)
    log.info(
        f"📊 STL 分解完成 | Baseline: {baseline['baseline_last']} | 趋势: {baseline['trend_slope']}/5m | 季节性振幅: {baseline['seasonal_amp']}"
    )
    push_to_pushgateway(baseline)


if __name__ == "__main__":
    main()
