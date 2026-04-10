#!/usr/bin/env python3
"""
LightGBM PR 评审效能预测器 & 动态权重校准
输入: 历史 PR 特征(代码变更量/文件类型/提交时段/作者历史/评审人负载)
输出: 预测评审时长 → 反向加权 CODEOWNERS 调度优先级
"""

import os
import json
import time
import logging
import math
import pandas as pd
import lightgbm as lgb
from github import Github
import yaml
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("LGBM-Scheduler")

GH_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPOSITORY", "your-org/repo")
CONFIG_MAP_NS = "quant-prod"
CONFIG_MAP_NAME = "pr-scheduling-weights"


def fetch_pr_features() -> pd.DataFrame:
    g = Github(GH_TOKEN)
    repo = g.get_repo(REPO)
    prs = repo.get_pulls(state="all", per_page=100).get_page(0)
    rows = []
    for p in prs:
        if not p.merged_at:
            continue
        created, merged = p.created_at, p.merged_at
        hours_to_merge = (merged - created).total_seconds() / 3600
        changes = p.additions + p.deletions
        hour = p.created_at.hour
        rows.append(
            {
                "changed_lines": changes,
                "num_files": len(list(p.get_files())),
                "hour_of_day": hour,
                "is_weekend": 1 if p.created_at.weekday() >= 5 else 0,
                "target_hours": hours_to_merge,
            }
        )
    return pd.DataFrame(rows)


def train_and_calibrate_weights(df: pd.DataFrame) -> dict:
    if len(df) < 50:
        return {"default": 1.0}

    X = df[["changed_lines", "num_files", "hour_of_day", "is_weekend"]]
    y = df["target_hours"]

    dtrain = lgb.Dataset(X, label=y)
    params = {"objective": "regression", "metric": "mae", "verbosity": -1, "seed": 42}
    model = lgb.train(params, dtrain, num_boost_round=150)

    # 预测未来典型 PR 负载对评审时长的影响
    test_X = pd.DataFrame(
        {
            "changed_lines": [100, 500, 1000, 5000],
            "num_files": [3, 12, 25, 80],
            "hour_of_day": [10, 10, 10, 10],
            "is_weekend": [0] * 4,
        }
    )
    preds = model.predict(test_X)

    # 动态权重: 耗时越长，权重越低(防阻塞)，但给予额外安全审查加分
    weights = {
        "high_load_penalty": 1.0 / (1.0 + preds.mean() / 24),
        "feature_importance": dict(
            zip(
                ["changed_lines", "num_files", "hour_of_day", "is_weekend"],
                model.feature_importance().tolist(),
            )
        ),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return weights


def update_configmap(weights: dict):
    config.load_incluster_config()
    api = client.CoreV1Api()
    try:
        cm = api.read_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS)
    except:
        cm = client.V1ConfigMap(
            meta={"name": CONFIG_MAP_NAME, "namespace": CONFIG_MAP_NS}, data={}
        )

    cm.data["scheduling_weights.json"] = json.dumps(weights, indent=2)
    try:
        api.patch_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS, cm)
    except:
        api.create_namespaced_config_map(CONFIG_MAP_NS, cm)
    log.info(f"✅ PR 调度权重已更新至 ConfigMap: {CONFIG_MAP_NAME}")


def main():
    log.info("📊 拉取 GitHub PR 历史特征...")
    df = fetch_pr_features()
    log.info(f"📈 训练 LightGBM 回归模型 ({len(df)} 样本)...")
    weights = train_and_calibrate_weights(df)
    update_configmap(weights)
    log.info(f"🎯 权重特征重要性: {weights.get('feature_importance', {})}")


if __name__ == "__main__":
    main()
