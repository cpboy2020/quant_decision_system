#!/usr/bin/env python3
"""
多目标贝叶斯 Pareto 截流器: CTR + Latency + Error Rate 联合优化
机制: Constrained Thompson Sampling → 硬约束触发自动降级 → 安全路由回滚
"""

import os
import json
import time
import logging
import math
import requests
import numpy as np
from scipy.stats import beta as beta_dist
from fastapi import FastAPI, HTTPException

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Constrained Pareto Flow Controller")

# 配置: 硬约束阈值
THRESHOLDS = {"min_ctr": 0.30, "max_latency_ms": 200.0, "max_error_rate": 0.03}
FALLBACK_ARM = os.getenv("FALLBACK_ARM", "control")


class ParetoFlowEngine:
    def __init__(self, arms: list):
        self.arms = arms
        # 多目标共轭先验: (ctr, latency, error)
        self.alphas = {a: [1.0, 5.0, 0.5] for a in arms}
        self.betas = {a: [1.0, 5.0, 0.5] for a in arms}
        self.kappa = 1.5  # 探索-利用温度

    def record_multi_feedback(
        self, arm: str, success: bool, latency_ms: float, is_error: bool
    ):
        # CTR 更新
        self.alphas[arm][0] += success
        self.betas[arm][0] += not success
        # Latency 更新 (逆时延作为正奖励)
        lat_reward = 1.0 / (latency_ms + 1.0)
        self.alphas[arm][1] += lat_reward
        self.betas[arm][1] += 0.2
        # Error 更新
        self.alphas[arm][2] += is_error
        self.betas[arm][2] += not is_error

    def compute_pareto_allocation(self) -> tuple:
        scores, violations = {}, []
        for arm in self.arms:
            # 采样后验
            ctr = beta_dist.rvs(self.alphas[arm][0], self.betas[arm][0])
            lat = (
                beta_dist.rvs(self.alphas[arm][1], self.betas[arm][1]) * 1000.0
            )  # 映射回 ms 量级
            err = beta_dist.rvs(self.alphas[arm][2], self.betas[arm][2])

            # 硬约束检查
            if err > THRESHOLDS["max_error_rate"] or lat > THRESHOLDS["max_latency_ms"]:
                violations.append((arm, err, lat))

            # 加权标量效用 (Pareto 近似)
            utility = 0.6 * ctr - 0.25 * (lat / 1000.0) - 0.15 * err
            scores[arm] = utility

        # 约束触发降级
        if violations:
            worst, e, l = max(violations, key=lambda x: x[1] * x[2])
            logging.warning(
                f"🚨 触发硬约束降级 | Arm: {worst} | Err: {e:.3f}, Lat: {l:.0f}ms"
            )
            alloc = {
                a: (0.0 if a == worst else 0.5 / (len(self.arms) - 1))
                for a in self.arms
            }
            alloc[FALLBACK_ARM] = alloc.get(FALLBACK_ARM, 0.0) + alloc[worst]
            return alloc, {
                "degraded": True,
                "violation_arm": worst,
                "metrics": {"err": e, "lat": l},
            }

        # 正常 Thompson 分配
        exp_s = np.exp(self.kappa * np.array(list(scores.values())))
        probs = exp_s / exp_s.sum()
        return dict(zip(self.arms, np.round(probs, 4))), {
            "degraded": False,
            "scores": {a: round(s, 4) for a, s in scores.items()},
        }


engine = None


@app.on_event("startup")
def init():
    engine = ParetoFlowEngine(
        arms=os.getenv("ARMS", "control,variant_a,variant_b").split(",")
    )


@app.get("/api/allocation")
def get_weights():
    return engine.compute_pareto_allocation()[0]


@app.post("/api/feedback")
def record(arm: str, success: bool = True, latency: float = 50.0, error: bool = False):
    engine.record_multi_feedback(arm, success, latency, error)
    return {"status": "recorded"}


@app.post("/api/trigger_fallback")
def force_fallback(arm: str):
    """外部系统强制降级某变体"""
    alloc, _ = engine.compute_pareto_allocation()
    if alloc.get(arm, 0) > 0.05:
        alloc[arm] = 0.0
        alloc[FALLBACK_ARM] += alloc[arm]
        return {"action": "degraded", "allocation": alloc}
    return {"status": "ok"}


@app.post("/api/webhook_sink")
async def notify_traffic_switcher(payload: dict):
    """接收收敛/降级指令, 转发至 Envoy/K8s 路由网关"""
    webhook = os.getenv("TRAFFIC_WEBHOOK")
    if webhook:
        requests.post(webhook, json=payload, timeout=3)
    return {"status": "forwarded"}
