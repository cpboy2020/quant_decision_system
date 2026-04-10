#!/usr/bin/env python3
"""
Dirichlet 多变量 A/B/n 实验引擎 (Thompson Sampling + 指数收敛)
原理: 后验 ~ Dir(α), 采样 θ ~ Dir(α), 流量按 softmax(κ*θ) 分配
      κ 随时间指数增长, 实现 Exploration → Exploitation 平滑过渡
"""

import os
import json
import time
import math
import logging
import numpy as np
from scipy.stats import dirichlet as dir_dist
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Dirichlet Multi-Armed Experiment Engine")


class ExpState:
    def __init__(self):
        self.arms = ["control", "variant_a", "variant_b", "variant_c"]
        self.alpha = (
            np.ones(len(self.arms), dtype=float) * 1.0
        )  # 先验 Beta(1,1) 等效 Dir(1...)
        self.start_ts = time.time()
        self.concentration_k = 1.0  # 探索强度

    def get_allocation(self, k_override: float = None) -> list:
        k = k_override or self.concentration_k
        # Thompson Sampling: 采样后验
        theta = dir_dist.rvs(self.alpha, size=1)[0]
        # 指数收敛: 放大高分臂权重, 压制尾部探索
        weights = np.exp(k * theta)
        return (weights / weights.sum()).tolist()

    def record_feedback(self, arm_idx: int, reward: float):
        self.alpha[arm_idx] += reward
        # 自动收敛: 每 1000 次反馈增加 κ, 加速确定性
        total = self.alpha.sum() - len(self.arms)
        self.concentration_k = 1.0 + 0.5 * math.log1p(total / 500.0)


state = ExpState()


@app.get("/api/allocation")
def get_weights():
    return {"weights": state.get_allocation(), "kappa": state.concentration_k}


@app.post("/api/record")
async def record(arm: str, reward: float = 1.0):
    idx = state.arms.index(arm)
    state.record_feedback(idx, reward)
    return {
        "status": "ok",
        "alpha": state.alpha.tolist(),
        "kappa": state.concentration_k,
    }


@app.post("/api/converge")
def force_converge():
    best = int(np.argmax(state.alpha))
    return {
        "forced_winner": state.arms[best],
        "alloc": state.get_allocation(k_override=100.0),
    }
