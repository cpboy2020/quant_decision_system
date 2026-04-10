#!/usr/bin/env bash
# 项目级 SSH 命令包装器：强制使用项目专属 SSH config
# 用法：git config core.sshCommand "$(pwd)/scripts/git-ssh.sh"

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CONFIG="$PROJECT_ROOT/configs/ssh/config"

if [ -f "$SSH_CONFIG" ]; then
  exec ssh -F "$SSH_CONFIG" "$@"
else
  exec ssh "$@"
fi
