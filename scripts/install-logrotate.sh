#!/usr/bin/env bash
# ============================================================
# install-logrotate.sh - 安装 yk-script logrotate 配置
# ============================================================
# 动作:
#   1. 复制 logrotate-yk-script → /etc/logrotate.d/yk-script
#   2. logrotate -d 验证配置语法
#
# 用法:
#   sudo bash scripts/install-logrotate.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOGROTATE_SRC="${PROJECT_DIR}/scripts/logrotate-yk-script"
LOGROTATE_DST="/etc/logrotate.d/yk-script"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err() { echo -e "${RED}[ERR]${NC} $*" >&2; }

# ============ 前置检查 ============
if [[ $EUID -ne 0 ]]; then
  err "必须 sudo 运行: sudo bash $0"
  exit 1
fi

if [[ ! -f "${LOGROTATE_SRC}" ]]; then
  err "logrotate 配置缺失: ${LOGROTATE_SRC}"
  exit 1
fi

# ============ 复制 ============
log "==== 复制 logrotate 配置 ===="
cp -v "${LOGROTATE_SRC}" "${LOGROTATE_DST}"
chmod 644 "${LOGROTATE_DST}"

# ============ 验证语法 ============
log "==== logrotate -d (debug 模式验证) ===="
if logrotate -d "${LOGROTATE_DST}" 2>&1 | tail -5; then
  log "✅ logrotate 配置 OK"
else
  err "logrotate 配置有语法错 (见上方)"
  exit 1
fi

log "✅ 安装完成! logrotate 每日自动跑 (cron.daily)"
log "   查状态: logrotate -d ${LOGROTATE_DST}"
log "   强制跑: sudo logrotate -f ${LOGROTATE_DST}"