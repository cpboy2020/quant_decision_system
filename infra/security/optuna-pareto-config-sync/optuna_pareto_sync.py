#!/usr/bin/env python3
"""
Optuna 离线帕累托权重搜索器: 寻找最优 [w_speed, w_quality, w_load]
同步: 将最优解写入 K8s ConfigMap linucb-pareto-weights 供在线引擎消费
"""

import os
import json
import logging
import time
import numpy as np
import optuna
from kubernetes import client, config
from sklearn.metrics import mean_squared_error

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("OptunaParetoSync")

CONFIG_MAP_NAME = "linucb-pareto-weights"
CONFIG_MAP_NS = "quant-prod"
N_TRIALS = int(os.getenv("N_TRIALS", "80"))

# 模拟历史回放数据集 (实际应从 Lakehouse 拉取)
HISTORICAL_PRS = [
    {
        "lines": 120,
        "files": 2,
        "hour": 9,
        "reviewer_load": 0.2,
        "actual_time": 4.5,
        "quality": 0.9,
    },
    {
        "lines": 2500,
        "files": 15,
        "hour": 18,
        "reviewer_load": 0.8,
        "actual_time": 36.0,
        "quality": 0.4,
    },
    {
        "lines": 800,
        "files": 5,
        "hour": 14,
        "reviewer_load": 0.4,
        "actual_time": 18.0,
        "quality": 0.85,
    },
] * 150  # 扩展至 450 条


def objective(trial: optuna.Trial):
    w_spd = trial.suggest_float("w_speed", 0.1, 0.6)
    w_qual = trial.suggest_float("w_quality", 0.3, 0.7)
    w_load = trial.suggest_float("w_load", 0.05, 0.3)

    # 约束: w_spd + w_qual + w_load = 1.0
    total = w_spd + w_qual + w_load
    w_spd, w_qual, w_load = w_spd / total, w_qual / total, w_load / total

    sim_time, sim_qual = [], []
    for pr in HISTORICAL_PRS:
        # 简化 LinUCB 模拟: 预测分数 = w_spd*(1-time/48) + w_qual*quality - w_load*load
        score = (
            w_spd * (1 - pr["actual_time"] / 48)
            + w_qual * pr["quality"]
            - w_load * pr["reviewer_load"]
        )
        sim_time.append(pr["actual_time"] * (1.1 if score < 0.5 else 0.9))  # 低分预测慢
        sim_qual.append(
            pr["quality"] * (0.9 if score < 0.5 else 1.05)
        )  # 低分预测质量降

    # 多目标: 最小化平均评审耗时, 最大化平均质量
    avg_time = np.mean(sim_time)
    avg_quality = np.mean(sim_qual)

    trial.set_user_attr(
        "weights",
        {
            "w_speed": round(w_spd, 3),
            "w_quality": round(w_qual, 3),
            "w_load": round(w_load, 3),
        },
    )
    trial.report(avg_time, step=0)
    if trial.should_prune():
        raise optuna.TrialPruned()

    return avg_time, avg_quality  # Optuna v3 多目标返回元组


def sync_best_weights_to_k8s(study: optuna.Study):
    # 选取 Pareto Front 中 Trade-off 最优解 (最小化距离原点)
    pareto = study.best_trials
    best = min(pareto, key=lambda t: np.linalg.norm(t.values))
    weights = best.user_attrs["weights"]

    config.load_incluster_config()
    api = client.CoreV1Api()
    payload = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": CONFIG_MAP_NAME, "namespace": CONFIG_MAP_NS},
        "data": {
            "weights.json": json.dumps(weights, indent=2),
            "updated_at": str(int(time.time())),
        },
    }
    try:
        api.create_namespaced_config_map(CONFIG_MAP_NS, payload)
    except client.exceptions.ApiException as e:
        if e.status == 409:
            api.patch_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS, payload)
    log.info(f"✅ 最优权重已同步至 ConfigMap | {weights}")


def main():
    log.info(f"🚀 启动 Optuna 多目标帕累托搜索 (Trials: {N_TRIALS})")
    study = optuna.create_study(
        directions=["minimize", "maximize"], sampler=optuna.samplers.NSGAIISampler()
    )
    study.optimize(objective, n_trials=N_TRIALS, n_jobs=-1, show_progress_bar=True)
    sync_best_weights_to_k8s(study)


if __name__ == "__main__":
    main()
