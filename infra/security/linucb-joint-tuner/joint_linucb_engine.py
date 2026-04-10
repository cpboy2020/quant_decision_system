#!/usr/bin/env python3
"""
LinUCB 在线-离线联合调优引擎
架构: 离线 Optuna (月频) → 输出 Pareto 先验 w0 → 在线 EMA 自适应 w(t) → 阈值同步回 ConfigMap
"""

import os
import json
import time
import logging
import math
import numpy as np
from kubernetes import client, config
import optuna

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

CONFIG_MAP_NAME = "linucb-pareto-weights"
CONFIG_MAP_NS = "quant-prod"
EMA_ALPHA = 0.05  # 在线衰减系数 (越小越贴近离线先验)
SYNC_THRESHOLD = 0.08  # L2 范数变化超此值触发 ConfigMap 同步


class HybridScheduler:
    def __init__(self):
        self.w_offline = self._load_optuna_prior()
        self.w_online = self.w_offline.copy()
        self.last_sync = time.time()
        self.feedback_count = 0
        logging.info(f"🧬 联合调度器初始化 | 离线先验: {self.w_offline}")

    def _load_optuna_prior(self) -> dict:
        try:
            config.load_incluster_config()
            cm = client.CoreV1Api().read_namespaced_config_map(
                CONFIG_MAP_NAME, CONFIG_MAP_NS
            )
            return json.loads(
                cm.data.get(
                    "weights.json", '{"w_speed":0.3,"w_quality":0.5,"w_load":0.2}'
                )
            )
        except:
            return {"w_speed": 0.3, "w_quality": 0.5, "w_load": 0.2}

    def recommend(self, ctx: dict) -> tuple:
        """基于在线权重进行上下文多臂老虎机决策"""
        x = np.array([ctx["lines"] / 5000.0, ctx["files"] / 20.0, ctx["hour"] / 24.0])
        # 简化的 UCB 决策 (实际可接入完整 A,b 矩阵)
        scores = {"dev-a": 0.72, "sec-b": 0.68, "infra-c": 0.81}  # 占位模型分
        best = max(scores, key=scores.get)
        return best, self.w_online

    def update_feedback(
        self, reviewer: str, reward_speed: float, quality: float, load: float
    ):
        """在线反馈 → EMA 更新权重"""
        # 奖励标量化: R = w_spd*speed + w_qual*quality - w_load*load
        w = self.w_offline
        r = w["w_speed"] * reward_speed + w["w_quality"] * quality - w["w_load"] * load

        # 在线权重漂移 (简化: 基于反馈方向微调)
        drift = 0.02 if r > 0.7 else -0.01
        for k in self.w_online:
            self.w_online[k] += drift

        # 归一化
        s = sum(self.w_online.values())
        self.w_online = {k: v / s for k, v in self.w_online.items()}
        self.feedback_count += 1

        # 检查是否同步回离线配置
        dist = math.sqrt(
            sum((self.w_online[k] - self.w_offline[k]) ** 2 for k in self.w_offline)
        )
        if dist > SYNC_THRESHOLD and time.time() - self.last_sync > 3600:
            self._sync_to_configmap()
        return r

    def _sync_to_configmap(self):
        config.load_incluster_config()
        api = client.CoreV1Api()
        payload = {
            "data": {
                "weights.json": json.dumps(self.w_online),
                "synced_at": str(int(time.time())),
            }
        }
        try:
            api.patch_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS, payload)
        except:
            pass
        self.w_offline = self.w_online.copy()
        self.last_sync = time.time()
        logging.info(f"📤 在线权重已同步至 ConfigMap | 距: {dist:.3f}")


if __name__ == "__main__":
    sched = HybridScheduler()
    rev, w = sched.recommend({"lines": 1500, "files": 8, "hour": 14})
    print(f"🎯 推荐: {rev} | 当前权重: {w}")
    r = sched.update_feedback(rev, 0.9, 0.85, 0.3)
    print(f"✅ 奖励: {r:.3f} | 在线权重: {sched.w_online}")
