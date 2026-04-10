#!/usr/bin/env python3
"""
WASM 正则自学习剪枝控制器 (EWMA + 频分淘汰)
逻辑: 拉取 Envoy 指标 → 计算 EWMA(延迟) × (1 - 命中率) → 低于阈值自动剔除 → 热更新 ConfigMap
"""

import os
import time
import json
import logging
import requests
import numpy as np
from kubernetes import client, config

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("RegexPruner")

ENVOY_METRICS_URL = os.getenv(
    "ENVOY_METRICS_URL", "http://localhost:15090/stats/prometheus"
)
CONFIG_MAP_NAME = "envoy-metric-whitelist"
CONFIG_MAP_NS = "istio-system"
ALPHA = 0.3  # EWMA 衰减系数
LATENCY_THRESHOLD_US = 800.0  # 超 800μs 视为高耗时
MIN_MATCH_RATE = 0.02  # 匹配率 < 2% 视为无效正则


class RegexEWMAPruner:
    def __init__(self):
        self.ewma_latency = {}
        self.match_counts = {}
        self.total_lines = 0

    def fetch_and_parse_metrics(self) -> dict:
        try:
            r = requests.get(ENVOY_METRICS_URL, timeout=5)
            r.raise_for_status()
            metrics = {"latency": {}, "matches": {}, "total": 0}
            for line in r.text.splitlines():
                if "wasm_canary_match_latency_us_count" in line:
                    parts = line.split()
                    name = parts[0].split("{")[1].split("=")[0]
                    metrics["latency"][name] = int(parts[1])
                elif "wasm_canary_match_total{" in line:
                    parts = line.split()
                    name = parts[0].split("pattern=")[1].split("}")[0]
                    metrics["matches"][name] = int(parts[1])
                    self.total_lines += int(parts[1])
            return metrics
        except Exception as e:
            log.warning(f"⚠️ 拉取指标失败: {e}")
            return {}

    def compute_prune_candidates(self, metrics: dict) -> list:
        prune_list = []
        for pattern, count in metrics["matches"].items():
            rate = count / max(self.total_lines, 1)
            # EWMA 平滑延迟
            lat = metrics["latency"].get(pattern, 0.0)
            self.ewma_latency[pattern] = ALPHA * lat + (
                1 - ALPHA
            ) * self.ewma_latency.get(pattern, 0.0)

            # 淘汰条件: 高延迟 且 低命中率
            ewma = self.ewma_latency[pattern]
            if ewma > LATENCY_THRESHOLD_US and rate < MIN_MATCH_RATE:
                prune_list.append(pattern)
                log.info(
                    f"🗑️ 触发淘汰 | Pattern: {pattern} | EWMA: {ewma:.1f}μs | Rate: {rate:.3f}"
                )
        return prune_list

    def apply_pruning(self, prune_list: list):
        if not prune_list:
            return
        config.load_incluster_config()
        api = client.CoreV1Api()
        cm = api.read_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS)
        current = json.loads(cm.data.get("whitelist.json", "{}")).get("patterns", [])
        new_patterns = [p for p in current if p not in prune_list]

        cm.data["whitelist.json"] = json.dumps(
            {"patterns": new_patterns, "pruned_at": time.time()}
        )
        api.patch_namespaced_config_map(CONFIG_MAP_NAME, CONFIG_MAP_NS, cm)
        log.info(f"✅ 正则列表已剪枝 | 剩余: {len(new_patterns)}/{len(current)} 条")

    def run(self, interval_sec=60):
        log.info("🚀 EWMA 正则自学习剪枝器启动")
        while True:
            metrics = self.fetch_and_parse_metrics()
            candidates = self.compute_prune_candidates(metrics)
            self.apply_pruning(candidates)
            time.sleep(interval_sec)


if __name__ == "__main__":
    RegexEWMAPruner().run()
