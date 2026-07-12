"""
test_outline_fetcher.py — OutlineFetcher 单元测试

覆盖:
- 构造校验 (空 token / 坏 repo)
- fetch_season: GitHub 200 + cache + local 三级 fallback
- 5xx 重试耗尽
- 4xx 直接抛错
- 404 文件不存在
- fetch_season_if_changed: sha 不变返回 None
- sha 变更触发新拉
- 本地缓存读写 + 原子写
- 工厂函数 (make_default_fetcher / fetch_season_with_fallback)
- 网络异常 (connect error)
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.outline_fetcher import (
    CACHE_ROOT,
    OutlineFetcher,
    OutlineFetcherError,
    OutlineSource,
    fetch_season_with_fallback,
    make_default_fetcher,
)

REPO = "blackclaw0318/obsidian-yk-script"
TOKEN = "ghp_" + "a" * 36
SEASON = 1
SAMPLE = {
    "season_id": 1,
    "episodes": [
        {"ep": 1, "title": "搬家日", "shots": 5, "duration_s": 62},
        {"ep": 2, "title": "首次洗澡", "shots": 4, "duration_s": 50},
    ],
    "stage_distribution": {"0-3s": "悬念钩", "3-15s": "建立"},
}

ENCODED = base64.b64encode(json.dumps(SAMPLE).encode("utf-8")).decode("ascii")


# ============================================================
# 构造 / 配置
# ============================================================

class TestConstruction:
    def test_basic_ok(self):
        f = OutlineFetcher(token=TOKEN, repo=REPO)
        assert f.owner == "blackclaw0318"
        assert f.name == "obsidian-yk-script"
        assert f.branch == "main"

    def test_repo_format_bad(self):
        with pytest.raises(ValueError, match="repo 必须是"):
            OutlineFetcher(token=TOKEN, repo="no-slash")

    def test_token_empty(self):
        with pytest.raises(ValueError, match="token 不能为空"):
            OutlineFetcher(token="", repo=REPO)

    def test_token_whitespace_only(self):
        with pytest.raises(ValueError, match="token 不能为空"):
            OutlineFetcher(token="   ", repo=REPO)

    def test_cache_dir_created(self, tmp_path: Path):
        cache = tmp_path / "sub" / "deep"
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=cache)
        assert cache.exists()


# ============================================================
# _headers / _url
# ============================================================

class TestInternals:
    def test_headers_contain_bearer(self):
        f = OutlineFetcher(token=TOKEN, repo=REPO)
        headers = f._headers()
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert "X-GitHub-Api-Version" in headers
        assert "User-Agent" in headers

    def test_url_builds_correctly(self):
        f = OutlineFetcher(token=TOKEN, repo=REPO)
        url = f._url("data/seasons/season-01.json")
        assert url == "https://api.github.com/repos/blackclaw0318/obsidian-yk-script/contents/data/seasons/season-01.json"


# ============================================================
# GitHub 拉取 (mock)
# ============================================================

def _github_ok(sha="abc1234567"):
    body = {
        "sha": sha,
        "encoding": "base64",
        "content": ENCODED,
        "name": f"season-{SEASON:02d}.json",
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _github_404():
    resp = MagicMock()
    resp.status_code = 404
    resp.text = "Not Found"
    return resp


def _github_500():
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal Server Error"
    return resp


def _github_401():
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Bad credentials"
    return resp


class TestFetchFromGitHub:
    def test_ok(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("sha1")) as m:
            data, sha = f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")
        assert sha == "sha1"
        assert data["season_id"] == 1
        assert len(data["episodes"]) == 2
        assert m.call_args[0][0].endswith(f"contents/data/seasons/season-{SEASON:02d}.json")

    def test_404_raises(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path, max_retries=1)
        with patch("src.outline_fetcher.requests.get", return_value=_github_404()):
            with pytest.raises(OutlineFetcherError, match="404"):
                f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")

    def test_401_raises_immediately(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path, max_retries=3)
        with patch("src.outline_fetcher.requests.get", return_value=_github_401()) as m:
            with pytest.raises(OutlineFetcherError, match="4xx"):
                f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")
        # 4xx 不应该重试
        assert m.call_count == 1

    def test_500_retries_then_raises(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path, max_retries=3)
        with patch("src.outline_fetcher.requests.get", return_value=_github_500()):
            with pytest.raises(OutlineFetcherError, match="重试 3 次耗尽"):
                f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")

    def test_500_retries_succeed(self, tmp_path: Path):
        """5xx 第一次失败,第二次 200"""
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path, max_retries=3)
        seq = [_github_500(), _github_ok("sha-retry")]
        with patch("src.outline_fetcher.requests.get", side_effect=seq):
            data, sha = f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")
        assert sha == "sha-retry"

    def test_network_exception_retries(self, tmp_path: Path):
        """requests.RequestException 应触发重试"""
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path, max_retries=2)
        seq = [requests.ConnectionError("boom"), _github_ok("sha-net")]
        with patch("src.outline_fetcher.requests.get", side_effect=seq):
            data, sha = f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")
        assert sha == "sha-net"

    def test_missing_sha(self, tmp_path: Path):
        body = {"encoding": "base64", "content": ENCODED}
        resp = MagicMock(status_code=200, json=MagicMock(return_value=body))
        resp.raise_for_status = MagicMock()
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=resp):
            with pytest.raises(OutlineFetcherError, match="缺 sha"):
                f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")

    def test_missing_base64_content(self, tmp_path: Path):
        body = {"sha": "abc", "encoding": "utf-8", "content": ENCODED}
        resp = MagicMock(status_code=200, json=MagicMock(return_value=body))
        resp.raise_for_status = MagicMock()
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=resp):
            with pytest.raises(OutlineFetcherError, match="缺 base64"):
                f._fetch_from_github(f"data/seasons/season-{SEASON:02d}.json")


# ============================================================
# fetch_season — 3 级 fallback
# ============================================================

class TestFetchSeasonFallback:
    def test_github_ok(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("sha-gh")):
            data, source = f.fetch_season(SEASON)
        assert source == OutlineSource.GITHUB
        assert data["season_id"] == 1

    def test_github_fail_falls_to_cache(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        # 先种 cache
        f._save_cache(SEASON, SAMPLE, "sha-cached")
        # github 全挂
        with patch("src.outline_fetcher.requests.get", return_value=_github_500()):
            data, source = f.fetch_season(SEASON)
        assert source == OutlineSource.CACHE
        assert data == SAMPLE

    def test_github_fail_cache_miss_falls_to_local(self, tmp_path: Path, monkeypatch, project_root_setup):
        # project_root_setup fixture 已 chdir 到临时目录(含 SAMPLE season-01.json)
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        # cache_dir 是 tmp_path, 没缓存
        with patch("src.outline_fetcher.requests.get", return_value=_github_500()):
            data, source = f.fetch_season(SEASON)
        assert source == OutlineSource.LOCAL
        assert data["season_id"] == 1

    def test_all_three_fail_raises(self, tmp_path: Path, monkeypatch):
        # 切到一个空 cwd (没 local season-01.json)
        empty = tmp_path
        monkeypatch.chdir(empty)
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_500()):
            with pytest.raises(OutlineFetcherError, match="3 级 fallback 全失败"):
                f.fetch_season(SEASON)


# ============================================================
# fetch_season_if_changed
# ============================================================

class TestFetchIfChanged:
    def test_sha_unchanged_returns_none(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._save_cache(SEASON, SAMPLE, "same-sha")
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("same-sha")):
            result = f.fetch_season_if_changed(SEASON)
        assert result is None

    def test_sha_changed_returns_data(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._save_cache(SEASON, SAMPLE, "old-sha")
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("new-sha")):
            result = f.fetch_season_if_changed(SEASON)
        assert result is not None
        data, source = result
        assert source == OutlineSource.GITHUB
        assert data["season_id"] == 1

    def test_no_cache_sha_changed(self, tmp_path: Path):
        """cache 没东西,github 有 → 直接返回"""
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("fresh-sha")):
            result = f.fetch_season_if_changed(SEASON)
        assert result is not None

    def test_github_error_returns_none(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_500()):
            result = f.fetch_season_if_changed(SEASON)
        assert result is None


# ============================================================
# 本地缓存
# ============================================================

class TestCacheIO:
    def test_save_load_roundtrip(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._save_cache(SEASON, SAMPLE, "roundtrip-sha")
        data, sha = f._load_cache(SEASON)
        assert data == SAMPLE
        assert sha == "roundtrip-sha"

    def test_load_no_cache(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        data, sha = f._load_cache(SEASON)
        assert data is None
        assert sha is None

    def test_load_corrupt_json(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._cache_json_path(SEASON).write_text("{bad json", encoding="utf-8")
        data, sha = f._load_cache(SEASON)
        assert data is None  # 不抛错, 走下一级

    def test_save_overwrites_old(self, tmp_path: Path):
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._save_cache(SEASON, SAMPLE, "v1")
        new = {"season_id": 1, "episodes": [], "updated": True}
        f._save_cache(SEASON, new, "v2")
        data, sha = f._load_cache(SEASON)
        assert sha == "v2"
        assert data["updated"] is True

    def test_save_atomic_no_leftover(self, tmp_path: Path):
        """原子写不应留下 .tmp"""
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        f._save_cache(SEASON, SAMPLE, "atomic-sha")
        leftovers = list(tmp_path.glob(".season-*.tmp"))
        assert leftovers == []


# ============================================================
# 工厂 + 便捷函数
# ============================================================

class TestFactory:
    def test_make_default_no_env(self, monkeypatch):
        monkeypatch.delenv("GITHUB_BACKUP_TOKEN", raising=False)
        with pytest.raises(OutlineFetcherError, match="GITHUB_BACKUP_TOKEN"):
            make_default_fetcher()

    def test_make_default_with_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_BACKUP_TOKEN", TOKEN)
        monkeypatch.setenv("GITHUB_OUTLINE_REPO", "owner/repo")
        f = make_default_fetcher()
        assert f.token == TOKEN
        assert f.owner == "owner"
        assert f.name == "repo"

    def test_fetch_season_with_fallback_no_token(self, monkeypatch, tmp_path: Path, project_root_setup):
        """无 token 直接走 local"""
        monkeypatch.delenv("GITHUB_BACKUP_TOKEN", raising=False)
        monkeypatch.chdir(project_root_setup)
        data, source = fetch_season_with_fallback(SEASON)
        assert source == OutlineSource.LOCAL

    def test_fetch_season_with_fallback_with_token_github_ok(self, monkeypatch, tmp_path: Path):
        """有 token + github 200 → source=github"""
        monkeypatch.setenv("GITHUB_BACKUP_TOKEN", TOKEN)
        f = OutlineFetcher(token=TOKEN, repo=REPO, cache_dir=tmp_path)
        with patch("src.outline_fetcher.requests.get", return_value=_github_ok("via-token")):
            data, source = fetch_season_with_fallback(SEASON)
        assert source == OutlineSource.GITHUB


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def project_root_setup(tmp_path: Path, monkeypatch) -> Path:
    """临时创一个项目根, 含 data/seasons/season-01.json"""
    seasons = tmp_path / "data" / "seasons"
    seasons.mkdir(parents=True)
    seasons.joinpath(f"season-{SEASON:02d}.json").write_text(
        json.dumps(SAMPLE, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path
