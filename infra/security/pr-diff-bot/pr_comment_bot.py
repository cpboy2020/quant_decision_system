#!/usr/bin/env python3
"""
GitHub PR Bot 评论渲染器 (PyGithub + Markdown 差异表格)
功能: 解析 Rego Diff JSON → 渲染 Markdown 表格 → 幂等更新 PR 评论
"""

import os
import sys
import json
import logging
from github import Github
from github.GithubException import GithubException

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PRCommentBot")


def render_markdown_table(diff_data: dict) -> str:
    """渲染差异表格与风险卡片"""
    score, risk = (
        diff_data.get("security_score", 0),
        diff_data.get("risk_level", "UNKNOWN"),
    )
    emoji = "✅" if risk in ["LOW", "MEDIUM"] else "🚨" if risk == "HIGH" else "💥"

    lines = [
        f"### {emoji} Rego 策略变更分析报告",
        f"**安全评分**: `{score}/100` | **风险等级**: `{risk}`",
        f"**变更统计**: 新增 `{len(diff_data.get('added',[]))}` | 删除 `{len(diff_data.get('removed',[]))}` | 修改 `{len(diff_data.get('modified',[]))}`",
        "",
        "<details>",
        "<summary>📊 变更详情与依赖传播</summary>",
        "",
        "| 规则/依赖 | 状态 | 权重影响 | 说明 |",
        "|:---|:---:|:---:|:---|",
    ]

    for r in diff_data.get("added", []):
        lines.append(f"| `{r}` | ➕ 新增 | ⚠️ 高 | 新增策略规则")
    for r in diff_data.get("removed", []):
        lines.append(f"| `{r}` | ➖ 删除 | ⚠️ 高 | 策略规则移除")
    for r in diff_data.get("modified", []):
        lines.append(f"| `{r}` | 🔄 修改 | 🔸 中 | 条件逻辑变更")
    if diff_data.get("imports_changed"):
        lines.append("| `import ...` | 📦 变更 | ⚠️ 高 | 依赖路径变更")

    lines += (
        [
            "",
            "</details>",
            "",
            "**🛡️ 智能建议**:",
        ]
        + [f"- {r}" for r in diff_data.get("recommendations", [])]
        + [""]
    )

    return "\n".join(lines)


def post_or_update_pr_comment(repo_full_name: str, pr_number: int, diff_json_path: str):
    """幂等发布/更新评论"""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        log.error("❌ 未配置 GITHUB_TOKEN 环境变量")
        sys.exit(1)

    g = Github(token)
    repo = g.get_repo(repo_full_name)
    pr = repo.get_pull(pr_number)

    with open(diff_json_path, "r") as f:
        diff_data = json.load(f)
    body = render_markdown_table(diff_data)
    bot_id = "🤖 rego-policy-auditor"

    # 查找历史评论并更新 (防刷屏)
    for comment in pr.get_issue_comments():
        if bot_id in comment.body:
            log.info(f"🔄 更新现有 PR #{pr_number} 评论...")
            comment.edit(f"{bot_id}\n---\n{body}")
            return

    log.info(f"📤 创建新评论至 PR #{pr_number}...")
    pr.create_issue_comment(f"{bot_id}\n---\n{body}")
    log.info("✅ PR 评论发布成功")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python pr_comment_bot.py <owner/repo> <pr_number> <diff.json>")
        sys.exit(1)
    post_or_update_pr_comment(sys.argv[1], int(sys.argv[2]), sys.argv[3])
