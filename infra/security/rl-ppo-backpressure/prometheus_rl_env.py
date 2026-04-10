#!/usr/bin/env python3
"""
Prometheus 流式背压 Gymnasium 环境
State: [p99_latency_s, drop_rate, tokens_remaining, current_rate]
Action: [capacity_delta(-1~1), rate_delta(-1~1)]
Reward: - (w1*latency_pen + w2*drop_pen + w3*action_smooth)
"""

import gymnasium as gym
import numpy as np
from prometheus_api_client import PrometheusConnect


class PrometheusBackpressureEnv(gym.Env):
    metadata = {"render_modes": ["ansi"]}

    def __init__(
        self, prom_url: str, latency_target: float = 0.15, drop_weight: float = 5.0
    ):
        super().__init__()
        self.prom = PrometheusConnect(url=prom_url, disable_ssl=True)
        self.target = latency_target
        self.drop_w = drop_weight
        self.observation_space = gym.spaces.Box(
            low=0, high=1.0, shape=(4,), dtype=np.float32
        )
        self.action_space = gym.spaces.Box(
            low=-1.0, high=1.0, shape=(2,), dtype=np.float32
        )
        self.state = np.zeros(4, dtype=np.float32)
        self.steps = 0

    def _fetch_state(self) -> np.ndarray:
        p99 = self.prom.custom_query(
            "histogram_quantile(0.99, sum(rate(etcd_sync_latency_seconds_bucket[5m])) by (le))"
        )[0]["value"]
        drops = self.prom.custom_query("sum(rate(etcd_sync_dropped_total[5m]))")[0][
            "value"
        ]
        rate = self.prom.custom_query("etcd_sync_current_rate")[0]["value"]
        # 归一化至 [0,1]
        return np.array(
            [float(p99[1]), float(drops[1]), 0.5, float(rate[1]) / 60.0],
            dtype=np.float32,
        )

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.state = self._fetch_state()
        self.steps = 0
        return self.state, {}

    def step(self, action):
        self.steps += 1
        cap_delta, rate_delta = action
        # 映射至物理参数
        new_cap = np.clip(300 + cap_delta * 150, 100, 600)
        new_rate = np.clip(25.0 * (1.5**rate_delta), 5.0, 50.0)

        # 模拟一步环境演进 (实际应等待 Prometheus 更新, 此处用平滑插值近似)
        self.state[3] = new_rate / 60.0

        # Reward 计算
        lat_pen = max(self.state[0] - self.target, 0.0) * 10.0
        drop_pen = self.state[1] * self.drop_w
        action_smooth = 0.1 * (cap_delta**2 + rate_delta**2)
        reward = -(lat_pen + drop_pen + action_smooth)

        done = self.steps >= 100 or reward < -50.0
        return self.state, reward, done, False, {"cap": new_cap, "rate": new_rate}
