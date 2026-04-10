#!/usr/bin/env bash
set -euo pipefail
rustup target add wasm32-wasip1 2>/dev/null || true
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/wasm_gr_diff_compressor.wasm .
echo "✅ WASM GR/LZ4 压缩模块编译完成: $(ls -lh wasm_gr_diff_compressor.wasm | awk '{print $5}')"
