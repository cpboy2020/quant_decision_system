#!/usr/bin/env bash
set -euo pipefail

# ================= 配置参数 =================
KEY_TYPE="${KEY_TYPE:-ed25519}"  # ed25519 (推荐) 或 rsa -b 4096
KEY_PREFIX="${KEY_PREFIX:-quant}"
KEY_EXPIRY_DAYS="${KEY_EXPIRY_DAYS:-90}"  # 密钥有效期
BACKUP_DIR="${BACKUP_DIR:-~/.ssh/rotated_keys}"
GITHUB_API_TOKEN="${GITHUB_API_TOKEN:-}"  # 可选：自动吊销 GitHub 密钥

# ================= 工具函数 =================
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { log "❌ $*"; exit 1; }

# ================= 主逻辑 =================
rotate_key() {
  local key_name="$1"
  local key_path="$HOME/.ssh/${KEY_PREFIX}_${key_name}"
  local pub_path="${key_path}.pub"
  local backup_path="$BACKUP_DIR/${KEY_PREFIX}_${key_name}_$(date +%Y%m%d_%H%M%S)"
  
  log "🔄 开始轮换密钥: $key_name"
  
  # 1. 备份旧密钥（防误删）
  mkdir -p "$BACKUP_DIR"
  if [ -f "$key_path" ]; then
    log "📦 备份旧密钥: $key_path → $backup_path"
    cp -p "$key_path" "$pub_path" "$backup_path" 2>/dev/null || true
    chmod 600 "$backup_path" 2>/dev/null || true
  fi
  
  # 2. 生成新密钥
  log "🔑 生成新 $KEY_TYPE 密钥: $key_path"
  ssh-keygen -t "$KEY_TYPE" -C "${KEY_PREFIX}_${key_name}@$(hostname)-$(date +%s)" \
    -f "$key_path" -N "" -q
  
  # 3. 设置权限
  chmod 600 "$key_path"
  chmod 644 "$pub_path"
  
  # 4. 输出公钥（供用户添加至服务端）
  echo ""
  log "✅ 新密钥已生成:"
  echo "   🔹 私钥: $key_path (权限: 600)"
  echo "   🔹 公钥: $pub_path"
  echo ""
  echo "📤 请将以下公钥添加至目标服务:"
  echo "   ┌─────────────────────────────────"
  cat "$pub_path"
  echo "   └─────────────────────────────────"
  echo ""
  
  # 5. 自动添加至 GitHub（如有 Token）
  if [ -n "$GITHUB_API_TOKEN" ] && [[ "$key_name" == *"github"* ]]; then
    log "🤖 尝试自动添加至 GitHub..."
    TITLE="${KEY_PREFIX}_${key_name}_$(date +%Y%m%d)"
    KEY_CONTENT=$(cat "$pub_path")
    
    curl -s -X POST https://api.github.com/user/keys \
      -H "Authorization: token $GITHUB_API_TOKEN" \
      -H "Accept: application/vnd.github.v3+json" \
      -d "{\"title\":\"$TITLE\",\"key\":\"$KEY_CONTENT\"}" \
      | jq -r '.html_url // empty' 2>/dev/null && \
      log "✅ 公钥已添加至 GitHub" || \
      log "⚠️  GitHub 添加失败，请手动操作"
  fi
  
  # 6. 更新 SSH config（如存在）
  local ssh_config="$HOME/.ssh/config"
  if [ -f "$ssh_config" ] && grep -q "Host.*$key_name" "$ssh_config"; then
    log "🔧 更新 SSH config 中的密钥路径..."
    sed -i.bak "s|IdentityFile.*${KEY_PREFIX}_${key_name}|IdentityFile $key_path|g" "$ssh_config"
    rm -f "${ssh_config}.bak"
  fi
  
  # 7. 记录轮换日志
  echo "$(date -Iseconds) ROTATED $key_name $key_path" >> "${BACKUP_DIR}/rotation.log"
  
  log "🎉 密钥轮换完成: $key_name"
}

# 吊销旧密钥（可选，需服务端支持）
revoke_old_keys() {
  local key_name="$1"
  local max_age_days="${2:-$KEY_EXPIRY_DAYS}"
  
  log "🗑️  检查并吊销过期密钥: $key_name (阈值: $max_age_days 天)"
  
  # 查找备份目录中超过阈值的密钥
  find "$BACKUP_DIR" -name "${KEY_PREFIX}_${key_name}_*" -type f -mtime "+$max_age_days" | while read -r old_key; do
    log "⚠️  发现过期密钥: $old_key"
    
    # 提取公钥指纹（用于服务端吊销）
    if [ -f "${old_key}.pub" ]; then
      FINGERPRINT=$(ssh-keygen -lf "${old_key}.pub" | awk '{print $2}')
      log "🔍 公钥指纹: $FINGERPRINT"
      
      # GitHub API 吊销（示例）
      if [ -n "$GITHUB_API_TOKEN" ]; then
        KEY_ID=$(curl -s -H "Authorization: token $GITHUB_API_TOKEN" \
          https://api.github.com/user/keys | \
          jq -r ".[] | select(.fingerprint == \"$FINGERPRINT\") | .id" 2>/dev/null)
        
        if [ -n "$KEY_ID" ] && [ "$KEY_ID" != "null" ]; then
          log "🗑️  吊销 GitHub 密钥 ID: $KEY_ID"
          curl -s -X DELETE "https://api.github.com/user/keys/$KEY_ID" \
            -H "Authorization: token $GITHUB_API_TOKEN" && \
            log "✅ 吊销成功" || log "⚠️  吊销失败"
        fi
      fi
    fi
    
    # 安全删除本地旧密钥（3 次覆盖）
    log "🔒 安全删除本地旧密钥: $old_key"
    shred -u -n 3 "$old_key" "${old_key}.pub" 2>/dev/null || rm -f "$old_key" "${old_key}.pub"
  done
}

# ================= 主入口 =================
main() {
  case "${1:-help}" in
    rotate)
      [ -z "${2:-}" ] && die "用法: $0 rotate <key_name>"
      rotate_key "$2"
      ;;
    revoke)
      [ -z "${2:-}" ] && die "用法: $0 revoke <key_name> [max_age_days]"
      revoke_old_keys "$2" "${3:-}"
      ;;
    list)
      log "📋 当前密钥列表:"
      ls -la ~/.ssh/${KEY_PREFIX}_* 2>/dev/null || echo "   (无量化系统密钥)"
      ;;
    help|*)
      echo "🔐 SSH 密钥轮换工具"
      echo ""
      echo "用法: $0 <command> [args]"
      echo ""
      echo "命令:"
      echo "   rotate <key_name>              生成新密钥并备份旧密钥"
      echo "   revoke <key_name> [days]       吊销并安全删除过期密钥"
      echo "   list                           列出当前所有量化系统密钥"
      echo ""
      echo "环境变量:"
      echo "   KEY_TYPE: 密钥类型 (ed25519|rsa) [默认: ed25519]"
      echo "   KEY_EXPIRY_DAYS: 密钥有效期 (天) [默认: 90]"
      echo "   GITHUB_API_TOKEN: GitHub API Token (可选，用于自动管理)"
      echo ""
      echo "示例:"
      echo "   $0 rotate github-company       # 轮换公司 GitHub 密钥"
      echo "   $0 revoke github-company 180   # 吊销 180 天前的旧密钥"
      ;;
  esac
}

main "$@"
