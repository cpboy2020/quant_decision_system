#!/bin/sh
set -e
echo "🚀 InitContainer: 冷启动 AC 规则预载..."
if [ ! -f /wasm-cache/ac_snapshot_v1.json ]; then
  wget -q http://etcd-bridge:8080/latest-snapshot -O /wasm-cache/ac_snapshot_v1.json
  echo "✅ 规则快照已写入 /wasm-cache/"
else
  echo "🔒 快照已存在，跳过下载"
fi
exec cat /wasm-cache/ac_snapshot_v1.json | sha256sum
