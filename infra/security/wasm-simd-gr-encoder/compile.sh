#!/usr/bin/env bash
set -euo pipefail
export RUSTFLAGS="-C target-cpu=mvp -C target-feature=+simd128"
rustup target add wasm32-wasip1 2>/dev/null || true
cargo build --target wasm32-wasip1 --release
cp target/wasm32-wasip1/release/gr_simd_encoder.wasm .
echo "✅ SIMD128 GR 编码器编译完成: $(ls -lh gr_simd_encoder.wasm | awk '{print $5}')"
