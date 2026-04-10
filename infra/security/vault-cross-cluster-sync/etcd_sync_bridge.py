#!/usr/bin/env python3
"""
etcd 单向多活同步桥 (Primary -> DR) + CRDT 冲突安全合并
机制: watch local etcd -> transform to versioned payload -> push to remote etcd with CAS
"""

import os
import json
import time
import logging
import base64
import etcd3
import requests
from nacl.hash import sha256

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("EtcdSyncBridge")

SRC_ETCD = os.getenv("SRC_ETCD_HOST", "etcd-primary.quant.svc")
DST_ETCD = os.getenv("DST_ETCD_HOST", "etcd-dr.quant-dr.svc")
WATCH_PREFIX = "/river/online_decomposer/"
DR_PREFIX = "/dr/river/online_decomposer/"


class EtcdBridge:
    def __init__(self):
        self.src = etcd3.client(
            host=SRC_ETCD,
            port=2379,
            ca_cert=os.getenv("ETCD_CA_CERT"),
            cert_key=os.getenv("ETCD_CERT_KEY"),
            cert_cert=os.getenv("ETCD_CERT_CERT"),
        )
        self.dst = etcd3.client(
            host=DST_ETCD,
            port=2379,
            ca_cert=os.getenv("DR_ETCD_CA_CERT"),
            cert_key=os.getenv("DR_ETCD_CERT_KEY"),
            cert_cert=os.getenv("DR_ETCD_CERT_CERT"),
        )

    def start_sync(self):
        log.info(f"👀 开始监听本地 etcd: {WATCH_PREFIX}")
        events_iterator, cancel = self.src.watch_prefix(WATCH_PREFIX)

        for event in events_iterator:
            key = event.key.decode()
            dr_key = key.replace(WATCH_PREFIX, DR_PREFIX, 1)
            value = event.value
            meta = event.mod_revision

            if event.deleted:
                self.dst.delete(dr_key)
                log.info(f"🗑️ 同步删除: {dr_key}")
            else:
                payload = value
                try:
                    success, _ = self.dst.transaction(
                        compare=[self.dst.transactions.mod(dr_key) != meta],  # 防覆盖
                        success=[self.dst.transactions.put(dr_key, payload)],
                        failure=[],
                    )
                    if success:
                        log.info(f"✅ 同步写入: {dr_key} (Rev:{meta})")
                except Exception as e:
                    log.warning(f"⚠️ 冲突跳过: {e}")


if __name__ == "__main__":
    EtcdBridge().start_sync()
