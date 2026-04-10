#!/usr/bin/env python3
"""
PPO 安全动作护栏: Action Clipper + Change Velocity Limiter + Hard Boundaries
保障: 防 RL 探索期剧烈震荡, 限制单次参数变更 ≤ 8%, 冷却周期 ≥ 30s
"""

import time
import logging
import gymnasium as gym
import numpy as np

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PPOSafeWrapper")


class SafeLimiterWrapper(gym.Wrapper):
    def __init__(
        self, env, max_delta_pct: float = 0.08, min_cooldown_sec: float = 30.0
    ):
        super().__init__(env)
        self.max_delta = max_delta_pct
        self.min_cooldown = min_cooldown_sec
        self.last_cap = 300.0
        self.last_rate = 25.0
        self.last_action_ts = 0.0

    def reset(self, seed=None, **kwargs):
        obs, info = super().reset(seed=seed, **kwargs)
        self.last_action_ts = time.time()
        return obs, info

    def step(self, action):
        now = time.time()
        cooldown_left = self.last_action_ts + self.min_cooldown - now
        if cooldown_left > 0:
            log.warning(f"⏳ 触发冷却限制 | 剩余: {cooldown_left:.1f}s")
            return self._apply_safe_action(np.zeros(2), wait=True)

        # 1. Hard Clipper: 映射 RL action [-1,1] → 安全范围
        cap_delta = np.clip(action[0], -0.9, 0.9) * 100.0
        rate_delta = np.clip(action[1], -0.9, 0.9) * 10.0

        # 2. Rate Limiter: 限制单次变更幅度 ≤ max_delta
        safe_cap = np.clip(
            cap_delta, -self.last_cap * self.max_delta, self.last_cap * self.max_delta
        )
        safe_rate = np.clip(
            rate_delta,
            -self.last_rate * self.max_delta,
            self.last_rate * self.max_delta,
        )

        safe_action = np.array([safe_cap, safe_rate], dtype=np.float32)
        self.last_action_ts = time.time()

        # 记录安全动作并下发
        return self._apply_safe_action(safe_action)

    def _apply_safe_action(self, safe_act: np.ndarray, wait: bool = False) -> tuple:
        if wait:
            # 冷却期: 返回零动作, 不惩罚, 仅等待
            return self.env.step(np.zeros(2))

        cap = np.clip(self.last_cap + safe_act[0], 100, 600)
        rate = np.clip(self.last_rate + safe_act[1], 5.0, 50.0)

        # 实际 Patch 逻辑 (此处调用原 env 或 K8s API)
        obs, reward, term, trunc, info = self.env.step(
            np.array([safe_act[0] / 100.0, safe_act[1] / 10.0])
        )

        self.last_cap, self.last_rate = cap, rate
        info.update(
            {
                "safe_cap": cap,
                "safe_rate": rate,
                "clipped": not np.array_equal(safe_act, np.zeros(2)),
            }
        )
        return obs, reward, term, trunc, info
