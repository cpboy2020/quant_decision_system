#!/usr/bin/env python3
"""
ConfigMap 实时热更新 API (受 kube-rbac-proxy 保护, 仅暴露本地 FastAPI)
端点: PATCH /api/v1/configmaps/{ns}/{name}
"""

import os
import logging
import json
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from kubernetes import client, config
from typing import Dict, Any

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
app = FastAPI(title="Secure ConfigMap Hot-Update API", version="1.0.0")


class PatchPayload(BaseModel):
    data: Dict[str, Any] = Field(..., max_items=20, description="键值对配置")
    reason: str = Field(
        ..., min_length=5, max_length=200, description="变更原因审计字段"
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.patch("/api/v1/configmaps/{namespace}/{name}")
async def patch_configmap(
    namespace: str, name: str, payload: PatchPayload, req: Request
):
    # kube-rbac-proxy 会将认证后的 SA 信息注入 Header
    user = req.headers.get("x-forwarded-user", "unknown")
    logging.info(f"🔐 收到热更新请求 | User: {user} | Target: {namespace}/{name}")

    try:
        config.load_incluster_config()
        api = client.CoreV1Api()
        # 读取当前 CM (防并发覆盖)
        cm = api.read_namespaced_config_map(name, namespace)
        cm.data.update(payload.data)
        cm.metadata.annotations["security.quant.io/last_updated_by"] = user
        cm.metadata.annotations["security.quant.io/change_reason"] = payload.reason

        api.patch_namespaced_config_map(name, namespace, cm)
        return {
            "status": "success",
            "updated_keys": list(payload.data.keys()),
            "user": user,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"K8s API 失败: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="info")
