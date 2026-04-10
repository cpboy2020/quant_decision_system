#!/usr/bin/env python3
"""
K-Factor 自学习校准器: 基于历史流量分布自动计算最优 K, 并 Patch PrometheusRule CRD
"""

import os
import json
import logging
import time
import numpy as np
from scipy.stats import norm
from prometheus_api_client import PrometheusConnect
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("KFactorLearner")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
RULE_NS = os.getenv("RULE_NAMESPACE", "monitoring")
RULE_NAME = os.getenv("RULE_NAME", "webhook-adaptive-alerts")
TARGET_FPR = float(os.getenv("TARGET_FPR", "0.05"))
METRIC_QUERY = 'sum(rate(http_requests_total{path="/route"}[5m]))'


def fetch_historical_distribution() -> np.ndarray:
    prom = PrometheusConnect(url=PROM_URL, disable_ssl=True)
    end = int(time.time())
    start = end - (7 * 86400)
    res = prom.custom_query_range(
        METRIC_QUERY, start_time=start, end_time=end, step="5m"
    )
    if not res:
        return np.array([1.0])
    return np.array([float(v[1]) for v in res[0]["values"]])


def calculate_k(values: np.ndarray) -> float:
    mu, sigma = np.mean(values), np.std(values)
    if sigma < 1e-4:
        return 3.0
    # 正态假设 + 经验修正: 取 1-TARGET_FPR 分位数
    k_emp = (np.percentile(values, 100 * (1 - TARGET_FPR)) - mu) / sigma
    k_norm = norm.ppf(1 - TARGET_FPR)
    # 保守平滑: 取理论值与经验值的加权平均
    return round(0.6 * k_norm + 0.4 * max(2.5, min(k_emp, 5.5)), 2)


def patch_prometheus_rule(new_k: float):
    config.load_incluster_config()
    api = client.CustomObjectsApi()
    rule = api.get_namespaced_custom_object(
        "monitoring.coreos.com", "v1", RULE_NS, "prometheusrules", RULE_NAME
    )

    # 安全替换 K_TRAFFIC 占位符 (精准匹配表达式路径)
    rules = rule["spec"]["groups"][0]["rules"]
    patched = False
    for r in rules:
        if r.get("alert") == "WebhookTrafficSpikeAnomaly":
            old_expr = r["expr"]
            if "${K_TRAFFIC}" in old_expr:
                r["expr"] = old_expr.replace("${K_TRAFFIC}", str(new_k))
                patched = True
            break

    if not patched:
        log.warning("⚠️ 未找到 WebhookTrafficSpikeAnomaly 告警规则, 跳过 Patch")
        return

    api.replace_namespaced_custom_object(
        "monitoring.coreos.com", "v1", RULE_NS, "prometheusrules", RULE_NAME, rule
    )
    log.info(f"✅ PrometheusRule 已热更新: K_TRAFFIC = {new_k}")


def main():
    log.info(f"🔍 开始 7 日流量分布学习与 K-Factor 计算 (目标误报率: {TARGET_FPR})")
    data = fetch_historical_distribution()
    k_opt = calculate_k(data)
    log.info(
        f"📊 历史统计: μ={np.mean(data):.2f}, σ={np.std(data):.2f}, 最优 K={k_opt}"
    )
    patch_prometheus_rule(k_opt)
    log.info("✅ K-Factor 自学习周期完成")


if __name__ == "__main__":
    main()
