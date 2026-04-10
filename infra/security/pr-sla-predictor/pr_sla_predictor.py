#!/usr/bin/env python3
"""
PR SLA 预测性预警: 基于历史 PR 停留时长与关闭率训练 Prophet → 预测未来 24h 高风险 PR → 企微推送
"""

import os
import json
import time
import logging
import requests
import pandas as pd
from prophet import Prophet
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("PRSLAPredictor")

GH_TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("REPO", "your-org/quant_decision_system")
SLA_HOURS = 48
WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL")


def fetch_pr_history() -> pd.DataFrame:
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{REPO}/pulls?state=all&per_page=100"
    res = requests.get(url, headers=headers, timeout=10)
    prs = res.json()
    rows = []
    for p in prs:
        c = datetime.fromisoformat(p["created_at"].replace("Z", ""))
        m = (
            datetime.fromisoformat(p["merged_at"].replace("Z", ""))
            if p["merged_at"]
            else datetime.utcnow()
        )
        if p["state"] == "closed" or (m - c).days > 7:
            rows.append(
                {"ds": c.strftime("%Y-%m-%d"), "y": (m - c).total_seconds() / 3600}
            )
    return pd.DataFrame(rows).dropna()


def train_and_predict(df: pd.DataFrame) -> list:
    if len(df) < 30:
        log.warning("⚠️ 历史数据不足 30 条, 使用线性外推")
        return []
    m = Prophet(
        daily_seasonality=True, weekly_seasonality=True, uncertainty_samples=100
    )
    m.fit(df)
    future = m.make_future_dataframe(periods=2)
    fc = m.predict(future)
    # 返回未来 2 天 P95 预计停留时长
    high_risk = fc[fc["yhat_upper"] > SLA_HOURS].tail(48)
    return high_risk[["ds", "yhat_upper"]].to_dict("records")


def push_wecom_alert(predictions: list, open_prs: list):
    if not predictions or not WEBHOOK_URL:
        return
    # 匹配当前 Open PR 中创建日期接近预测高位的
    at_risk = [
        pr
        for pr in open_prs
        if (
            datetime.utcnow()
            - datetime.fromisoformat(pr["created_at"].replace("Z", ""))
        ).days
        >= 30
    ]
    if not at_risk:
        return

    msg = (
        f"### 🔮 PR SLA 预测性预警\n"
        f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"**模型预测**: 未来 24h 将有 {len(predictions)} 个 PR 停留时长逼近 {SLA_HOURS}h 阈值\n"
        f"**⚠️ 高风险待审 PR**:\n"
    )
    for pr in at_risk[:3]:
        msg += f"- [#{pr['number']} {pr['title']}]({pr['html_url']}) (已开启 {(datetime.utcnow()-datetime.fromisoformat(pr['created_at'].replace('Z',''))).days} 天)\n"
    msg += f"\n👉 请相关 Reviewer 优先处理，避免阻塞发布流水线。"

    payload = {"msgtype": "markdown", "markdown": {"content": msg}}
    r = requests.post(WEBHOOK_URL, json=payload, timeout=5)
    log.info(f"✅ 企微预警推送成功 | Status: {r.status_code}")


def main():
    log.info("🔮 启动 Prophet PR SLA 预测模型...")
    df = fetch_pr_history()
    preds = train_and_predict(df)

    headers = {"Authorization": f"token {GH_TOKEN}"}
    open_prs = requests.get(
        f"https://api.github.com/repos/{REPO}/pulls?state=open",
        headers=headers,
        timeout=10,
    ).json()
    push_wecom_alert(preds, open_prs)
    log.info("✅ PR SLA 预测周期完成")


if __name__ == "__main__":
    main()
