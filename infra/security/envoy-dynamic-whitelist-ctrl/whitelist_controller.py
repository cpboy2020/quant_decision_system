#!/usr/bin/env python3
"""
K8s ConfigMap 监听器 -> Envoy Admin API 推送动态白名单
机制: watch whitelist-cm -> 编译为 JSON -> POST /runtime_modify 或 patch EnvoyFilter.configuration
"""
import os, json, logging, time
import yaml
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("WhitelistCtrl")

CM_NAME = "envoy-metric-whitelist"
CM_NS = "istio-system"
ENVOY_FILTER_NAME = "envoy-metric-pruner"
ENVOY_FILTER_NS = "istio-system"

def patch_envoy_filter_config(new_patterns: list):
    """原子更新 EnvoyFilter vm_config.configuration 触发热重载"""
    config_payload = json.dumps({"whitelist_patterns": new_patterns, "updated_at": int(time.time())})
    
    try:
        config.load_incluster_config()
        api = client.CustomObjectsApi()
        api.patch_namespaced_custom_object(
            group="networking.istio.io", version="v1alpha3",
            namespace=ENVOY_FILTER_NS, plural="envoyfilters", name=ENVOY_FILTER_NAME,
            body={"spec": {"configPatches": [{"applyTo": "HTTP_FILTER", "patch": {"operation": "MERGE", "value": {"typed_config": {"@type": "type.googleapis.com/udpa.type.v1.TypedStruct", "type_url": "type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm", "value": {"config": {"vm_config": {"configuration": {"@type": "type.googleapis.com/google.protobuf.StringValue", "value": config_payload}}}}}}}]}}
        )
        log.info(f"✅ EnvoyFilter 配置已热更新 | Patterns: {new_patterns}")
    except ApiException as e:
        log.error(f"❌ 更新失败: {e}")

def main():
    config.load_incluster_config()
    w = watch.Watch()
    core = client.CoreV1Api()
    log.info("👀 开始监听 ConfigMap: istio-system/envoy-metric-whitelist")
    
    for event in w.stream(core.list_namespaced_config_map, namespace=CM_NS, timeout_seconds=0):
        obj = event["object"]
        if obj.metadata.name == CM_NAME:
            data = obj.data.get("whitelist.json")
            if data:
                try:
                    patterns = json.loads(data)["patterns"]
                    patch_envoy_filter_config(patterns)
                except Exception as e: log.warning(f"⚠️ 解析 ConfigMap 失败: {e}")

if __name__ == "__main__": main()
