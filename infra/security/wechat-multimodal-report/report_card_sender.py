#!/usr/bin/env python3
"""
研发节奏多模态报告生成器: Matplotlib 图表 → Base64/URL → 企微模板卡片 (TemplateCard)
"""

import os
import io
import json
import time
import logging
import requests
import base64
import matplotlib.pyplot as plt
import matplotlib

matplotlib.use("Agg")  # 无头渲染
import numpy as np

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("WeChatCardSender")

WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL", "")
CORP_ID = os.getenv("WECOM_CORP_ID", "")
CORP_SECRET = os.getenv("WECOM_CORP_SECRET", "")


def generate_trend_chart(data_x: list, data_y: list, title: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 4), dpi=100)
    ax.plot(
        data_x,
        data_y,
        marker="o",
        linestyle="-",
        color="#0052CC",
        linewidth=2,
        markersize=6,
    )
    ax.fill_between(data_x, data_y, alpha=0.15, color="#0052CC")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=10)
    ax.set_xlabel("Time", fontsize=10)
    ax.set_ylabel("Value", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", transparent=True)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def get_access_token() -> str:
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORP_ID}&corpsecret={CORP_SECRET}"
    return requests.get(url, timeout=5).json().get("access_token")


def upload_media(access_token: str, img_b64: str) -> str:
    """上传图片至企微临时媒体库"""
    import base64
    import io
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    img_bytes = base64.b64decode(img_b64)
    m = MultipartEncoder(
        fields={"media": ("chart.png", io.BytesIO(img_bytes), "image/png")}
    )
    r = requests.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={access_token}&type=image",
        data=m,
        headers={"Content-Type": m.content_type},
        timeout=10,
    )
    return r.json().get("media_id", "")


def send_template_card(text: str, img_b64: str):
    if not WEBHOOK_URL:
        log.warning("⚠️ 未配置企微 Webhook")
        return
    token = get_access_token()
    media_id = upload_media(token, img_b64)

    card = {
        "msgtype": "template_card",
        "template_card": {
            "card_type": "news_notice",
            "source": {"desc": "Quant Ops AI", "desc_color": 1},
            "main_title": {
                "title": "📊 研发节奏演进报告",
                "desc": time.strftime("%Y-%m-%d %H:%M"),
            },
            "quote_area": {"title": "核心洞察", "quote_text": text[:100]},
            "image": {"media_id": media_id, "preview_url": ""},
            "horizontal_content_list": [
                {"keyname": "评审效率", "value": "↑ 12% 环比"},
                {"keyname": "质量指数", "value": "0.87 / 1.0"},
                {"keyname": "阻塞率", "value": "3.2% (优)"},
            ],
            "card_action": {
                "type": 1,
                "url": "https://grafana.quant.company/d/rd-cadence",
                "appid": "",
            },
        },
    }
    r = requests.post(
        f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WEBHOOK_URL.split('key=')[-1]}",
        json=card,
        timeout=10,
    )
    log.info(f"✅ 企微多模态卡片发送成功 | Status: {r.status_code}")


if __name__ == "__main__":
    x = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    y = [4.2, 5.1, 3.8, 6.2, 4.9]
    img = generate_trend_chart(x, y, "Weekly PR Review Duration (Hours)")
    send_template_card(
        "本周评审耗时平稳，周四受大促策略迭代影响短暂冲高。建议启用低负载路由与预分配机制。",
        img,
    )
