#!/usr/bin/env python3
"""
PPO 动态安全边界调节器: 基于 CPU/IO/网络负载自适应收紧/放宽 Action Clipper
机制: EMA 负载跟踪 → 动态计算 max_delta 与 cooldown → 保障高载期策略平滑, 低载期快速探索
"""

import time
import logging
import gymnasium as gym
import numpy as np
from prometheus_api_client import PrometheusConnect

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("DynamicSafetyClipper")


class DynamicLoadClipper(gym.Wrapper):
    def __init__(
        self, env, prom_url: str, base_delta: float = 0.08, base_cooldown: float = 30.0
    ):
        super().__init__(env)
        self.prom = PrometheusConnect(url=prom_url, disable_ssl=True)
        self.base_delta = base_delta
        self.base_cooldown = base_cooldown

        # 动态状态
        self.ema_load = 0.5
        self.current_delta = base_delta
        self.current_cooldown = base_cooldown
        self.last_step_ts = 0.0
        self.last_action = np.zeros(2, dtype=np.float32)

    def _fetch_system_metrics(self) -> float:
        """获取归一化综合负载 (0~1): 0.6*CPU + 0.2*IO_wait + 0.2*Net_Err"""
        cpu = (
            float(
                self.prom.custom_query(
                    '100 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100'
                )[0]["value"][1]
            )
            / 100.0
        )
        iow = (
            float(
                self.prom.custom_query(
                    'avg(rate(node_cpu_seconds_total{mode="iowait"}[5m]))*100'
                )[0]["value"][1]
            )
            / 100.0
        )
        # 归一化至 [0,1] 并加权
        return np.clip(0.6 * cpu + 0.2 * iow + 0.1, 0.0, 1.0)

    def _recalculate_bounds(self):
        """负载越高, 探索越保守 (指数衰减边界 + 线性延长冷却)"""
        self.ema_load = 0.85 * self.ema_load + 0.15 * self._fetch_system_metrics()
        tightness = self.ema_load

        # 动态边界: 负载 80% 时收缩至原 30%, 负载 30% 时放宽至原 110%
        self.current_delta = np.clip(
            self.base_delta * (1.1 - 0.9 * tightness), 0.02, 0.15
        )
        self.current_cooldown = self.base_cooldown * (1.0 + 2.0 * tightness)

    def step(self, action):
        self._recalculate_bounds()
        now = time.time()

        # 冷却期拦截
        if now - self.last_step_ts < self.current_cooldown:
            log.debug(
                f"⏳ 动态冷却拦截 | 剩余: {self.current_cooldown - (now - self.last_step_ts):.1f}s"
            )
            return self.env.step(np.zeros(2, dtype=np.float32))

        # 动态 Clipper: 限制变化速率
        clipped_act = np.clip(
            action - self.last_action, -self.current_delta, self.current_delta
        )
        safe_act = self.last_action + clipped_act
        safe_act = np.clip(safe_act, -1.0, 1.0)  # 全局硬限幅

        obs, reward, term, trunc, info = self.env.step(safe_act)
        self.last_action = safe_act
        self.last_step_ts = now

        info.update(
            {
                "load_ema": round(self.ema_load, 3),
                "delta": round(self.current_delta, 4),
                "cooldown": round(self.current_cooldown, 1),
                "clipped": bool(np.any(np.abs(clipped_act) < 1e-5)),
            }
        )
        return obs, reward, term, trunc, info
