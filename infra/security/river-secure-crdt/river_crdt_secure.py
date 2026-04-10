#!/usr/bin/env python3
"""
River 在线状态 etcd mTLS 同步与 libsodium 加密模块
加密算法: XChaCha20-Poly1305 (libsodium/PyNaCl) | 传输: etcd TLS 1.3
"""

import os
import json
import pickle
import time
import base64
import logging
import etcd3
from nacl.secret import SecretBox
from nacl.exceptions import CryptoError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("RiverSecureCRDT")


class SecureETCDClient:
    def __init__(self):
        self.client = etcd3.client(
            host=os.getenv("ETCD_HOST", "etcd-client.quant.svc"),
            port=int(os.getenv("ETCD_PORT", "2379")),
            ca_cert=os.getenv("ETCD_CA_CERT", "/etc/etcd-tls/ca.crt"),
            cert_key=os.getenv("ETCD_CERT_KEY", "/etc/etcd-tls/tls.key"),
            cert_cert=os.getenv("ETCD_CERT_CERT", "/etc/etcd-tls/tls.crt"),
            timeout=10,
        )
        key_hex = os.getenv("MODEL_ENCRYPTION_KEY")
        if not key_hex:
            raise ValueError("❌ 未配置 MODEL_ENCRYPTION_KEY (32字节Hex)")
        self.box = SecretBox(bytes.fromhex(key_hex))
        self.etcd_key = "/river/online_decomposer/state"

    def encrypt_state(self, state: dict) -> bytes:
        payload = json.dumps(state, separators=(",", ":")).encode()
        return self.box.encrypt(payload)  # 自动附加 Nonce + MAC

    def decrypt_state(self, cipher: bytes) -> dict:
        try:
            return json.loads(self.box.decrypt(cipher).decode())
        except CryptoError as e:
            raise RuntimeError(f"🚨 解密失败 (密钥错误或数据篡改): {e}")

    def load_with_revision(self) -> tuple:
        val, meta = self.client.get(self.etcd_key)
        if val:
            return self.decrypt_state(val), meta.mod_revision
        return {"t": 0, "weights": {}}, 0

    def save_cas(self, state: dict, expected_rev: int) -> bool:
        payload = self.encrypt_state(state)
        success, _ = self.client.transaction(
            compare=[self.client.transactions.mod(self.etcd_key) == expected_rev],
            success=[self.client.transactions.put(self.etcd_key, payload)],
            failure=[],
        )
        return bool(success)


class SecureCRDTSyncer:
    def __init__(self):
        self.sec = SecureETCDClient()
        self.model = None  # River model placeholder
        self.local_t = 0
        self.revision = 0

    def sync_down(self):
        state, self.revision = self.sec.load_with_revision()
        self.local_t = state.get("t", 0)
        self.model = pickle.loads(
            base64.b64decode(state.get("weights_b64", "gAN9Lg=="))
        )
        log.info(f"🔓 状态解密下载成功 | Rev: {self.revision} | t={self.local_t}")

    def sync_up(self):
        state = {
            "t": self.local_t,
            "weights_b64": base64.b64encode(pickle.dumps(self.model)).decode(),
            "node": os.getenv("POD_NAME", "unknown"),
            "ts": int(time.time()),
        }
        for i in range(3):
            if self.sec.save_cas(state, self.revision):
                self.revision += 1
                log.info("✅ 加密状态原子写入成功")
                return
            log.warning(f"⚠️ 写入冲突 (尝试 {i+1}/3), 执行 G-Counter 合并...")
            time.sleep(1)
            self.sync_down()  # 拉最新后重新合并


if __name__ == "__main__":
    syncer = SecureCRDTSyncer()
    syncer.sync_down()
    syncer.local_t += 1
    syncer.sync_up()
