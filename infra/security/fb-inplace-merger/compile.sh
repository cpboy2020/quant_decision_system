#!/usr/bin/env bash
set -euo pipefail
flatc --rust -o src/generated ac_delta_merger.fbs 2>/dev/null || echo "ℹ️ 跳过 FB 编译 (需 flatc 工具链)"
cargo build --target wasm32-wasip1 --release
echo "✅ WASM FB 增量合并模块编译完成"
