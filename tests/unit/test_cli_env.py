"""
test_cli_env.py — daily.py cli() 环境加载行为验证

P11+P13 fix: 手动跑 `python3 -m src.daily` 时, cli() 第一行调 load_dotenv(),
             自动从 cwd 的 .env 文件注入 env. systemd 跑时 EnvironmentFile 已注入,
             override=False 不覆盖 (python-dotenv 默认行为).

测试覆盖:
- TestCliEnvLoading::test_cli_calls_load_dotenv         cli() 必调 load_dotenv()
- TestCliEnvLoading::test_cli_loads_dotenv_from_cwd     cwd 有 .env 时注入
- TestCliEnvLoading::test_cli_no_dotenv_no_crash        无 .env 时不报错
- TestCliEnvLoading::test_cli_does_not_override_existing_env  systemd env 优先级 > .env
"""

from __future__ import annotations

from unittest.mock import patch


class TestCliEnvLoading:
    """daily.cli() 自动加载 .env 的行为"""

    def test_cli_calls_load_dotenv(self, monkeypatch):
        """cli() 必须调 load_dotenv() (manual run 友好)"""
        # 拦截 main(), 避免跑真业务
        with patch("src.daily.main", return_value=0) as mock_main, \
             patch("src.daily.load_dotenv") as mock_load:
            from src.daily import cli
            # 用 sys.argv 喂参数, 避免 argparse 读真实 argv
            monkeypatch.setattr("sys.argv", ["yk-daily", "--dry-run"])
            cli()
            mock_load.assert_called_once()
            # 必须传 dotenv_path=".env" 避免 pytest 调试模式下 find_dotenv 错误
            assert mock_load.call_args.kwargs.get("dotenv_path") == ".env"
            assert mock_load.call_args.kwargs.get("override") is False
            mock_main.assert_called_once()

    def test_cli_loads_dotenv_from_cwd(self, tmp_path, monkeypatch):
        """cli() 从 cwd 读 .env (验证真实 .env 文件加载)"""
        # 在 tmp_path 写一个 .env
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_CLI_DOTENV_VAR=loaded-from-tmp\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("TEST_CLI_DOTENV_VAR", raising=False)
        import os

        with patch("src.daily.main", return_value=0):
            from src.daily import cli
            monkeypatch.setattr("sys.argv", ["yk-daily", "--dry-run"])
            cli()

        # cli() 后, TEST_CLI_DOTENV_VAR 应该是 "loaded-from-tmp"
        assert os.environ.get("TEST_CLI_DOTENV_VAR") == "loaded-from-tmp"

    def test_cli_no_dotenv_no_crash(self, tmp_path, monkeypatch):
        """cli() 在无 .env 时不报错 (测试场景 + 全新部署)"""
        # tmp_path 没有 .env
        monkeypatch.chdir(tmp_path)

        with patch("src.daily.main", return_value=0):
            from src.daily import cli
            monkeypatch.setattr("sys.argv", ["yk-daily", "--dry-run"])
            # 不应该抛 FileNotFoundError 或类似
            result = cli()
            assert result == 0

    def test_cli_does_not_override_existing_env(self, tmp_path, monkeypatch):
        """systemd 注入的 env 优先级 > .env (override=False 默认值)"""
        env_file = tmp_path / ".env"
        # .env 里写 GITHUB_BACKUP_TOKEN=from-dotenv-file
        env_file.write_text(
            "GITHUB_BACKUP_TOKEN=from-dotenv-file\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        # 但 shell 已设 GITHUB_BACKUP_TOKEN=from-shell-env (模拟 systemd)
        monkeypatch.setenv("GITHUB_BACKUP_TOKEN", "from-shell-env")
        # 删 pytest 上下文里的 fake GITHUB_BACKUP_TOKEN 等无关变量
        monkeypatch.delenv("TEST_CLI_DOTENV_VAR", raising=False)

        with patch("src.daily.main", return_value=0):
            from src.daily import cli
            monkeypatch.setattr("sys.argv", ["yk-daily", "--dry-run"])
            cli()

        # systemd env 必须赢 — 不能被 .env 覆盖
        import os
        assert os.environ.get("GITHUB_BACKUP_TOKEN") == "from-shell-env"


# 防止 pytest skip import 报错
