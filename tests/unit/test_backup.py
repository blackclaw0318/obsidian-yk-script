"""
test_backup.py — backup 单元测试

覆盖:
- Backup 构造 (token / repo)
- EpisodeMeta.now / model_dump_json
- _chapter_path / _meta_path / _index_path / _changelog_path
- _build_index (新条目 / 追加 / 幂等覆盖)
- _build_changelog (新增日期 / 同日追加)
- _commit_message (新文件 vs 覆盖)
- upload: 3 文件 PUT (mock), sha 检测, 5xx 重试, 4xx 不重试
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.backup import (
    Backup,
    BackupError,
    BackupResult,
    EpisodeMeta,
)

TOKEN = "a" * 40
REPO = "blackclaw0318/obsidian-novel-backups"


# ============================================================
# 构造
# ============================================================

class TestConstruction:
    def test_basic_ok(self):
        b = Backup(token=TOKEN)
        assert b.owner == "blackclaw0318"
        assert b.name == "obsidian-novel-backups"
        assert b.novel_id == "yk-script"

    def test_custom_novel_id(self):
        b = Backup(token=TOKEN, novel_id="custom-id")
        assert b.novel_id == "custom-id"

    def test_repo_format_bad(self):
        with pytest.raises(ValueError, match="repo 必须是"):
            Backup(token=TOKEN, repo="no-slash")

    def test_token_empty(self):
        with pytest.raises(ValueError, match="token 不能为空"):
            Backup(token="")


# ============================================================
# EpisodeMeta
# ============================================================

class TestEpisodeMeta:
    def test_now_minimal(self):
        m = EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=1800)
        assert m.title == "搬家日"
        assert m.word_count == 1800
        assert m.created_at  # auto filled

    def test_now_with_post_url(self):
        m = EpisodeMeta.now(
            season_id=1, episode_idx=1, title="t", word_count=100,
            post_url="https://shangkun.uk/x",
        )
        assert m.post_url == "https://shangkun.uk/x"

    def test_model_dump_json_serializable(self):
        m = EpisodeMeta.now(season_id=1, episode_idx=1, title="t", word_count=100)
        s = m.model_dump_json(indent=2)
        d = json.loads(s)
        assert d["title"] == "t"


# ============================================================
# 路径生成
# ============================================================

class TestPaths:
    def test_chapter_path(self):
        b = Backup(token=TOKEN)
        assert b._chapter_path(1, 1) == "yk-script/chapters/yk-s01-ep01.md"
        assert b._chapter_path(2, 12) == "yk-script/chapters/yk-s02-ep12.md"

    def test_meta_path(self):
        b = Backup(token=TOKEN)
        assert b._meta_path(1, 1) == "yk-script/meta/yk-s01-ep01.json"

    def test_index_path(self):
        b = Backup(token=TOKEN)
        assert b._index_path() == "yk-script/index.json"

    def test_changelog_path(self):
        b = Backup(token=TOKEN)
        assert b._changelog_path() == "yk-script/CHANGELOG.md"

    def test_custom_novel_id_paths(self):
        b = Backup(token=TOKEN, novel_id="other")
        assert b._chapter_path(1, 1) == "other/chapters/yk-s01-ep01.md"


# ============================================================
# _build_index
# ============================================================

class TestBuildIndex:
    def test_first_episode(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=1800, post_url="u")
        result = b._build_index(None, meta)
        assert result["novel_id"] == "yk-script"
        assert len(result["episodes"]) == 1
        assert result["episodes"][0]["episode_idx"] == 1

    def test_append_second_episode(self):
        b = Backup(token=TOKEN)
        existing = json.dumps({
            "novel_id": "yk-script",
            "episodes": [
                {"season_id": 1, "episode_idx": 1, "title": "t1", "word_count": 1800,
                 "created_at": "x", "post_url": "", "files": {}}
            ],
        })
        meta2 = EpisodeMeta.now(season_id=1, episode_idx=2, title="t2", word_count=2000)
        result = b._build_index(existing, meta2)
        assert len(result["episodes"]) == 2

    def test_idempotent_overwrite(self):
        b = Backup(token=TOKEN)
        existing = json.dumps({
            "novel_id": "yk-script",
            "episodes": [
                {"season_id": 1, "episode_idx": 1, "title": "OLD", "word_count": 1000,
                 "created_at": "x", "post_url": "", "files": {}}
            ],
        })
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="NEW", word_count=9999)
        result = b._build_index(existing, meta)
        # 1 episode, NEW 覆盖 OLD
        assert len(result["episodes"]) == 1
        assert result["episodes"][0]["title"] == "NEW"
        assert result["episodes"][0]["word_count"] == 9999

    def test_corrupt_existing(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="t", word_count=100)
        result = b._build_index("not json {", meta)
        # 不抛错, 重置为空
        assert len(result["episodes"]) == 1


# ============================================================
# _build_changelog
# ============================================================

class TestBuildChangelog:
    def test_first_entry(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=1800)
        result = b._build_changelog("# CHANGELOG\n\n", meta)
        assert "## 2026" in result
        assert "搬家日" in result

    def test_append_to_existing_day(self):
        b = Backup(token=TOKEN)
        existing = "# CHANGELOG\n\n## 2026-07-12\n\n### yk-s01-ep01 — 搬家日\n"
        meta = EpisodeMeta.now(season_id=1, episode_idx=2, title="首次洗澡", word_count=1500)
        result = b._build_changelog(existing, meta)
        # 还是 ## 2026-07-12 (创建日期自动 = now)
        # 1 章 + 新章
        assert "yk-s01-ep01" in result
        assert "yk-s01-ep02" in result


# ============================================================
# _commit_message
# ============================================================

class TestCommitMessage:
    def test_new_file(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=100)
        msg = b._commit_message("yk-script/chapters/yk-s01-ep01.md", meta, is_overwrite=False)
        assert "backup" in msg
        assert "yk-s01-ep01" in msg

    def test_overwrite_index(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="t", word_count=100)
        msg = b._commit_message("yk-script/index.json", meta, is_overwrite=True)
        assert "update index.json" in msg
        assert "yk-s01-ep01" in msg

    def test_overwrite_changelog(self):
        b = Backup(token=TOKEN)
        meta = EpisodeMeta.now(season_id=1, episode_idx=1, title="t", word_count=100)
        msg = b._commit_message("yk-script/CHANGELOG.md", meta, is_overwrite=True)
        assert "update CHANGELOG.md" in msg


# ============================================================
# upload() with mocked GitHub API
# ============================================================

def _put_201_resp(sha="abc1234567"):
    body = {"commit": {"sha": sha}, "content": {"sha": "blob-1"}}
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp


def _get_404_resp():
    resp = MagicMock()
    resp.status_code = 404
    return resp


def _make_backup(max_retries=2):
    return Backup(token=TOKEN, max_retries=max_retries)


def _make_meta():
    return EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=1800, post_url="u")


class TestUpload:
    def test_full_upload_creates_files(self):
        """upload() 推 2 文件 (chapter+meta) + index + changelog = 4 PUT"""
        b = _make_backup(max_retries=2)
        # GET existing (sha check) 返回 None (新文件) for all paths
        # GET index/changelog content 返回 None (不存在)
        # PUT 全 201
        with patch.object(b, "_get_existing_sha", return_value=None), \
             patch.object(b, "_get_existing_content", return_value=None), \
             patch("src.backup.requests.put", return_value=_put_201_resp("commit-sha-1")) as m:
            result = b.upload("# md", _make_meta())

        assert isinstance(result, BackupResult)
        assert result.commit_sha == "commit-sha-1"
        # 2 file PUT (chapter + meta) + index + changelog = 4
        assert m.call_count == 4
        # 从 URL 中提取 path
        paths_called = [
            call.args[0].split("/contents/", 1)[1] for call in m.call_args_list
        ]
        assert any("chapters" in p for p in paths_called)
        assert any("meta/" in p for p in paths_called)
        assert "yk-script/index.json" in paths_called
        assert "yk-script/CHANGELOG.md" in paths_called

    def test_upload_with_existing_sha(self):
        """已有文件路径 → sha check 返回 sha → PUT body 含 sha"""
        b = _make_backup(max_retries=2)
        sha_mock = MagicMock(return_value="existing-sha")
        with patch.object(b, "_get_existing_sha", sha_mock), \
             patch.object(b, "_get_existing_content", return_value=None), \
             patch("src.backup.requests.put", return_value=_put_201_resp()) as m:
            b.upload("# md", _make_meta())
        # sha 必被检查 (4 个 PUT 路径都查)
        assert sha_mock.call_count >= 4
        # 检查第一个 PUT body 含 sha
        first_body = m.call_args_list[0].kwargs.get("json") or m.call_args_list[0].args[1]
        assert first_body.get("sha") == "existing-sha"

    def test_5xx_retries_then_raises(self):
        b = _make_backup(max_retries=2)
        # 4 个 PUT 路径, 每个 retry 2 次, 每次 mock 返回 500 → 8 次调用
        resp = MagicMock(status_code=500, text="Server Error")
        with patch.object(b, "_get_existing_sha", return_value=None), \
             patch.object(b, "_get_existing_content", return_value=None), \
             patch("src.backup.requests.put", return_value=resp), \
             patch("src.backup.time.sleep"):
            with pytest.raises(BackupError, match="重试 2 次后仍失败"):
                b.upload("# md", _make_meta())

    def test_4xx_no_retry(self):
        b = _make_backup(max_retries=3)
        resp = MagicMock(status_code=400, text="bad request")
        with patch.object(b, "_get_existing_sha", return_value=None), \
             patch.object(b, "_get_existing_content", return_value=None), \
             patch("src.backup.requests.put", return_value=resp) as m, \
             patch("src.backup.time.sleep"):
            with pytest.raises(BackupError, match="4xx"):
                b.upload("# md", _make_meta())
        # 第 1 个文件 PUT 失败 → 不重试 (4xx 立即抛)
        assert m.call_count == 1

    def test_network_error_retries(self):
        b = _make_backup(max_retries=2)
        # 第 1 个 PUT: 网络错 → 重试 → 第 2 次 201
        # 第 2 个 PUT (meta): 直接 201
        # 第 3 个 PUT (index): 直接 201
        # 第 4 个 PUT (changelog): 直接 201
        seq = [
            requests.ConnectionError("boom"),
            _put_201_resp("sha1"),
            _put_201_resp("sha2"),
            _put_201_resp("sha3"),
            _put_201_resp("sha4"),
        ]
        with patch.object(b, "_get_existing_sha", return_value=None), \
             patch.object(b, "_get_existing_content", return_value=None), \
             patch("src.backup.requests.put", side_effect=seq), \
             patch("src.backup.time.sleep"):
            result = b.upload("# md", _make_meta())
        assert result.commit_sha == "sha4"
