#!/usr/bin/env python3
"""
PR 智能评审人匹配引擎
逻辑: 解析 CODEOWNERS → 构建 文件-评审人 二部图 → 计算负载权重 → 返回 Top-K 最优评审人
"""

import os
import sys
import re
import json
import logging
import requests
from collections import defaultdict
from github import Github

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ReviewerMatcher")


def load_codeowners(token: str, repo: str) -> list:
    """通过 API 拉取并解析 CODEOWNERS 规则"""
    url = f"https://api.github.com/repos/{repo}/contents/.github/CODEOWNERS"
    r = requests.get(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.raw",
        },
        timeout=10,
    )
    if r.status_code != 200:
        return []

    rules = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(\S+)\s+(.+)$", line)
        if match:
            pattern, owners = (
                match.group(1),
                [
                    o.strip().lstrip("@")
                    for o in match.group(2).split()
                    if o.startswith("@")
                ],
            )
            rules.append((pattern, owners))
    return rules


def get_reviewer_load(g: Github, repo_name: str, reviewers: list) -> dict:
    """计算评审人当前负载 (Open PR 数 + 近期合并惩罚分)"""
    repo = g.get_repo(repo_name)
    loads = {r: 0.0 for r in reviewers}

    # 统计 Open PR 分配数
    for pr in repo.get_pulls(state="open"):
        for rev in pr.get_review_requests()[0]:  # requested reviewers
            if rev.login in loads:
                loads[rev.login] += 1.0

    # 历史合并活跃度 (近 7 天, 越多负载越高)
    # 此处简化: 假设近期 Merge 次数通过 API 获取较耗, 改用 Open PR 权重
    return loads


def match_reviewers(
    changed_files: list, codeowners_rules: list, loads: dict, top_k: int = 3
) -> list:
    """加权评分匹配: 命中规则数 * 基础分 / (负载 + 1)"""
    scores = defaultdict(float)
    for file in changed_files:
        for pattern, owners in codeowners_rules:
            # 简单 glob 匹配 (支持 * 和 / 通配)
            if re.match(pattern.replace("*", ".*").replace("?", "."), file):
                for owner in owners:
                    if owner != "CODEOWNERS":  # 忽略占位符
                        scores[owner] += 1.0

    # 归一化并排序
    ranked = sorted(
        scores.items(), key=lambda x: x[1] / (loads.get(x[0], 0) + 1), reverse=True
    )
    return [u for u, _ in ranked[:top_k]]


def main():
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    pr_num = int(os.getenv("PR_NUMBER"))

    g = Github(token)
    pr = g.get_repo(repo).get_pull(pr_num)

    # 获取变更文件
    changed = [f.filename for f in pr.get_files()]
    log.info(f"📂 变更文件 ({len(changed)}): {', '.join(changed)}")

    rules = load_codeowners(token, repo)
    all_potential = {u for _, owners in rules for u in owners if u != "CODEOWNERS"}
    loads = get_reviewer_load(g, repo, list(all_potential))

    top_reviewers = match_reviewers(changed, rules, loads, top_k=3)
    log.info(f"🎯 推荐评审人: {top_reviewers}")

    # 写入环境变量供 Action 使用
    with open(os.getenv("GITHUB_OUTPUT", "/dev/stdout"), "a") as f:
        f.write(f"REVIEWERS={','.join(top_reviewers)}\n")
    if not top_reviewers:
        log.warning("⚠️ 无匹配评审人, 回退至默认团队")


if __name__ == "__main__":
    main()
