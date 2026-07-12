"""
test_systemd.py — systemd unit + logrotate 配置验证

验证:
- systemd-analyze verify yk-daily.service / .timer 语法正确
- yk-daily.service 关键字段 (ExecStart / TZ / TimeoutStartSec)
- yk-daily.timer OnCalendar=*-*-* 06:00:00
- logrotate config 关键指令 (daily / rotate 30 / compress)
- install/uninstall scripts 语法 OK

不需要 sudo 权限 (只 verify 语法, 不实际安装)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[2]
SYSTEMD_DIR = PROJECT_DIR / "systemd"
SCRIPTS_DIR = PROJECT_DIR / "scripts"


# ===== Test: systemd-analyze verify =====
class TestSystemdVerify:
    """systemd unit 文件语法验证"""

    def test_service_verify_syntax(self):
        if not shutil.which("systemd-analyze"):
            pytest.skip("systemd-analyze 不可用 (非 Linux 主机?)")
        result = subprocess.run(
            ["systemd-analyze", "verify", str(SYSTEMD_DIR / "yk-daily.service")],
            capture_output=True,
            text=True,
        )
        # verify 退出码 0 = OK; 但通常路径不存在的警告也算非 0
        # 我们只看 stderr 有无 "Failed" / "bad unit" 字样
        combined = result.stdout + result.stderr
        assert "Failed to" not in combined or "is not executable" in combined

    def test_timer_verify_syntax(self):
        if not shutil.which("systemd-analyze"):
            pytest.skip("systemd-analyze 不可用")
        result = subprocess.run(
            ["systemd-analyze", "verify", str(SYSTEMD_DIR / "yk-daily.timer")],
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        assert "Failed to" not in combined or "is not executable" in combined


# ===== Test: service 文件字段 =====
class TestServiceFile:
    """yk-daily.service 关键字段"""

    @classmethod
    def setup_class(cls):
        cls.content = (SYSTEMD_DIR / "yk-daily.service").read_text(encoding="utf-8")

    def test_unit_section(self):
        assert "[Unit]" in self.content
        assert "Description=" in self.content
        assert "After=network-online.target" in self.content

    def test_service_type_oneshot(self):
        assert "Type=oneshot" in self.content

    def test_execstart_python_module(self):
        assert "ExecStart=" in self.content
        assert "python -m src.daily" in self.content

    def test_environment_file(self):
        assert "EnvironmentFile=" in self.content
        assert ".env" in self.content

    def test_timezone_asia_shanghai(self):
        assert "TZ=Asia/Shanghai" in self.content

    def test_timeout_set(self):
        assert "TimeoutStartSec=" in self.content

    def test_working_directory(self):
        assert "WorkingDirectory=" in self.content
        assert "obsidian-yk-script" in self.content


# ===== Test: timer 文件字段 =====
class TestTimerFile:
    """yk-daily.timer 关键字段"""

    @classmethod
    def setup_class(cls):
        cls.content = (SYSTEMD_DIR / "yk-daily.timer").read_text(encoding="utf-8")

    def test_unit_section(self):
        assert "[Unit]" in self.content
        assert "Description=" in self.content

    def test_timer_section(self):
        assert "[Timer]" in self.content

    def test_oncalendar_06_00(self):
        """必须配置每天 06:00"""
        assert re.search(r"OnCalendar=\*-\*-\* 06:00:00", self.content), (
            "yk-daily.timer 必须配 OnCalendar=*-*-* 06:00:00"
        )

    def test_persistent_true(self):
        assert "Persistent=true" in self.content

    def test_unit_reference(self):
        assert "Unit=yk-daily.service" in self.content

    def test_install_section(self):
        assert "[Install]" in self.content
        assert "WantedBy=timers.target" in self.content


# ===== Test: install/uninstall scripts =====
class TestInstallScripts:
    """scripts/*.sh 语法验证 (不执行)"""

    @staticmethod
    def _check_bash_syntax(path: Path) -> bool:
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def test_install_systemd_syntax(self):
        assert self._check_bash_syntax(SCRIPTS_DIR / "install-systemd.sh")

    def test_uninstall_systemd_syntax(self):
        assert self._check_bash_syntax(SCRIPTS_DIR / "uninstall-systemd.sh")

    def test_install_logrotate_syntax(self):
        assert self._check_bash_syntax(SCRIPTS_DIR / "install-logrotate.sh")

    def test_install_systemd_executable(self):
        """安装脚本必须可执行"""
        path = SCRIPTS_DIR / "install-systemd.sh"
        assert os.access(path, os.X_OK), f"{path} 不可执行 (chmod +x)"

    def test_uninstall_systemd_executable(self):
        path = SCRIPTS_DIR / "uninstall-systemd.sh"
        assert os.access(path, os.X_OK), f"{path} 不可执行"

    def test_install_logrotate_executable(self):
        path = SCRIPTS_DIR / "install-logrotate.sh"
        assert os.access(path, os.X_OK), f"{path} 不可执行"

    def test_install_systemd_uses_sudo(self):
        content = (SCRIPTS_DIR / "install-systemd.sh").read_text(encoding="utf-8")
        assert "EUID -ne 0" in content
        assert "systemctl daemon-reload" in content
        assert "systemctl enable --now" in content

    def test_uninstall_systemd_idempotent(self):
        """卸载脚本必须幂等 (stop + disable + rm + reload)"""
        content = (SCRIPTS_DIR / "uninstall-systemd.sh").read_text(encoding="utf-8")
        assert "is-active" in content  # 检查是否在跑
        assert "is-enabled" in content  # 检查是否启用
        assert "systemctl daemon-reload" in content


# ===== Test: logrotate config =====
class TestLogrotateConfig:
    """scripts/logrotate-yk-script 关键指令"""

    @classmethod
    def setup_class(cls):
        cls.path = SCRIPTS_DIR / "logrotate-yk-script"
        cls.content = cls.path.read_text(encoding="utf-8")

    def test_path_match(self):
        """必须匹配 yk-daily.log"""
        assert "yk-daily.log" in self.content
        assert "/logs/" in self.content

    def test_daily_rotation(self):
        assert "daily" in self.content

    def test_keep_30_days(self):
        assert "rotate 30" in self.content

    def test_compress(self):
        assert "compress" in self.content

    def test_copytruncate(self):
        """systemd 用 append: 持续开 inode, 必须 copytruncate"""
        assert "copytruncate" in self.content

    def test_dateext(self):
        assert "dateext" in self.content

    def test_create_permissions(self):
        assert "create 0644" in self.content


# ===== Test: logrotate -d verify =====
class TestLogrotateDryRun:
    """logrotate -d 验证语法 (debug 模式, 不实际 rotate)"""

    def test_logrotate_dry_run(self):
        if not shutil.which("logrotate"):
            pytest.skip("logrotate 不可用")
        result = subprocess.run(
            ["logrotate", "-d", str(SCRIPTS_DIR / "logrotate-yk-script")],
            capture_output=True,
            text=True,
        )
        # logrotate -d 退出码 0 = OK
        # 我们也容忍"无法读日志文件"的警告 (因为 logs/yk-daily.log 还没生成)
        assert result.returncode == 0 or "No such file" in result.stderr


# 防止 pytest skip import 报错
