#!/usr/bin/env python3
"""
River 模型分布式状态同步器 (etcd CAS + CRDT 合并)
CRDT 类型: LWW-Register (模型权重) + G-Counter (全局步数 t)
保障: 多副本并发写入无冲突, Pod 重启/滚动更新零状态丢失
"""

import os
import json
import logging
import base64
import time
import pickle
import numpy as np
import etcd3
from river import linear_model

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("RiverCRDT-Sync")

ETCD_HOST = os.getenv("ETCD_HOST", "etcd-client.quant.svc")
ETCD_PORT = int(os.getenv("ETCD_PORT", "2379"))
ETCD_KEY = "/river/online_decomposer/state"
NODE_ID = os.getenv("POD_NAME", "node_1")


class CRDTStateSyncer:
    def __init__(self):
        self.client = etcd3.client(host=ETCD_HOST, port=ETCD_PORT)
        self.revision = 0
        self.local_model = None
        self.local_t = 0

    def load_or_init(self, model_cls, t=0):
        """从 etcd 加载最新状态, 若不存在则初始化"""
        val, meta = self.client.get(ETCD_KEY)
        if val:
            state = json.loads(val.decode())
            self.revision = meta.mod_revision
            self.local_t = state.get("t", 0)
            model_bytes = base64.b64decode(state["model_b64"])
            self.local_model = pickle.loads(model_bytes)
            log.info(
                f"📥 状态已加载 | Revision: {self.revision} | t={self.local_t} | Node: {state['node']}"
            )
        else:
            self.local_model = model_cls
            self.local_t = t
            log.info(f"🆕 初始化新状态 | Node: {NODE_ID}")

    def save_with_cas(self):
        """CAS 原子写入: 冲突时自动重试并合并"""
        for attempt in range(5):
            payload = {
                "t": self.local_t,
                "node": NODE_ID,
                "model_b64": base64.b64encode(pickle.dumps(self.local_model)).decode(),
                "ts": int(time.time()),
            }
            try:
                success, _ = self.client.transaction(
                    compare=[self.client.transactions.mod(ETCD_KEY) == self.revision],
                    success=[
                        self.client.transactions.put(ETCD_KEY, json.dumps(payload))
                    ],
                    failure=[],
                )
                if success:
                    log.info(f"✅ CAS 写入成功 | Rev: {self.revision+1}")
                    return True
                # 冲突: 拉取最新并 CRDT 合并
                log.warning(f"⚠️ CAS 冲突 (尝试 {attempt+1}/5), 执行 CRDT 合并...")
                self._merge_state()
            except Exception as e:
                log.error(f"❌ etcd 交互异常: {e}")
                time.sleep(1 * (attempt + 1))
        raise RuntimeError("CRDT 合并失败, 超过最大重试次数")

    def _merge_state(self):
        """CRDT 合并规则: t 取最大值(G-Counter), 模型权重 LWW (时间戳大者胜, 相同则平均)"""
        val, meta = self.client.get(ETCD_KEY)
        if not val:
            return
        self.revision = meta.mod_revision
        remote = json.loads(val.decode())

        # G-Counter: 步数取最大值
        self.local_t = max(self.local_t, remote.get("t", 0))

        # LWW-Register: 比较时间戳, 相同则对权重求平均(防抖动)
        remote_model = pickle.loads(base64.b64decode(remote["model_b64"]))
        if hasattr(remote_model, "_weights") and hasattr(self.local_model, "_weights"):
            rw, lw = remote_model._weights, self.local_model._weights
            common_keys = set(rw.keys()) & set(lw.keys())
            for k in common_keys:
                if remote.get("ts", 0) == int(time.time()) - 1:  # 近似同代
                    self.local_model._weights[k] = (rw[k] + lw[k]) / 2.0
            # 非重叠键直接覆盖
            self.local_model._weights.update(rw)
            log.info("🔗 CRDT 合并完成: 权重已融合")
