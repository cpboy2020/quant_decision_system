#!/usr/bin/env python3
"""
LinUCB PR 智能评审人调度引擎 (带接受率反馈闭环)
算法: p_a = x^T θ_a + α √(x^T A_a^-1 x) → 探索/利用自适应平衡
"""

import os
import json
import time
import logging
import pickle
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="LinUCB PR Reviewer Scheduler", version="1.0.0")

STATE_PATH = "/data/linucb_state.pkl"
ALPHA = 1.5  # 探索系数
REVIEWERS = os.getenv("REVIEWERS", "dev-team-a,dev-team-b,security-review").split(",")
DIM = 4  # [lines_changed, num_files, is_complex, hour_of_day]


class PRContext(BaseModel):
    changed_lines: int
    num_files: int
    is_complex: bool = False
    hour_of_day: int = 10
    pr_id: str


class Feedback(BaseModel):
    pr_id: str
    reviewer: str
    reward: float  # +1 快速通过, 0 延迟, -1 驳回/返工


class LinUCBState:
    def __init__(self):
        self.A = {r: np.eye(DIM) * 0.5 for r in REVIEWERS}
        self.b = {r: np.zeros(DIM) for r in REVIEWERS}
        self.load()

    def load(self):
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, "rb") as f:
                    saved = pickle.load(f)
                self.A = saved.get("A", self.A)
                self.b = saved.get("b", self.b)
                log.info(f"💾 状态已恢复 | A shape: {list(self.A.values())[0].shape}")
            except Exception as e:
                log.warning(f"⚠️ 加载失败: {e}")

    def save(self):
        with open(STATE_PATH, "wb") as f:
            pickle.dump({"A": self.A, "b": self.b}, f)

    def predict(self, x: np.ndarray) -> str:
        best_score, best_rev = -float("inf"), ""
        for rev in REVIEWERS:
            A_inv = np.linalg.inv(self.A[rev])
            theta = A_inv @ self.b[rev]
            p = x @ theta + ALPHA * np.sqrt(x @ A_inv @ x)
            if p > best_score:
                best_score, best_rev = p, rev
        return best_rev

    def update(self, x: np.ndarray, rev: str, r: float):
        self.A[rev] += np.outer(x, x)
        self.b[rev] += r * x
        self.save()


state = LinUCBState()


@app.post("/recommend")
def recommend(ctx: PRContext) -> dict:
    x = np.array(
        [
            ctx.changed_lines / 5000.0,
            ctx.num_files / 20.0,
            float(ctx.is_complex),
            ctx.hour_of_day / 24.0,
        ]
    )
    rev = state.predict(x)
    return {"reviewer": rev, "confidence": round(ALPHA, 2), "context": x.tolist()}


@app.post("/feedback")
def feedback(fb: Feedback) -> dict:
    # 实际生产应从 DB 提取该 PR 的原始 Context
    x = np.random.uniform(0, 1, DIM)  # 占位: 实际应从请求日志反查
    state.update(x, fb.reviewer, fb.reward)
    log.info(f"🔄 反馈更新 | Reviewer: {fb.reviewer} | Reward: {fb.reward}")
    return {"status": "updated"}


@app.get("/stats")
def stats():
    return {
        rev: {
            "A_trace": float(np.trace(state.A[rev])),
            "b_norm": float(np.linalg.norm(state.b[rev])),
        }
        for rev in REVIEWERS
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9092, log_level="info")
