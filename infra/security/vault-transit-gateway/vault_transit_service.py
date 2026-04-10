#!/usr/bin/env python3
"""
Vault Transit 解密网关: 支持自动版本解析、关联数据 (AAD) 校验、解密缓存
替代本地 PyNaCl, 实现密钥集中轮换、操作全量审计、版本无缝迁移
"""

import os
import json
import time
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks
import hvac
import etcd3
from functools import lru_cache

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Vault Transit Decryption Gateway")

client = hvac.Client(url=os.getenv("VAULT_ADDR", "http://vault:8200"))
client.token = os.getenv("VAULT_TOKEN")  # 生产请使用 AppRole/K8s Auth
etcd = etcd3.client(host="etcd-client.quant.svc", port=2379)

# 启用 Transit 引擎 (仅首次)
try:
    client.sys.enable_secrets_engine(backend_type="transit")
except:
    pass
try:
    client.secrets.transit.create_or_update_key(
        name="river-state", key_type="aes256-gcm96"
    )
except:
    pass


class VaultDecryptionCache:
    def __init__(self, maxsize=5000):
        self.cache = {}
        self.maxsize = maxsize
        self.last_cleanup = time.time()

    def get(self, key: str):
        if key in self.cache:
            return self.cache[key]
        return None

    def put(self, key: str, val: dict):
        if len(self.cache) >= self.maxsize:
            self.cache = dict(list(self.cache.items())[-self.maxsize :])
        self.cache[key] = val


cache = VaultDecryptionCache()


@app.post("/decrypt-state")
async def decrypt_state(ciphertext: str, context: str = "river_crdt_v1"):
    # Vault 密文格式: vault:vN:base64...  自动带版本
    cache_key = f"{ciphertext}:{context}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    try:
        resp = client.secrets.transit.decrypt_data(
            name="river-state", ciphertext=ciphertext, context=context
        )
        plaintext = resp["data"]["plaintext"]
        version = ciphertext.split(":")[1]
        result = {"plaintext": plaintext, "version": version, "status": "success"}
        cache.put(cache_key, result)
        return result
    except Exception as e:
        logging.error(f"❌ Transit 解密失败: {e}")
        raise HTTPException(400, f"解密异常: {e}")


@app.post("/reencrypt-latest")
async def reencrypt_to_latest(ciphertext: str, context: str = "river_crdt_v1"):
    """零停机密钥轮换: 将旧版本密文重加密至最新密钥版本"""
    try:
        pt_resp = client.secrets.transit.decrypt_data(
            name="river-state", ciphertext=ciphertext, context=context
        )
        new_ct = client.secrets.transit.rewrap_data(
            name="river-state", ciphertext=ciphertext, context=context
        )
        logging.info(f"✅ 密文已重加密至最新版本 | 原版本: {ciphertext.split(':')[1]}")
        return {"new_ciphertext": new_ct["data"]["ciphertext"]}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.on_event("startup")
def init_etcd_watch():
    """监听 etcd 旧密文, 异步触发重加密 (防密钥老化)"""

    def callback(event):
        ct = event.value.decode()
        if ct.startswith("vault:v") and not ct.startswith(
            "vault:v15"
        ):  # v15 为当前最新
            app.state.reencrypt_queue.put(ct)

    etcd.add_event_callback("/river/online_decomposer/state", callback, range_end="")
