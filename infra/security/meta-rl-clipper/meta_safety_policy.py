#!/usr/bin/env python3
"""
Meta-RL 安全参数控制器: 轻量 MLP 策略网络 → 输出 max_delta_pct & cooldown_sec
架构: 观测系统状态 → 策略前向传播 → 输出归一化动作 → 映射至物理安全边界
生产模式: 纯推理 (<2ms), 训练模式: 离线回放+PPO梯度更新
"""

import os
import json
import time
import logging
import torch
import torch.nn as nn
import numpy as np
import requests
from prometheus_api_client import PrometheusConnect
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Meta-RL Safety Boundary Controller")


# 策略网络定义
class SafetyPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(5, 64),
            nn.ReLU(),
            nn.LayerNorm(64),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, 2),
            nn.Tanh(),  # 输出 [-1,1] 缩放因子
        )

    def forward(self, x):
        return self.net(x)


policy = SafetyPolicy()
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
policy.to(DEVICE)

# 加载预训练权重 (生产应从 S3/Vault 拉取)
CKPT_PATH = os.getenv("META_CKPT", "/data/meta_safety_ckpt.pt")
if os.path.exists(CKPT_PATH):
    policy.load_state_dict(torch.load(CKPT_PATH, map_location=DEVICE))
    policy.eval()
    logging.info(f"✅ Meta-Policy 权重已加载: {CKPT_PATH}")


def fetch_observation(prom_url: str) -> np.ndarray:
    p = PrometheusConnect(url=prom_url, disable_ssl=True)
    cpu = float(
        p.custom_query('100-avg(rate(node_cpu_seconds_total{mode="idle"}[2m]))*100')[0][
            "value"
        ][1]
    )
    io = float(
        p.custom_query('avg(rate(node_cpu_seconds_total{mode="iowait"}[2m]))*100')[0][
            "value"
        ][1]
    )
    net_err = float(
        p.custom_query("sum(rate(node_network_receive_errs_total[2m]))")[0]["value"][1]
    )
    lat_p99 = float(
        p.custom_query(
            "histogram_quantile(0.99,sum(rate(etcd_sync_latency_seconds_bucket[5m]))by(le))"
        )[0]["value"][1]
    )
    cur_delta = float(os.getenv("CURR_DELTA", "0.06"))
    # 归一化 [0,1]
    return np.array(
        [
            cpu / 100.0,
            io / 20.0,
            min(net_err / 1000, 1.0),
            min(lat_p99 / 0.5, 1.0),
            cur_delta / 0.15,
        ],
        dtype=np.float32,
    )


@app.get("/api/safety_bounds")
async def get_bounds():
    obs = fetch_observation(
        os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
    )
    with torch.no_grad():
        act = policy(torch.tensor(obs).to(DEVICE)).cpu().numpy()

    # 映射: act[0]->delta_scale, act[1]->cooldown_scale
    delta = np.clip(0.06 + act[0] * 0.08, 0.015, 0.14)
    cooldown = np.clip(30.0 + act[1] * 40.0, 15.0, 85.0)
    return {
        "max_delta_pct": round(float(delta), 4),
        "cooldown_sec": round(float(cooldown), 1),
        "obs_norm": obs.tolist(),
    }


@app.post("/api/train_step")
async def train_step(reward: float, obs: list, action: list):
    """离线训练数据注入端点 (可选)"""
    # 实际生产应连接 Ray/RLlib replay buffer, 此处省略梯度更新代码
    return {"status": "logged"}
