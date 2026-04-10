# 替换原 river_crdt_secure.py 中的加解密逻辑, 调用网关
import requests
import os
import json

VAULT_GW = os.getenv("VAULT_GATEWAY_URL", "http://localhost:8180/decrypt-state")


def decrypt_from_vault(ciphertext: str, ctx="river_crdt_v1"):
    r = requests.post(
        VAULT_GW, json={"ciphertext": ciphertext, "context": ctx}, timeout=5
    )
    r.raise_for_status()
    return json.loads(r.json()["plaintext"])


def encrypt_for_vault(plaintext: dict, ctx="river_crdt_v1") -> str:
    # 生产应调用网关 /encrypt 接口, 此处占位
    pass
