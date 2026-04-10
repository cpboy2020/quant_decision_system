#!/usr/bin/env python3
"""
LinUCB 多目标帕累托奖励引擎 (Speed + Quality + Load)
质量打分: 基于 GitHub API (Approval 速度、Comment 深度、变更请求率)
"""

import os
import json
import time
import math
import logging
import numpy as np
import requests
from github import Github

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)


class QualityScorer:
    def __init__(self, token: str, repo: str):
        self.gh = Github(token)
        self.repo = self.gh.get_repo(repo)

    def compute_pr_quality(self, pr_number: int) -> float:
        """计算 PR 质量分 [0,1]: 审批速度、评论密度、无打回加权"""
        pr = self.repo.get_pull(pr_number)
        reviews = pr.get_reviews()
        comments = pr.get_issue_comments()

        approvals = sum(1 for r in reviews if r.state == "APPROVED")
        changes = sum(1 for r in reviews if r.state == "CHANGES_REQUESTED")
        if not approvals and not changes:
            return 0.5  # 无反馈默认中

        # 速度分 (假设目标 <24h, 越快分越高)
        hours_open = (
            (pr.merged_at - pr.created_at).total_seconds() / 3600
            if pr.merged_at
            else 48
        )
        speed_score = max(0.0, 1.0 - hours_open / 48.0)

        # 质量分 (适度评论=好, 频繁打回=差)
        comment_density = len(list(comments)) / max(pr.additions + pr.deletions, 1)
        quality_score = max(
            0.0, min(1.0, comment_density * 5.0 + (approvals - changes) * 0.3)
        )

        return 0.5 * speed_score + 0.5 * quality_score


class ParetoLinUCB:
    def __init__(
        self, arms: list, alpha: float = 1.0, w_speed=0.35, w_quality=0.45, w_load=0.20
    ):
        self.arms = arms
        self.alpha = alpha
        self.w = np.array([w_speed, w_quality, w_load])
        self.d = 3  # 简化上下文: [lines/5k, files/20, hour/24]
        self.A = {r: np.eye(self.d) * 0.5 for r in arms}
        self.b = {r: np.zeros(self.d) for r in arms}
        self.load_tracker = {r: 0 for r in arms}
        self.scorer = None

    def init_github_scorer(self, token, repo):
        self.scorer = QualityScorer(token, repo)

    def recommend(self, pr_ctx: dict) -> str:
        x = np.array(
            [pr_ctx["lines"] / 5000.0, pr_ctx["files"] / 20.0, pr_ctx["hour"] / 24.0]
        )
        scores = {}
        for r in self.arms:
            inv = np.linalg.inv(self.A[r])
            theta = inv @ self.b[r]
            ucb = x @ theta + self.alpha * np.sqrt(x @ inv @ x)
            # 多目标奖励估计 (历史均值近似)
            load_pen = self.load_tracker[r] / 10.0
            scores[r] = ucb * (self.w[0] + self.w[1]) - self.w[2] * load_pen
        best = max(scores, key=scores.get)
        self.load_tracker[best] += 1
        return best

    def update(
        self, pr_ctx: dict, reviewer: str, reward_speed: float, quality_score: float
    ):
        x = np.array(
            [pr_ctx["lines"] / 5000.0, pr_ctx["files"] / 20.0, pr_ctx["hour"] / 24.0]
        )
        # 帕累托标量化奖励
        load_pen = self.load_tracker.get(reviewer, 0) / 10.0
        r = self.w[0] * reward_speed + self.w[1] * quality_score - self.w[2] * load_pen

        self.A[reviewer] += np.outer(x, x)
        self.b[reviewer] += r * x
        self.load_tracker[reviewer] = max(0, self.load_tracker.get(reviewer, 0) - 0.5)
        logging.info(
            f"📈 LinUCB更新 | Reviewer: {reviewer} | R={r:.3f} (Spd:{reward_speed:.2f}, Q:{quality_score:.2f}, Ld:{load_pen:.2f})"
        )


if __name__ == "__main__":
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO", "your-org/quant")

    scheduler = ParetoLinUCB(
        arms=["dev-a", "sec-b", "infra-c"],
        alpha=1.2,
        w_speed=0.3,
        w_quality=0.5,
        w_load=0.2,
    )
    scheduler.init_github_scorer(token, repo)

    # 模拟调度闭环
    ctx = {"lines": 1200, "files": 8, "hour": 10, "pr_id": 45}
    rec = scheduler.recommend(ctx)
    print(f"🤖 推荐评审人: {rec}")

    # 模拟 GitHub 回调
    if scheduler.scorer:
        quality = scheduler.scorer.compute_pr_quality(ctx["pr_id"])
        scheduler.update(ctx, rec, reward_speed=0.85, quality_score=quality)
        print(f"✅ 质量打分: {quality:.3f} | 权重已更新")
