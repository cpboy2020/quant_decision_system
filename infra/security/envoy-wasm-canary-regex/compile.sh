#!/usr/bin/env bash
set -euo pipefail
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/envoy_wasm_canary_regex.wasm .
echo "✅ WASM 灰度裁剪模块编译完成: $(ls -lh envoy_wasm_canary_regex.wasm | awk '{print $5}')"
