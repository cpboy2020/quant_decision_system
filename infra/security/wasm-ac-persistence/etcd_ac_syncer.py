#!/usr/bin/env python3
"""
etcd -> Envoy 配置桥接器
监听 etcd /wasm/ac_patterns 变更 → 差分合并 → 调用 Envoy Admin API 触发 WASM Reconfigure
"""

import os
import json
import time
import logging
import requests
import etcd3

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("EtcdACSyncer")

ETCD_HOST = os.getenv("ETCD_HOST", "etcd-client.quant.svc")
ENVOY_ADMIN = os.getenv("ENVOY_ADMIN", "http://localhost:19000")
FILTER_NAME = os.getenv("FILTER_NAME", "envoy.filters.http.ac_diff")


def trigger_wasm_reconfigure(diff_patch: dict):
    """通过 Envoy Admin API 热更新 WASM 配置"""
    payload = {
        "name": "ac_diff_config",
        "dynamic_resources": {"lds_config": {"path": "/etc/envoy/lds.yaml"}},
        "filter_chains": [],
        "wasm_filters": [{"name": FILTER_NAME, "config": json.dumps(diff_patch)}],
    }
    try:
        r = requests.post(f"{ENVOY_ADMIN}/config_dump", json=payload, timeout=3)
        r.raise_for_status()
        log.info("✅ WASM AC 配置已热推至 Envoy")
    except Exception as e:
        log.error(f"❌ Envoy 配置推送失败: {e}")


def watch_etcd_and_sync():
    client = etcd3.client(host=ETCD_HOST, port=2379)
    log.info(f"👀 开始监听 etcd: /wasm/ac_patterns")
    rev, _ = client.get("/wasm/ac_patterns/revision")

    def watch_cb(event):
        if event.value:
            patch = json.loads(event.value)
            log.info(
                f"📥 捕获 AC 变更 | Add: {len(patch.get('add',[]))}, Remove: {len(patch.get('remove',[]))}"
            )
            trigger_wasm_reconfigure(patch)

    client.add_watch_callback("/wasm/ac_patterns", watch_cb)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    watch_etcd_and_sync()
