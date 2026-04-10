#!/usr/bin/env python3
"""
Grafana A/B 显著性检验服务 (Beta-Binomial 共轭 + 自动流量切换)
逻辑: 先验 ~ Beta(1,1) → 后验 ~ Beta(1+clicks, 1+impressions-clicks) → 计算 P(A>B) → 触发 Webhook
"""

import os
import json
import time
import logging
import math
import numpy as np
from scipy.stats import beta as beta_dist
from fastapi import FastAPI
import requests

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Bayesian AB Analyzer")

# Webhook 配置
SWITCH_URL = os.getenv("TRAFFIC_SWITCH_WEBHOOK", "http://config-syncer:8080/switch")
CONFIDENCE_THRESHOLD = 0.95


@app.get("/api/bayesian-metrics")
async def get_metrics(variant_a: str = "A", variant_b: str = "B"):
    # 实际生产应从 Prometheus/ClickHouse 拉取实时数据
    # 此处模拟: A=(imp=5000, click=420), B=(imp=5000, click=380)
    a_imp, a_clk = 5000, 420
    b_imp, b_clk = 5000, 380

    # 共轭后验
    post_a = beta_dist(a_clk + 1, a_imp - a_clk + 1)
    post_b = beta_dist(b_clk + 1, b_imp - b_clk + 1)

    # 蒙特卡洛计算 P(A > B)
    sims = 200_000
    p_win = np.mean(post_a.rvs(sims) > post_b.rvs(sims))

    # 提升幅度期望
    lift = (a_clk / a_imp - b_clk / b_imp) / (b_clk / b_imp)

    return {
        "variant_a": {
            "impressions": a_imp,
            "clicks": a_clk,
            "ctr": round(a_clk / a_imp, 4),
        },
        "variant_b": {
            "impressions": b_imp,
            "clicks": b_clk,
            "ctr": round(b_clk / b_imp, 4),
        },
        "p_a_wins": round(float(p_win), 4),
        "expected_lift": round(float(lift * 100), 2),
        "decision_ready": bool(
            p_win > CONFIDENCE_THRESHOLD or p_win < 1 - CONFIDENCE_THRESHOLD
        ),
    }


@app.post("/api/evaluate-and-switch")
async def auto_switch():
    metrics = await get_metrics()
    if not metrics["decision_ready"]:
        return {"status": "insufficient_data", "p_value": metrics["p_a_wins"]}

    winner = "A" if metrics["p_a_wins"] > 0.5 else "B"
    conf = metrics["p_a_wins"] if winner == "A" else 1 - metrics["p_a_wins"]

    # 触发流量切换 Webhook (K8s/Envoy 路由更新)
    payload = {"winner": winner, "confidence": conf, "timestamp": time.time()}
    requests.post(SWITCH_URL, json=payload, timeout=5)
    logging.info(f"🚀 已自动切换流量至 Winner: {winner} (置信度: {conf:.2%})")
    return {"status": "switched", "winner": winner, "confidence": conf}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9098, log_level="info")
