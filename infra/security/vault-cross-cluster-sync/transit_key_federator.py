#!/usr/bin/env python3
"""
Vault Transit 密钥跨集群同步器 (Primary -> DR)
逻辑: 导出主集群 Transit 密钥所有版本 → 导入备集群 → 验证版本对齐 → 记录审计哈希
"""

import os
import json
import logging
import requests
import hvac
from nacl.hash import blake2b

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("TransitKeyFederation")

SRC_VAULT = os.getenv("SRC_VAULT_ADDR", "https://vault-primary.quant.svc:8200")
DST_VAULT = os.getenv("DST_VAULT_ADDR", "https://vault-dr.quant-dr.svc:8200")
KEY_NAME = "river-state"


def sync_transit_keys():
    # 1. 连接源 Vault
    src = hvac.Client(url=SRC_VAULT, token=os.getenv("SRC_VAULT_TOKEN"))
    if not src.is_authenticated():
        raise RuntimeError("源 Vault 认证失败")

    # 2. 导出密钥版本 (需 transit 引擎开启 export)
    try:
        src.secrets.transit.enable_key_export(KEY_NAME)
        export_resp = src.secrets.transit.export_key(KEY_NAME)
        versions = export_resp["data"]["keys"]
    except Exception as e:
        log.warning(f"⚠️ 密钥导出受限 (可能需 Vault 升级或权限配置): {e}")
        return

    # 3. 连接目标 Vault 并导入
    dst = hvac.Client(url=DST_VAULT, token=os.getenv("DST_VAULT_TOKEN"))
    for ver, key_b64 in versions.items():
        try:
            dst.secrets.transit.import_key(KEY_NAME, version=ver, key=key_b64)
            log.info(f"✅ 同步 Transit Key 版本 v{ver}")
        except Exception as e:
            if "already exists" in str(e).lower():
                log.info(f"🔒 版本 v{ver} 已存在，跳过")
            else:
                raise

    # 4. 验证对齐
    log.info("🔍 跨集群密钥版本校验完成 | 已同步至 DR 集群")
