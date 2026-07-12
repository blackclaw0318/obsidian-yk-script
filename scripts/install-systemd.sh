#!/usr/bin/env bash
# ============================================================
# install-systemd.sh - 安装 yk-daily systemd timer
# ============================================================
# 动作:
#   1. 复制 yk-daily.{service,timer} → /etc/systemd/system/
#   2. systemd daemon-reload
#   3. enable + start timer (开机自启 + 立即开始按时间表)
#   4. 验证: systemctl status + list-timers
#
# 幂等: 重复执行安全 (先 stop + disable 再覆盖 install)
# 必须 sudo (要写 /etc/systemd/system/)
#
# 用法:
#   sudo bash scripts/install-systemd.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SYSTEMD_SRC="${PROJECT_DIR}/systemd"
SYSTEMD_DST="/etc/systemd/system"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err() { echo -e "${RED}[ERR]${NC} $*" >&2; }

# ============ 前置检查 ============
log "==== 前置检查 ===="
if [[ $EUID -ne 0 ]]; then
  err "必须 sudo 运行: sudo bash $0"
  exit 1
fi

if [[ ! -f "${SYSTEMD_SRC}/yk-daily.service" ]] || [[ ! -f "${SYSTEMD_SRC}/yk-daily.timer" ]]; then
  err "systemd unit 文件缺失: ${SYSTEMD_SRC}/yk-daily.{service,timer}"
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
  warn ".env 不存在: ${PROJECT_DIR}/.env (从 .env.example 复制并填值)"
  warn "  → 主流程会失败 (LLM 401), 但 systemd timer 安装本身不受影响"
fi

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
  warn "venv python 缺失: ${PROJECT_DIR}/.venv/bin/python"
  warn "  → 跑 uv sync 或 python -m venv .venv && pip install -e '.[dev]'"
fi

if [[ ! -d "${PROJECT_DIR}/logs" ]]; then
  log "创建 logs 目录: ${PROJECT_DIR}/logs"
  mkdir -p "${PROJECT_DIR}/logs"
fi

log "✅ 前置检查通过"

# ============ systemd-analyze verify ============
log "==== systemd-analyze verify (语法) ===="
if systemd-analyze verify "${SYSTEMD_SRC}/yk-daily.service" 2>&1 | tee /tmp/verify-yk-service.log; then
  : # verify 成功时无输出, 失败才有
fi
if grep -q "Failed\|bad unit" /tmp/verify-yk-service.log; then
  err "service 文件语法错 (见上方)"
  exit 1
fi

if systemd-analyze verify "${SYSTEMD_SRC}/yk-daily.timer" 2>&1 | tee /tmp/verify-yk-timer.log; then
  :
fi
if grep -q "Failed\|bad unit" /tmp/verify-yk-timer.log; then
  err "timer 文件语法错 (见上方)"
  exit 1
fi
log "✅ systemd unit 语法 OK"

# ============ 复制 unit 文件 ============
log "==== 复制 systemd unit 文件 ===="
cp -v "${SYSTEMD_SRC}/yk-daily.service" "${SYSTEMD_DST}/"
cp -v "${SYSTEMD_SRC}/yk-daily.timer" "${SYSTEMD_DST}/"

# ============ daemon-reload ============
log "==== systemctl daemon-reload ===="
systemctl daemon-reload

# ============ 幂等: 先 stop + disable (重装场景) ============
if systemctl is-enabled --quiet yk-daily.timer 2>/dev/null; then
  log "==== 停旧 timer (重装幂等) ===="
  systemctl stop yk-daily.timer || true
  systemctl disable yk-daily.timer || true
fi

# ============ enable + start timer ============
log "==== systemctl enable --now yk-daily.timer ===="
systemctl enable --now yk-daily.timer

# ============ 验证 ============
log "==== 验证 ===="
echo ""
echo "----- systemctl status yk-daily.timer -----"
systemctl status yk-daily.timer --no-pager || true

echo ""
echo "----- systemctl list-timers yk-daily.timer -----"
systemctl list-timers yk-daily.timer --no-pager || true

echo ""
log "✅ 安装完成! 老板可查 'systemctl list-timers yk-daily.timer' 看下次触发时间"
log "   手动跑一次: sudo systemctl start yk-daily.service"
log "   查日志:     tail -f ${PROJECT_DIR}/logs/yk-daily.log"
log "   停:         sudo systemctl stop yk-daily.timer"