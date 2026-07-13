"""
backup.py — GitHub 备份 (私仓 obsidian-novel-backups/yk-script/)
============================================================

每次成功推送博客后, 把 episode (md + meta.json) 备份到 GitHub 私仓,
作为 obsidian-journal 站点丢失时的离线副本。

设计:
- 走 GitHub Contents API (PUT /repos/{owner}/{repo}/contents/{path})
- 不走 git push (轻量, 无需本地 clone)
- 编码 base64 (GitHub API 标准)
- 失败重试 3 次 (1s/2s/4s 退避), 4xx 不重试
- **失败不阻塞主推送**: 备份失败 -> logger.warning, 不抛 (外层接 warn)
- sha 必传: 覆盖已存在文件必须先 GET 拿 sha

适配 yk-script:
- novel_id 默认 'yk-script'
- 路径 schema:
    yk-script/{chapters,covers,meta}/yk-s01-epNN.{md,jpg,json}
    yk-script/index.json
    yk-script/CHANGELOG.md
- 不上传封面 jpg (yk-script v1 不生成封面, 留扩展点)

依赖: requests, pydantic
凭据: GITHUB_BACKUP_TOKEN (fine-grained PAT, Contents: Read+Write on backups 仓)
"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_NOVEL_ID = "yk-script"
GITHUB_API_BASE = "https://api.github.com"

_RETRY_BACKOFF_S = (1, 2, 4)


# ============================================================
# 异常
# ============================================================


class BackupError(Exception):
    """GitHub 备份失败

    注: 调用方应 try/except 捕获, 失败不回滚已成功的博客推送。
    """


# ============================================================
# 数据模型
# ============================================================


class EpisodeMeta(BaseModel):
    """单集 episode 元信息

    字段:
        season_id:   季号 (1, 2, ...)
        episode_idx: 集号 (1-12)
        title:       集标题
        word_count:  字数
        created_at:  ISO 8601 UTC
        post_url:    博客侧推送后的 URL
        extra:       自由扩展字段
    """

    season_id: int = Field(..., ge=1)
    episode_idx: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    word_count: int = Field(default=0, ge=0)
    created_at: str = Field(..., min_length=1)
    post_url: str = Field(default="")
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def now(
        cls,
        *,
        season_id: int,
        episode_idx: int,
        title: str,
        word_count: int,
        post_url: str = "",
        **extra: Any,
    ) -> "EpisodeMeta":
        return cls(
            season_id=season_id,
            episode_idx=episode_idx,
            title=title,
            word_count=word_count,
            created_at=datetime.now(UTC).isoformat(),
            post_url=post_url,
            extra=extra,
        )


class BackupResult(BaseModel):
    """单次备份结果"""

    commit_sha: str = ""
    pushed_files: list[str] = Field(default_factory=list)


# ============================================================
# 主类
# ============================================================


class Backup:
    """GitHub Contents API 客户端 — 备份 episode 到 obsidian-novel-backups/yk-script/

    用法:
        backup = Backup(token=...)
        result = backup.upload(
            md="# EP1 ...\\n\\n正文...",
            meta=EpisodeMeta.now(season_id=1, episode_idx=1, title="搬家日", word_count=1800, post_url="..."),
        )
    """

    def __init__(
        self,
        token: str,
        repo: str = "blackclaw0318/obsidian-novel-backups",
        branch: str = "main",
        novel_id: str = DEFAULT_NOVEL_ID,
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        api_base: str = GITHUB_API_BASE,
    ):
        if "/" not in repo:
            raise ValueError(f"repo 必须是 'owner/name' 格式: {repo!r}")
        if not token or not token.strip():
            raise ValueError("token 不能为空 (或纯空白)")

        self.owner, self.name = repo.split("/", 1)
        self.token = token
        self.branch = branch
        self.novel_id = novel_id
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.api_base = api_base.rstrip("/")

    # ---------- public API ----------

    def upload(
        self,
        md: str,
        meta: EpisodeMeta,
    ) -> BackupResult:
        """完整备份一次: md + meta + 更新 index + CHANGELOG

        Args:
            md:  完整 episode markdown 文本
            meta:  EpisodeMeta (含 season_id / episode_idx / title / ...)

        Returns:
            BackupResult { commit_sha, pushed_files }

        Raises:
            BackupError: 备份失败 (4xx / 重试 / 网络错)
        """
        pushed: list[str] = []
        last_commit_sha = ""

        # 1. 推 md + meta (2 文件, 不存封面 jpg)
        files_to_push: list[tuple[str, str, str]] = [
            (self._chapter_path(meta.season_id, meta.episode_idx), md, "text/markdown; charset=utf-8"),
            (self._meta_path(meta.season_id, meta.episode_idx), meta.model_dump_json(indent=2), "application/json"),
        ]

        for path, content, mime in files_to_push:
            logger.info("[backup] PUT %s (%d bytes)", path, len(content))
            result = self._put_file(path, content, mime, meta, allow_overwrite=True)
            last_commit_sha = result["commit_sha"]
            pushed.append(path)

        # 2. 更新 index.json
        index_path = self._index_path()
        existing_index = self._get_existing_content(index_path)
        index_data = self._build_index(existing_index, meta)
        logger.info("[backup] PUT %s (index)", index_path)
        result = self._put_file(
            index_path,
            json.dumps(index_data, ensure_ascii=False, indent=2),
            "application/json",
            meta,
            allow_overwrite=True,
        )
        last_commit_sha = result["commit_sha"]
        pushed.append(index_path)

        # 3. 更新 CHANGELOG.md
        changelog_path = self._changelog_path()
        existing_changelog = self._get_existing_content(changelog_path) or "# CHANGELOG\n\n"
        changelog_data = self._build_changelog(existing_changelog, meta)
        logger.info("[backup] PUT %s (changelog)", changelog_path)
        result = self._put_file(
            changelog_path,
            changelog_data,
            "text/markdown; charset=utf-8",
            meta,
            allow_overwrite=True,
        )
        last_commit_sha = result["commit_sha"]
        pushed.append(changelog_path)

        logger.info(
            "[backup] ✅ 备份完成, commit=%s, files=%d",
            last_commit_sha[:12],
            len(pushed),
        )
        return BackupResult(commit_sha=last_commit_sha, pushed_files=pushed)

    # ---------- 路径生成 ----------

    def _chapter_path(self, season_id: int, ep: int) -> str:
        return f"{self.novel_id}/chapters/yk-s{season_id:02d}-ep{ep:02d}.md"

    def _meta_path(self, season_id: int, ep: int) -> str:
        return f"{self.novel_id}/meta/yk-s{season_id:02d}-ep{ep:02d}.json"

    def _index_path(self) -> str:
        return f"{self.novel_id}/index.json"

    def _changelog_path(self) -> str:
        return f"{self.novel_id}/CHANGELOG.md"

    # ---------- index + changelog 构建 ----------

    def _build_index(
        self,
        existing_content: str | None,
        meta: EpisodeMeta,
    ) -> dict[str, Any]:
        """追加新 episode 到 index.json
        Schema:
            {
              "novel_id": "yk-script",
              "episodes": [
                {
                  "season_id": 1, "episode_idx": 1, "title": "...", "word_count": 1800,
                  "created_at": "...", "post_url": "...",
                  "files": {"chapter": "...", "meta": "..."}
                }
              ],
              "updated_at": "..."
            }
        """
        if existing_content:
            try:
                data = json.loads(existing_content)
            except json.JSONDecodeError:
                logger.warning("[backup] index.json 解析失败, 重置为空 dict")
                data = {}
        else:
            data = {}

        episodes = data.get("episodes", [])
        # 幂等: 同 (season, ep) 已存在则覆盖, 不重复
        key = lambda e: (e.get("season_id", 0), e.get("episode_idx", 0))
        new_key = (meta.season_id, meta.episode_idx)
        episodes = [e for e in episodes if key(e) != new_key]
        episodes.append(
            {
                "season_id": meta.season_id,
                "episode_idx": meta.episode_idx,
                "title": meta.title,
                "word_count": meta.word_count,
                "created_at": meta.created_at,
                "post_url": meta.post_url,
                "files": {
                    "chapter": self._chapter_path(meta.season_id, meta.episode_idx),
                    "meta": self._meta_path(meta.season_id, meta.episode_idx),
                },
            }
        )
        episodes.sort(key=key)

        return {
            "novel_id": self.novel_id,
            "episodes": episodes,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def _build_changelog(
        self,
        existing_content: str,
        meta: EpisodeMeta,
    ) -> str:
        """追加每日汇总到 CHANGELOG.md"""
        date_str = meta.created_at[:10]
        section_header = f"## {date_str}"
        entry = (
            f"### yk-s{meta.season_id:02d}-ep{meta.episode_idx:02d} — {meta.title} "
            f"({meta.created_at})\n"
            f"- 字数: {meta.word_count}\n"
        )
        if meta.post_url:
            entry += f"- 博客: {meta.post_url}\n"

        if section_header in existing_content:
            parts = existing_content.split(section_header, 1)
            before, after = parts[0], parts[1]
            next_section_idx = after.find("\n## ")
            if next_section_idx == -1:
                new_after = after.rstrip() + "\n\n" + entry
            else:
                new_after = (
                    after[:next_section_idx].rstrip() + "\n\n" + entry + after[next_section_idx:]
                )
            return before + section_header + new_after
        return existing_content.rstrip() + f"\n\n{section_header}\n\n{entry}"

    # ---------- GitHub API 底层 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _url(self, path: str) -> str:
        return f"{self.api_base}/repos/{self.owner}/{self.name}/contents/{path}"

    def _get_existing_content(self, path: str) -> str | None:
        url = self._url(path)
        try:
            resp = requests.get(url, headers=self._headers(), timeout=(10, self.timeout_s))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            body = resp.json()
            content_b64 = body.get("content", "").replace("\n", "")
            return base64.b64decode(content_b64).decode("utf-8")
        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.warning("[backup] GET %s 失败: %s (返回 None)", path, e)
            return None

    def _put_file(
        self,
        path: str,
        content: str,
        mime: str,
        meta: EpisodeMeta,
        *,
        allow_overwrite: bool = False,
    ) -> dict[str, str]:
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

        sha: str | None = None
        if allow_overwrite:
            sha = self._get_existing_sha(path)

        commit_msg = self._commit_message(path, meta, is_overwrite=sha is not None)
        body: dict[str, Any] = {
            "message": commit_msg,
            "content": content_b64,
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha

        url = self._url(path)
        last_err: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.put(
                    url,
                    headers=self._headers(),
                    json=body,
                    timeout=(10, self.timeout_s),
                )
                if 400 <= resp.status_code < 500:
                    raise BackupError(
                        f"4xx ({resp.status_code}) PUT {path} 失败 (不重试): {resp.text[:300]}"
                    )
                if resp.status_code >= 500:
                    raise BackupError(f"5xx ({resp.status_code}) PUT {path} 服务器错 (重试)")

                resp.raise_for_status()
                commit_sha = resp.json().get("commit", {}).get("sha", "")
                logger.info(
                    "[backup] PUT %s ✅ commit=%s",
                    path,
                    commit_sha[:12] if commit_sha else "(empty)",
                )
                return {"commit_sha": commit_sha}

            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(
                    "[backup] PUT %s 网络错 (attempt %d/%d): %s",
                    path,
                    attempt,
                    self.max_retries,
                    e,
                )
            except BackupError as e:
                last_err = e
                if "4xx" in str(e):
                    raise
                logger.warning(
                    "[backup] PUT %s 5xx (attempt %d/%d): %s",
                    path,
                    attempt,
                    self.max_retries,
                    e,
                )

            if attempt < self.max_retries:
                sleep_s = _RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)]
                time.sleep(sleep_s)

        raise BackupError(f"PUT {path} 重试 {self.max_retries} 次后仍失败: {last_err}")

    def _get_existing_sha(self, path: str) -> str | None:
        url = self._url(path)
        try:
            resp = requests.get(url, headers=self._headers(), timeout=(10, self.timeout_s))
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json().get("sha")
        except requests.exceptions.RequestException as e:
            logger.warning("[backup] GET %s sha 失败: %s", path, e)
            return None

    def _commit_message(self, path: str, meta: EpisodeMeta, *, is_overwrite: bool) -> str:
        basename = path.rsplit("/", 1)[-1] if "/" in path else path
        prefix = f"yk-s{meta.season_id:02d}-ep{meta.episode_idx:02d}: {meta.title}"
        if is_overwrite and basename in ("index.json", "CHANGELOG.md"):
            return f"update {basename} for yk-s{meta.season_id:02d}-ep{meta.episode_idx:02d} ({prefix})"
        return f"backup yk-s{meta.season_id:02d}-ep{meta.episode_idx:02d} ({prefix})"
