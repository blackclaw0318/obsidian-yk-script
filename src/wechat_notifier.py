"""
wechat_notifier.py — yk-script 推送结果 → 老板微信审查
====================================================

设计 (v0.3 §3.9 增项 P14, 复刻 obsidian-novel-publisher pattern):
  - 极简: 4 行 ≤40 字/行, 老板一眼能审
  - 隔离: try/except 全包, 微信推送失败不影响 publisher 主流程
  - 幂等: 写 pending.txt + openclaw cron run + 等 agent 读
  - 可关: WEIXIN_NOTIFY_ENABLED=false 完全跳过

推送路径:
  daily.py -> wechat-pending.txt -> openclaw cron run <jobId>
    -> OpenClaw gateway -> isolated agentTurn -> announce delivery fallback
    -> openclaw-weixin plugin -> 老板微信 (私聊)

依赖:
  - openclaw CLI
  - cron job `notify-yk-script-wechat` (老板需手动注册, 见 ops)
  - 微信 plugin openclaw-weixin 已 login + running

.env 配置:
  WEIXIN_NOTIFY_ENABLED      true/false (默认 true)
  YK_WEIXIN_CRON_JOB_ID      OpenClaw cron job id (老板注册时拿)
  YK_WEIXIN_PENDING_FILE     pending.txt 路径 (默认 logs/wechat-pending.txt)
  WEIXIN_CRON_RUN_TIMEOUT_S  CLI 超时秒数 (默认 15)

老板体验 (消息示例):
  ✅ 推送成功 · yk-script 第1集
  📦 搬家日 (S01-EP01)
  字数 1800 · 62s
  https://www.shangkun.uk/posts/yk-s01-ep01

  ❌ 推送失败 · yk-script 第1集
  📦 搬家日 (S01-EP01)
  原因: LLM 调用失败
  查看: tail logs/yk-daily.log

复用自 obsidian-novel-publisher/src/wechat_notifier.py (整建制搬迁, 适配 yk-script 文案)。
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WechatNotifierConfig:
    """微信通知配置 (从 .env 读)"""

    enabled: bool
    cron_job_id: str  # OpenClaw cron job id (yk-script 的通知 job)
    pending_file: Path
    cron_run_timeout_s: float
    sleep_after_enqueue_s: float = 20.0  # 等 agent 处理时间

    @classmethod
    def from_env(cls) -> WechatNotifierConfig:
        return cls(
            enabled=os.environ.get("WEIXIN_NOTIFY_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            cron_job_id=os.environ.get("YK_WEIXIN_CRON_JOB_ID", ""),
            pending_file=Path(
                os.environ.get(
                    "YK_WEIXIN_PENDING_FILE",
                    str(Path(__file__).parent.parent / "logs" / "wechat-pending.txt"),
                )
            ),
            cron_run_timeout_s=float(os.environ.get("WEIXIN_CRON_RUN_TIMEOUT_S", "15")),
        )


# --------------------------------------------------------------------------
# 消息构造
# --------------------------------------------------------------------------


def _format_success(
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    word_count: int,
    duration_s: int,
    post_url: str,
) -> str:
    """成功消息: 4 行"""
    line1 = f"✅ 推送成功 · yk-script S{season_id:02d}-EP{episode_idx:02d}"
    line2 = title if title else "(无标题)"
    line3 = f"字数 {word_count} · {duration_s}s"
    line4 = post_url if post_url else "(无 URL)"
    return "\n".join([line1, line2, line3, line4])


def _format_failure(
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    error_short: str,
) -> str:
    line1 = f"❌ 推送失败 · yk-script S{season_id:02d}-EP{episode_idx:02d}"
    line2 = title if title else "(无标题)"
    line3 = f"原因: {error_short}"
    line4 = "查看: tail logs/yk-daily.log"
    return "\n".join([line1, line2, line3, line4])


def _format_backup_warning(
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    backup_error: str,
) -> str:
    """备份失败告警: ⚠️ (推送成功 + 备份失败)"""
    line1 = f"⚠️ 推送成功但备份失败 · yk-script S{season_id:02d}-EP{episode_idx:02d}"
    line2 = title if title else "(无标题)"
    line3 = f"博客已发布 (公开), 备份未同步 (GitHub 备份失败)"
    line4 = f"原因: {backup_error}"
    return "\n".join([line1, line2, line3, line4])


# --------------------------------------------------------------------------
# 推送主函数
# --------------------------------------------------------------------------


def notify_success(
    cfg: WechatNotifierConfig,
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    word_count: int,
    duration_s: int,
    post_url: str,
) -> bool:
    """推送成功 → 微信审查消息 (永不抛)"""
    if not cfg.enabled:
        logger.debug("[notify] WEIXIN_NOTIFY_ENABLED=false, 跳过")
        return False
    if not cfg.cron_job_id:
        logger.warning("[notify] YK_WEIXIN_CRON_JOB_ID 未设置, 跳过微信推送")
        return False

    msg = _format_success(
        season_id=season_id,
        episode_idx=episode_idx,
        title=title,
        word_count=word_count,
        duration_s=duration_s,
        post_url=post_url,
    )
    return _send(cfg, msg)


def notify_failure(
    cfg: WechatNotifierConfig,
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    error_short: str,
) -> bool:
    """失败告警 → 微信"""
    if not cfg.enabled:
        return False
    if not cfg.cron_job_id:
        return False

    msg = _format_failure(
        season_id=season_id,
        episode_idx=episode_idx,
        title=title,
        error_short=error_short,
    )
    return _send(cfg, msg)


def notify_backup_warning(
    cfg: WechatNotifierConfig,
    *,
    season_id: int,
    episode_idx: int,
    title: str,
    backup_error: str,
) -> bool:
    """备份失败但推送成功 → 微信告警"""
    if not cfg.enabled or not cfg.cron_job_id:
        return False

    msg = _format_backup_warning(
        season_id=season_id,
        episode_idx=episode_idx,
        title=title,
        backup_error=backup_error,
    )
    return _send(cfg, msg)


def _send(cfg: WechatNotifierConfig, msg: str) -> bool:
    """实际推送: 写文件 + cron run + 等 + 删文件"""
    try:
        # 1. 写 pending.txt
        cfg.pending_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.pending_file.write_text(msg, encoding="utf-8")
        logger.info("[notify] pending.txt 已写: %s", cfg.pending_file)

        # 2. 强制触发 cron job (enqueue, 不等完成)
        try:
            result = subprocess.run(
                ["openclaw", "cron", "run", cfg.cron_job_id],
                capture_output=True,
                text=True,
                timeout=cfg.cron_run_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[notify] cron run CLI 超时 (%.1fs)", cfg.cron_run_timeout_s)
        else:
            if result.returncode != 0:
                logger.warning(
                    "[notify] cron run rc=%d stderr=%s",
                    result.returncode,
                    (result.stderr or "")[:200],
                )
            else:
                logger.info("[notify] cron run enqueue 成功: job=%s", cfg.cron_job_id)

        # 3. sleep 等 agent 处理
        time.sleep(cfg.sleep_after_enqueue_s)

        # 4. 删文件 (避免 schedule 兜底重复推送)
        try:
            cfg.pending_file.unlink(missing_ok=True)
        except Exception as e:  # pragma: no cover
            logger.warning("[notify] 删 pending.txt 失败 (无害): %s", e)

        return True

    except Exception as e:
        logger.warning("[notify] 推送失败 (无害): %s: %s", type(e).__name__, e)
        return False
