#!/usr/bin/env bash
set -euo pipefail
echo "🔨 编译 FlatBuffers Schema -> Rust..."
flatc --rust -o src/generated ac_rules.fbs
echo "✅ 生成: src/generated/ac_rules_generated.rs"
