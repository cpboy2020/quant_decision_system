#!/usr/bin/env python3
"""
Markdown 报告自动归档与企微/SRE 频道推送器
支持: S3/MinIO 归档 + Webhook 推送 (企微/钉钉/Slack) + 失败重试
"""

import os
import glob
import logging
import time
import json
import requests
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from datetime import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("ReportPusher")

# 配置
S3_BUCKET = os.getenv("S3_BUCKET", "quant-audit-reports")
S3_PREFIX = "reports/rootcause/"
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
ENDPOINT = os.getenv("S3_ENDPOINT_URL", None)
WEBHOOK_URL = os.getenv("IM_WEBHOOK_URL", "")
REPORT_DIR = os.getenv("REPORT_DIR", "/tmp/reports")
MAX_RETRIES = 3


def upload_to_s3(filepath: str) -> str:
    """上传报告至 S3/MinIO"""
    s3 = boto3.client(
        "s3",
        region_name=REGION,
        endpoint_url=ENDPOINT,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )
    key = f"{S3_PREFIX}{os.path.basename(filepath)}"
    try:
        s3.upload_file(
            filepath, S3_BUCKET, key, ExtraArgs={"ContentType": "text/markdown"}
        )
        log.info(f"✅ S3 归档成功: s3://{S3_BUCKET}/{key}")
        return key
    except ClientError as e:
        log.error(f"❌ S3 上传失败: {e}")
        raise


def send_webhook(filepath: str, s3_key: str) -> bool:
    """推送至企微/钉钉/Slack Webhook"""
    if not WEBHOOK_URL:
        log.warning("⚠️ 未配置 WEBHOOK_URL，跳过推送")
        return False
    fname = os.path.basename(filepath)
    lines = open(filepath, "r", encoding="utf-8").readlines()
    summary = "".join(
        [l.strip() for l in lines[:15] if not l.startswith("#") and l.strip()]
    )[:200]

    # 企微 Markdown 格式
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"### 🕳️ 根因分析报告归档\n"
            f"**文件**: `{fname}`\n"
            f"**时间**: `{datetime.utcnow().isoformat()}Z`\n"
            f"**摘要**: {summary}...\n"
            f"**下载**: [S3 链接](s3://{S3_BUCKET}/{s3_key})"
        },
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(
                WEBHOOK_URL,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            log.info("✅ Webhook 推送成功")
            return True
        except Exception as e:
            log.warning(f"⚠️ 推送失败 (尝试 {attempt}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2**attempt)
    return False


def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(REPORT_DIR, "rootcause_*.md")))
    if not files:
        log.info("ℹ️ 无待推送报告，退出")
        return
    latest = files[-1]
    log.info(f"📦 发现最新报告: {latest}")
    s3_key = upload_to_s3(latest)
    send_webhook(latest, s3_key)
    # 清理本地旧文件 (保留最近 3 份)
    for old in files[:-3]:
        os.remove(old)


if __name__ == "__main__":
    main()
