#!/usr/bin/env python3
"""
Ray RLlib PPO 背压在线控制器
流程: 离线训练 → 保存 Checkpoint → 在线流式推理 → 动态 Patch K8s ConfigMap
"""

import os
import json
import time
import logging
import numpy as np
import ray
from ray.rllib.algorithms.ppo import PPOConfig
from prometheus_rl_env import PrometheusBackpressureEnv
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PPO-Backpressure")

PROM_URL = os.getenv("PROM_URL", "http://prometheus.monitoring.svc:9090")
CM_NAME = os.getenv("LIMITER_CM", "etcd-limiter-config")
CM_NS = os.getenv("LIMITER_NS", "istio-system")
CHECKPOINT_DIR = "/data/ppo_checkpoints"


def train_and_save():
    log.info("🎓 启动 PPO 离线训练...")
    env = PrometheusBackpressureEnv(PROM_URL)
    ray.init(ignore_reinit_error=True)
    cfg = (
        PPOConfig()
        .environment(env=PrometheusBackpressureEnv)
        .framework("torch")
        .num_workers(4)
        .rollout_fragment_length(100)
    )
    algo = cfg.build()
    for i in range(150):
        res = algo.train()
        if i % 25 == 0:
            log.info(f"📊 Iter {i} | Mean Reward: {res['episode_reward_mean']:.2f}")
    cp_path = algo.save(CHECKPOINT_DIR)
    log.info(f"✅ Checkpoint 已保存: {cp_path}")
    return cp_path


def serve_loop(cp_path):
    log.info(f"🌐 启动在线推理服务 | Checkpoint: {cp_path}")
    algo = PPOConfig().framework("torch").build()
    algo.restore(cp_path)
    env = PrometheusBackpressureEnv(PROM_URL)
    obs, _ = env.reset()
    config.load_incluster_config()
    api = client.CoreV1Api()

    while True:
        try:
            action = algo.compute_single_action(obs, explore=False)
            _, _, done, _, info = env.step(action)
            obs, _ = env.reset() if done else (env.state, {})

            new_cap, new_rate = info["cap"], info["rate"]
            payload = {
                "data": {"capacity": str(int(new_cap)), "base_rate": f"{new_rate:.2f}"}
            }
            api.patch_namespaced_config_map(CM_NAME, CM_NS, payload)
            log.info(f"📤 RL 动作执行 | cap={new_cap:.0f}, rate={new_rate:.2f}")
            time.sleep(30)  # 对齐 Prometheus 采集粒度
        except Exception as e:
            log.error(f"💥 在线推理异常: {e}")
            time.sleep(60)


if __name__ == "__main__":
    mode = os.getenv("MODE", "serve")
    if mode == "train":
        cp = train_and_save()
    else:
        if not os.path.exists(CHECKPOINT_DIR + "/checkpoint"):
            raise RuntimeError("❌ 未找到 Checkpoint, 请先设置 MODE=train 训练")
        serve_loop(CHECKPOINT_DIR)
