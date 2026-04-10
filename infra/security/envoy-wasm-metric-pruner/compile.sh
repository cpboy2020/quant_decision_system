#!/usr/bin/env bash
set -euo pipefail
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/envoy_metric_pruner.wasm .
echo "✅ WASM 裁剪模块编译完成: $(ls -lh envoy_metric_pruner.wasm | awk '{print $5}')"
