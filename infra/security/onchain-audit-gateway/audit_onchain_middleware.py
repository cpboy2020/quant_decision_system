#!/usr/bin/env python3
"""
热更新审计上链网关: 拦截 Patch 请求 → 生成防重放签名 → 提交联盟链 JSON-RPC → 返回 TxHash
兼容: FISCO BCOS / Quorum / 任意 EVM 链
"""

import os
import json
import time
import hmac
import hashlib
import logging
from fastapi import Request, HTTPException
import requests
from ecdsa import SigningKey, NIST256p

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("OnChainAuditGateway")

AUDIT_PRIVATE_KEY = os.getenv("AUDIT_ECDSA_PRIVKEY")  # PEM/Hex 格式
CHAIN_RPC_URL = os.getenv("CHAIN_RPC_URL", "http://consortium-chain-rpc:8545")
CHAIN_CONTRACT_ADDR = os.getenv("AUDIT_CONTRACT_ADDR", "0x...")
NONCE_WINDOW_SEC = 300  # 5分钟防重放窗口


def generate_signature(user: str, cm_name: str, reason: str, ts: int) -> tuple:
    if not AUDIT_PRIVATE_KEY:
        raise HTTPException(500, "未配置审计私钥")
    sk = SigningKey.from_string(bytes.fromhex(AUDIT_PRIVATE_KEY), curve=NIST256p)
    msg = f"{user}|{cm_name}|{reason}|{ts}".encode()
    sig_hex = sk.sign(msg).hex()
    return sig_hex


def submit_to_chain(payload: dict, sig: str) -> str:
    tx_data = {
        "jsonrpc": "2.0",
        "method": "eth_sendTransaction",
        "params": [
            {
                "from": "0x...gateway_account...",
                "to": CHAIN_CONTRACT_ADDR,
                "data": "0x" + json.dumps(payload).encode().hex() + sig,
            }
        ],
        "id": 1,
    }
    try:
        r = requests.post(CHAIN_RPC_URL, json=tx_data, timeout=5)
        r.raise_for_status()
        return r.json()["result"]
    except Exception as e:
        log.error(f"❌ 链上提交失败: {e}")
        raise HTTPException(502, "联盟链 RPC 调用异常")


async def audit_middleware(request: Request):
    user = request.headers.get("x-forwarded-user", "unknown")
    body = await request.json()
    cm_name = request.path_params.get("name", "unknown")
    reason = body.get("reason", "manual")
    ts = int(time.time() // NONCE_WINDOW_SEC)  # 时间窗口 Nonce

    # 1. 防重放校验
    req_nonce = request.headers.get("X-Audit-Nonce", "0")
    if abs(int(req_nonce) - ts) > 2:  # 允许 ±1 个窗口漂移
        raise HTTPException(401, "请求已过期 (防重放拦截)")

    # 2. 签名与上链
    sig = generate_signature(user, cm_name, reason, ts)
    payload = {
        "user": user,
        "cm": cm_name,
        "reason": reason,
        "ts": ts,
        "nonce": req_nonce,
    }
    tx_hash = submit_to_chain(payload, sig)
    log.info(f"🔗 审计哈希已上链 | TxHash: {tx_hash}")

    # 将 TxHash 注入响应头 (由下游 FastAPI 读取)
    request.state.audit_tx_hash = tx_hash
    return request


# 使用方式: 在 FastAPI 路由中调用 await audit_middleware(request)
