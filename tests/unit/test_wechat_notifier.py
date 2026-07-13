"""
test_wechat_notifier.py — 微信通知单元测试

覆盖:
- WechatNotifierConfig.from_env (默认 / override / 缺省)
- _format_success (4 行 简洁 格式)
- _format_failure (4 行)
- _format_backup_warning (4 行)
- notify_success / notify_failure / notify_backup_warning
  - WEIXIN_NOTIFY_ENABLED=false → 跳过
  - cron_job_id 空 → 跳过
  - 正常路径: 写文件 + run subprocess + sleep + unlink
  - 异常: subprocess 抛错 → 返回 False (永不抛)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.wechat_notifier import (
    WechatNotifierConfig,
    _format_backup_warning,
    _format_failure,
    _format_success,
    notify_backup_warning,
    notify_failure,
    notify_success,
)


@pytest.fixture
def cfg_with_job(tmp_path: Path) -> WechatNotifierConfig:
    return WechatNotifierConfig(
        enabled=True,
        cron_job_id="test-job-id-001",
        pending_file=tmp_path / "wechat-pending.txt",
        cron_run_timeout_s=2.0,
        sleep_after_enqueue_s=0.01,  # 加速测试
    )


@pytest.fixture
def cfg_disabled(tmp_path: Path) -> WechatNotifierConfig:
    return WechatNotifierConfig(
        enabled=False,
        cron_job_id="test-job-id-001",
        pending_file=tmp_path / "wechat-pending.txt",
        cron_run_timeout_s=2.0,
        sleep_after_enqueue_s=0.01,
    )


@pytest.fixture
def cfg_no_job(tmp_path: Path) -> WechatNotifierConfig:
    return WechatNotifierConfig(
        enabled=True,
        cron_job_id="",
        pending_file=tmp_path / "wechat-pending.txt",
        cron_run_timeout_s=2.0,
        sleep_after_enqueue_s=0.01,
    )


# ============================================================
# WechatNotifierConfig.from_env
# ============================================================

class TestConfig:
    def test_from_env_defaults(self, monkeypatch, tmp_path):
        monkeypatch.delenv("WEIXIN_NOTIFY_ENABLED", raising=False)
        monkeypatch.delenv("YK_WEIXIN_CRON_JOB_ID", raising=False)
        monkeypatch.setenv("YK_WEIXIN_PENDING_FILE", str(tmp_path / "p.txt"))
        cfg = WechatNotifierConfig.from_env()
        assert cfg.enabled is True
        assert cfg.cron_job_id == ""
        assert cfg.pending_file == tmp_path / "p.txt"

    def test_from_env_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WEIXIN_NOTIFY_ENABLED", "false")
        monkeypatch.setenv("YK_WEIXIN_PENDING_FILE", str(tmp_path / "p.txt"))
        cfg = WechatNotifierConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_custom_job_id(self, monkeypatch, tmp_path):
        monkeypatch.setenv("YK_WEIXIN_CRON_JOB_ID", "abc-123")
        monkeypatch.setenv("YK_WEIXIN_PENDING_FILE", str(tmp_path / "p.txt"))
        cfg = WechatNotifierConfig.from_env()
        assert cfg.cron_job_id == "abc-123"


# ============================================================
# _format_success / failure / backup_warning
# ============================================================

class TestFormatSuccess:
    def test_basic(self):
        s = _format_success(
            season_id=1, episode_idx=1, title="搬家日",
            word_count=1800, duration_s=62,
            post_url="https://shangkun.uk/posts/yk-s01-ep01",
        )
        assert "✅" in s
        assert "yk-script" in s
        assert "S01-EP01" in s
        assert "搬家日" in s
        assert "1800" in s
        assert "62s" in s
        assert "https://shangkun.uk" in s
        # 4 行
        assert s.count("\n") == 3

    def test_no_url(self):
        s = _format_success(
            season_id=1, episode_idx=1, title="t", word_count=100, duration_s=30, post_url="",
        )
        assert "无 URL" in s

    def test_season_2_episode_12(self):
        s = _format_success(
            season_id=2, episode_idx=12, title="t", word_count=100, duration_s=30, post_url="u",
        )
        assert "S02-EP12" in s


class TestFormatFailure:
    def test_basic(self):
        s = _format_failure(
            season_id=1, episode_idx=1, title="搬家日", error_short="LLM 调用失败",
        )
        assert "❌" in s
        assert "搬家日" in s
        assert "LLM" in s
        assert "tail logs" in s
        assert s.count("\n") == 3

    def test_empty_title(self):
        s = _format_failure(season_id=1, episode_idx=1, title="", error_short="x")
        assert "无标题" in s


class TestFormatBackupWarning:
    def test_basic(self):
        s = _format_backup_warning(
            season_id=1, episode_idx=1, title="搬家日",
            backup_error="GitHub PUT 5xx",
        )
        assert "⚠️" in s
        assert "推送成功" in s and "备份失败" in s
        assert "搬家日" in s
        assert "GitHub PUT" in s
        assert s.count("\n") == 3


# ============================================================
# notify_success / notify_failure / notify_backup_warning
# ============================================================

class TestNotifySuccess:
    def test_disabled_skips(self, cfg_disabled):
        result = notify_success(
            cfg_disabled,
            season_id=1, episode_idx=1, title="t", word_count=100, duration_s=30, post_url="u",
        )
        assert result is False
        # 没写文件
        assert not cfg_disabled.pending_file.exists()

    def test_no_job_id_skips(self, cfg_no_job):
        result = notify_success(
            cfg_no_job,
            season_id=1, episode_idx=1, title="t", word_count=100, duration_s=30, post_url="u",
        )
        assert result is False

    def test_full_flow_writes_then_runs_then_deletes(self, cfg_with_job):
        with patch("src.wechat_notifier.subprocess.run") as m_run:
            result = notify_success(
                cfg_with_job,
                season_id=1, episode_idx=1, title="搬家日",
                word_count=1800, duration_s=62, post_url="https://x/y",
            )
        assert result is True
        # 1. pending.txt 已写
        # 2. run 被调
        m_run.assert_called_once()
        # 3. 文件已删 (避免 schedule 重推)
        assert not cfg_with_job.pending_file.exists()

    def test_subprocess_failure_does_not_propagate(self, cfg_with_job):
        """subprocess.run 抛错 → 返回 False, 不抛"""
        with patch("src.wechat_notifier.subprocess.run", side_effect=Exception("boom")):
            result = notify_success(
                cfg_with_job,
                season_id=1, episode_idx=1, title="t", word_count=100, duration_s=30, post_url="u",
            )
        assert result is False

    def test_timeout_does_not_propagate(self, cfg_with_job):
        """timeout 乐观策略: CLI 超时不代表 enqueue 失败, 继续流程返回 True"""
        with patch("src.wechat_notifier.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = notify_success(
                cfg_with_job,
                season_id=1, episode_idx=1, title="t", word_count=100, duration_s=30, post_url="u",
            )
        # 乐观策略: 内层 TimeoutExpired 被 catch, 不影响后续 step
        assert result is True  # 流程完成, 不抛


class TestNotifyFailure:
    def test_disabled_skips(self, cfg_disabled):
        assert notify_failure(
            cfg_disabled, season_id=1, episode_idx=1, title="t", error_short="x"
        ) is False

    def test_full_flow(self, cfg_with_job):
        with patch("src.wechat_notifier.subprocess.run"):
            result = notify_failure(
                cfg_with_job, season_id=1, episode_idx=1, title="搬家日", error_short="LLM 失败"
            )
        assert result is True
        assert not cfg_with_job.pending_file.exists()


class TestNotifyBackupWarning:
    def test_disabled_skips(self, cfg_disabled):
        assert notify_backup_warning(
            cfg_disabled, season_id=1, episode_idx=1, title="t", backup_error="x"
        ) is False

    def test_full_flow(self, cfg_with_job):
        with patch("src.wechat_notifier.subprocess.run"):
            result = notify_backup_warning(
                cfg_with_job, season_id=1, episode_idx=1, title="搬家日", backup_error="5xx"
            )
        assert result is True
        assert not cfg_with_job.pending_file.exists()
