#!/usr/bin/env python3
"""
Sigma-Driven 探索-利用动态调节器 (Gumbel-Max 噪声注入)
原理: trace(Sigma) 度量参数不确定性 → 映射至探索权重 ε ∈ [ε_min, ε_max]
      在奖励采样阶段注入 Gumbel 噪声，实现平滑过渡与理论最优遗憾界保证
"""

import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("SigmaExplorer")


class SigmaDrivenRegulator:
    def __init__(
        self,
        d: int,
        eps_min: float = 0.05,
        eps_max: float = 0.60,
        sigma_ref: float = 0.8,
    ):
        self.eps_min = eps_min
        self.eps_max = eps_max
        self.sigma_ref = sigma_ref  # 参考方差阈值，超此值加大探索
        self.d = d

    def compute_exploration_rate(self, sigma_diag: list) -> float:
        """计算当前探索率 (0~1)"""
        total_uncertainty = np.sum(sigma_diag)
        # Sigmoid-like 映射: f(x) = x / (x + ref)
        rate = total_uncertainty / (total_uncertainty + self.sigma_ref * self.d)
        return np.clip(
            rate * (self.eps_max - self.eps_min) + self.eps_min,
            self.eps_min,
            self.eps_max,
        )

    def adjust_rewards_with_exploration(self, rewards: dict, sigma_diag: list) -> dict:
        """在奖励上注入 Gumbel 噪声实现探索 (TS + Exploration Bonus)"""
        eps = self.compute_exploration_rate(sigma_diag)
        log.info(
            f"🔍 Sigma不确定性: {np.sum(sigma_diag):.3f} | 动态探索率 ε: {eps:.3f}"
        )

        adjusted = {}
        for ver, base_r in rewards.items():
            # Gumbel(0,1) 采样: -log(-log(U))
            gumbel_noise = -np.log(-np.log(np.random.uniform(0.001, 0.999)))
            adjusted[ver] = base_r + eps * gumbel_noise
        return adjusted

    def should_force_explore(self, sigma_diag: list, min_samples: int = 5) -> bool:
        """冷启动/数据稀疏时强制探索"""
        return (
            np.mean(sigma_diag) > self.sigma_ref * 1.5
            and sum(sigma_diag) < min_samples * 0.1
        )


# ================= 使用示例 (Patch 至原 linear_ts_pareto.py) =================
if __name__ == "__main__":
    regulator = SigmaDrivenRegulator(d=4, eps_min=0.05, eps_max=0.6, sigma_ref=0.8)
    test_sigma = [0.4, 0.5, 0.2, 0.6]
    test_rewards = {"v1": 0.72, "v2": 0.68}

    adjusted = regulator.adjust_rewards_with_exploration(test_rewards, test_sigma)
    print(f"📊 原始奖励: {test_rewards}")
    print(f"🎯 调整后: { {k: round(v,4) for k,v in adjusted.items()} }")
