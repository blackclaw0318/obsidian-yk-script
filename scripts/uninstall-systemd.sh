#!/usr/bin/env bash
# ============================================================
# uninstall-systemd.sh - 卸载 yk-daily systemd timer
# ============================================================
# 动作:
#   1. systemctl stop + disable yk-daily.timer
#   2. 删除 /etc/systemd/system/yk-daily.{service,timer}
#   3. systemctl daemon-reload
#   4. systemctl reset-failed (清残留失败标记)
#
# 幂等: 重复执行安全
# 必须 sudo (要写 /etc/systemd/system/)
#
# 用法:
#   sudo bash scripts/uninstall-systemd.sh
# ============================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err() { echo -e "${RED}[ERR]${NC} $*" >&2; }

# ============ 前置检查 ============
if [[ $EUID -ne 0 ]]; then
  err "必须 sudo 运行: sudo bash $0"
  exit 1
fi

# ============ 停 + 禁用 timer ============
log "==== 停 + 禁用 yk-daily.timer ===="
if systemctl is-active --quiet yk-daily.timer 2>/dev/null; then
  systemctl stop yk-daily.timer || true
fi
if systemctl is-enabled --quiet yk-daily.timer 2>/dev/null; then
  systemctl disable yk-daily.timer || true
fi

# ============ 删除 unit 文件 ============
log "==== 删除 systemd unit 文件 ===="
for f in /etc/systemd/system/yk-daily.service /etc/systemd/system/yk-daily.timer; do
  if [[ -f "$f" ]]; then
    rm -v "$f"
  fi
done

# ============ daemon-reload + reset-failed ============
log "==== systemctl daemon-reload + reset-failed ===="
systemctl daemon-reload
systemctl reset-failed yk-daily.service 2>/dev/null || true

log "✅ 卸载完成!"
log "   状态: systemctl status yk-daily.timer (应该: Unit not found)"