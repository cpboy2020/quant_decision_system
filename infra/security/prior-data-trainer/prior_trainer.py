#!/usr/bin/env python3
"""
Prior-Data 预训练先验分布生成器
输入: 离线回测 CSV (含上下文特征 X, 奖励 Y)
输出: 适配 Linear TS 控制器的 μ/Σ JSON (含 v1/v2 独立先验)
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PriorTrainer")

OUTPUT_PATH = os.getenv("OUTPUT_PRIOR_JSON", "/opt/config/linear_ts_prior.json")
D = int(os.getenv("CONTEXT_DIM", "4"))  # [time, load, hist_acc, bias]


def synthesize_offline_data(n=2000):
    """生成符合量化业务分布的模拟离线数据"""
    np.random.seed(42)
    t = np.random.uniform(0, 1, n)
    load = np.random.exponential(0.6, n)
    acc = np.random.beta(8, 2, n)
    X = np.column_stack([t, load, acc, np.ones(n)])

    # 真实 θ* 假设: 时间影响小, 负载负向, 准确率正向, 偏置 0.2
    theta_true = np.array([-0.1, 0.35, 1.2, 0.15])
    noise = np.random.normal(0, 0.05, n)
    y = X @ theta_true + noise

    df = pd.DataFrame(X, columns=["time", "load", "acc", "bias"])
    df["y"] = np.clip(y, 0, 1.5)
    return df


def fit_bayesian_prior(df: pd.DataFrame, subset: str = "all") -> dict:
    """拟合贝叶斯岭回归获取 μ, Σ"""
    X = df[["time", "load", "acc", "bias"]].values
    y = df["y"].values
    model = BayesianRidge(
        compute_score=True, fit_intercept=False, alpha_1=1e-6, alpha_2=1e-6
    )
    model.fit(X, y)

    mu = model.coef_.tolist()
    # Σ ≈ diag(σ² / (X^T X + λI)) 近似对角协方差
    Sigma_diag = (model.sigma_).tolist() if hasattr(model, "sigma_") else [0.01] * D
    return {
        "mu": [round(m, 4) for m in mu],
        "Sigma_diag": [round(s, 5) for s in Sigma_diag],
        "rmse": round(np.sqrt(model.score_), 4),
    }


def main():
    data_file = os.getenv("OFFLINE_CSV_PATH")
    if data_file and Path(data_file).exists():
        log.info(f"📥 加载离线数据: {data_file}")
        df = pd.read_csv(data_file)
    else:
        log.warning("⚠️ 未提供离线 CSV，使用合成数据生成先验")
        df = synthesize_offline_data()

    log.info(f"🧪 数据集规模: {len(df)} 样本 | 维度: {D}")
    prior_v1 = fit_bayesian_prior(
        df[df.get("version", "v1") == "v1"] if "version" in df.columns else df, "v1"
    )
    prior_v2 = fit_bayesian_prior(
        df[df.get("version", "v2") == "v2"] if "version" in df.columns else df, "v2"
    )

    result = {
        "metadata": {
            "context_dim": D,
            "train_samples": len(df),
            "generated_at": pd.Timestamp.utcnow().isoformat(),
        },
        "v1": prior_v1,
        "v2": prior_v2,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    log.info(f"✅ 先验分布已生成: {OUTPUT_PATH}")
    log.info(f"📊 v1 μ: {prior_v1['mu']} | v2 μ: {prior_v2['mu']}")


if __name__ == "__main__":
    main()
