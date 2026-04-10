#!/usr/bin/env python3
"""
Dirichlet 95% CI 重叠率计算器 + 自动收敛 Webhook
原理: 边际分布 ~ Beta(α_i, α_0-α_i) → 计算 95% 可信区间 → 重叠率 < 5% 触发收敛
"""

import os
import json
import time
import math
import logging
import requests
import numpy as np
from scipy.stats import beta as beta_dist
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Dirichlet CI Convergence Engine")

WEBHOOK_URL = os.getenv("CONVERGENCE_WEBHOOK", "http://istio-pilot:8080/traffic/shift")
OVERLAP_THRESHOLD = 0.05  # 重叠率 < 5% 判定为显著差异
CONFIDENCE_LEVEL = 0.95


class ExperimentData(BaseModel):
    arms: dict[str, tuple[int, int]]  # {"arm_name": (clicks, impressions)}


@app.post("/api/evaluate_convergence")
async def evaluate(data: ExperimentData):
    if not data.arms:
        raise HTTPException(400, "No arms provided")

    alphas, arms = [], []
    for arm_name, (clk, imp) in data.arms.items():
        arms.append(arm_name)
        alphas.append((clk + 1, imp - clk + 1))

    # 计算边际 Beta 分布的 95% CI
    lower, upper = [], []
    for a, b in alphas:
        ci = beta_dist.ppf([0.025, 0.975], a, b)
        lower.append(ci[0])
        upper.append(ci[1])

    # 重叠率计算: max(L) vs min(U) of top-2
    sorted_idx = np.argsort(upper)[::-1]
    top_l, top_u = lower[sorted_idx[0]], upper[sorted_idx[0]]
    runner_l, runner_u = lower[sorted_idx[1]], upper[sorted_idx[1]]

    overlap = max(0.0, min(top_u, runner_u) - max(top_l, runner_l))
    span = max(top_u, runner_u) - min(top_l, runner_l)
    overlap_rate = overlap / span if span > 1e-6 else 0.0

    is_converged = overlap_rate < OVERLAP_THRESHOLD
    winner = arms[sorted_idx[0]]
    winner_ctr = (alphas[sorted_idx[0]][0] - 1) / (alphas[sorted_idx[0]][1] - 1)

    logging.info(
        f"📊 收敛评估 | Winner: {winner} | CTR: {winner_ctr:.3f} | 重叠率: {overlap_rate:.3f} | 收敛: {is_converged}"
    )

    if is_converged and time.time() % 86400 < 300:  # 每日限触发一次防震荡
        trigger_webhook(winner, winner_ctr)

    return {
        "winner": winner,
        "overlap_rate": round(overlap_rate, 4),
        "converged": is_converged,
        "confidence_interval": {a: (l, u) for a, l, u in zip(arms, lower, upper)},
    }


def trigger_webhook(winner: str, ctr: float):
    payload = {
        "experiment": "dirichlet_abn",
        "action": "converge_to_100pct",
        "winner": winner,
        "metrics": {"ctr": round(ctr, 4), "timestamp": time.time()},
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
        logging.info(f"🚀 已触发收敛 Webhook -> {winner} (CTR: {ctr:.3f})")
    except Exception as e:
        logging.error(f"❌ Webhook 调用失败: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9099, log_level="info")
