#!/usr/bin/env bash
set -euo pipefail
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/envoy_ac_diff_filter.wasm .
echo "✅ WASM AC 差分引擎编译完成: $(ls -lh envoy_ac_diff_filter.wasm | awk '{print $5}')"
