#!/usr/bin/env bash
set -euo pipefail
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/envoy_audit_wasm.wasm .
echo "✅ WASM 模块已编译: envoy_audit_wasm.wasm ($(ls -lh envoy_audit_wasm.wasm | awk '{print $5}'))"
