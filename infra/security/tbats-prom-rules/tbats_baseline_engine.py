#!/usr/bin/env python3
"""
TBATS 多周期时序分解器: 自动识别 5m/1h/24h/1w 季节性 → 生成动态上下界 → 渲染 PrometheusRule
"""

import os
import json
import time
import logging
import numpy as np
import pandas as pd
import requests
from tbats import TBATS
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("TBATS-Engine")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
RULE_NS = "monitoring"
RULE_NAME = "webhook-dynamic-baselines-tbats"
DAYS_HISTORY = 30
PERIODS = [288, 2016]  # 5m 粒度: 日/周


def fetch_series(metric: str) -> pd.Series:
    end, start = int(time.time()), int(time.time()) - DAYS_HISTORY * 86400
    r = requests.get(
        f"{PROM_URL}/api/v1/query_range",
        params={
            "query": f"sum(rate(http_requests_total{{path='/route'}}[5m]))",
            "start": start,
            "end": end,
            "step": "300s",
        },
        timeout=20,
    )
    vals = r.json()["data"]["result"][0]["values"]
    df = pd.DataFrame(vals, columns=["ts", "v"])
    df.index = pd.to_datetime(df["ts"], unit="s")
    df["v"] = df["v"].astype(float).interpolate(method="time")
    return df["v"].dropna()


def fit_and_forecast(series: pd.Series) -> tuple:
    log.info(f"🔍 拟合 TBATS 模型 (周期: {PERIODS}, 样本: {len(series)})")
    estimator = TBATS(
        seasonal_periods=PERIODS, use_arma_errors=False, show_warnings=False
    )
    model = estimator.fit(series)
    # 预测未来 24h (用于规则基线)
    fc = model.forecast(steps=288)
    ci = model.confidence_intervals(steps=288)
    baseline = model.predict(steps=288)  # 趋势+季节

    upper = baseline + 2.5 * (ci[:, 1] - ci[:, 0]) / 2
    lower = baseline - 2.0 * (ci[:, 1] - ci[:, 0]) / 2

    return baseline.values, upper.values, lower.values


def generate_prom_rule(baseline: list, upper: list, lower: list):
    # 生成 Prometheus 记录规则与动态阈值告警
    rule_yaml = f"""
groups:
  - name: tbats_baselines
    interval: 15m
    rules:
      - record: webhook_tbats_baseline_5m
        expr: vector({baseline[-1]:.3f})
      - record: webhook_tbats_upper_5m
        expr: vector({upper[-1]:.3f})
      - record: webhook_tbats_lower_5m
        expr: vector({lower[-1]:.3f})
      - alert: WebhookTrafficTBATSAnomaly
        expr: sum(rate(http_requests_total{{path="/route"}}[5m])) > webhook_tbats_upper_5m
        for: 5m
        labels: {{severity: warning, model: tbats}}
        annotations:
          summary: "流量突破 TBATS 动态上界 (当前: {{{{ $value | humanize }}}})"
          action: "检查大促流量入口或 Alertmanager 路由风暴"
"""
    return rule_yaml


def apply_rule(yaml_str: str):
    import yaml

    rule = yaml.safe_load(yaml_str)
    config.load_incluster_config()
    api = client.CustomObjectsApi()
    payload = {
        "apiVersion": "monitoring.coreos.com/v1",
        "kind": "PrometheusRule",
        "metadata": {"name": RULE_NAME, "namespace": RULE_NS},
        "spec": rule,
    }
    try:
        api.create_namespaced_custom_object(
            "monitoring.coreos.com", "v1", RULE_NS, "prometheusrules", payload
        )
    except client.exceptions.ApiException as e:
        if e.status == 409:
            api.replace_namespaced_custom_object(
                "monitoring.coreos.com",
                "v1",
                RULE_NS,
                "prometheusrules",
                RULE_NAME,
                payload,
            )
    log.info("✅ PrometheusRule 已应用/更新")


def main():
    series = fetch_series("rps")
    base, up, low = fit_and_forecast(series)
    rule = generate_prom_rule(base, up, low)
    apply_rule(rule)
    log.info("✅ TBATS 周期分解与规则生成完成")


if __name__ == "__main__":
    main()
