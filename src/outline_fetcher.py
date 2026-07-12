"""
outline_fetcher.py — 从 GitHub 拉取老板 web UI 编辑的 season 大纲

职责 (v0.3 文档 §3.8):
- 从 obsidian-yk-script 仓 data/seasons/season-XX.json 拉最新大纲
- sha 检测变更 (If-None-Match / 本地缓存比对)
- 3 级 fallback: GitHub → 本地缓存 → 本地仓库文件
- 失败不阻塞主流程 (P8 决策: 备份失败不阻塞, 同理拉大纲失败用本地)

调用方:
- src/daily.py (cron 6am_shanghai, 优先 GitHub 最新版, 失败 fallback 本地)
- scripts/pull_outline.py (手动强制拉)

设计:
- 走 GitHub Contents API (GET /repos/{owner}/{repo}/contents/{path})
- 本地缓存: data/cache/outline/season-XX.{json,sha} (gitignored)
- sha 缓存: data/cache/outline/season-XX.sha (单文件)
- 复用 publisher BackupReader 模式

参考: src/backup_reader.py (publisher)
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_REPO = "blackclaw0318/obsidian-yk-script"

# 本地缓存路径
CACHE_ROOT = Path("data/cache/outline")


class OutlineFetcherError(Exception):
    """GitHub 拉大纲失败 (5xx 重试耗尽 / 4xx 参数错 / 网络错)"""


class OutlineSource:
    """大纲来源标识"""

    GITHUB = "github"  # 来自 GitHub 最新版
    CACHE = "cache"  # 来自本地缓存 (上次 GitHub 成功的版本)
    LOCAL = "local"  # 来自本地仓库文件 (git 仓里的版本, 兜底)


class OutlineFetcher:
    """GitHub Contents API 只读客户端 + 本地缓存

    用法:
        fetcher = OutlineFetcher(token=os.environ["GITHUB_BACKUP_TOKEN"])
        data, source = fetcher.fetch_season(season_id=1)
        # data = {episodes: [...], stage_distribution: {...}, ...}
        # source = "github" | "cache" | "local"
    """

    def __init__(
        self,
        token: str,
        repo: str = DEFAULT_REPO,
        branch: str = "main",
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        api_base: str = GITHUB_API_BASE,
        cache_dir: Path | None = None,
    ):
        if "/" not in repo:
            raise ValueError(f"repo 必须是 'owner/name' 格式: {repo!r}")
        if not token or not token.strip():
            raise ValueError("token 不能为空 (或纯空白)")

        self.owner, self.name = repo.split("/", 1)
        self.token = token
        self.branch = branch
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.api_base = api_base.rstrip("/")
        self.cache_dir = cache_dir or CACHE_ROOT
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ===== 公开接口 =====

    def fetch_season(self, season_id: int) -> tuple[dict, str]:
        """拉取某季大纲 (3 级 fallback)

        Args:
            season_id: 季号 (1, 2, ...)

        Returns:
            (data, source): data = 解析后的 JSON dict; source = "github"/"cache"/"local"

        Raises:
            OutlineFetcherError: 3 级都失败 (极其罕见, 通常最后一级 local 总能成功)
        """
        path = f"data/seasons/season-{season_id:02d}.json"
        local_path = Path(f"data/seasons/season-{season_id:02d}.json")

        # Level 1: GitHub
        try:
            data, sha = self._fetch_from_github(path)
            self._save_cache(season_id, data, sha)
            logger.info(f"✅ Season-{season_id:02d} outline fetched from GitHub (sha={sha[:8]})")
            return data, OutlineSource.GITHUB
        except Exception as e:
            logger.warning(f"⚠️ GitHub fetch 失败: {e}, fallback to cache")

        # Level 2: 本地缓存
        cached_data, cached_sha = self._load_cache(season_id)
        if cached_data is not None:
            logger.info(
                f"📦 Season-{season_id:02d} outline loaded from cache (sha={cached_sha[:8] if cached_sha else '?'})",
            )
            return cached_data, OutlineSource.CACHE

        # Level 3: 本地仓库文件
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text(encoding="utf-8"))
                logger.info(f"📂 Season-{season_id:02d} outline loaded from local file (last resort)")
                return data, OutlineSource.LOCAL
            except (json.JSONDecodeError, ValueError) as e:
                raise OutlineFetcherError(
                    f"3 级 fallback 全失败: GitHub 错 + cache 无 + local 文件损坏: {e}",
                ) from e

        # 极端兜底: 全部失败
        raise OutlineFetcherError(
            f"3 级 fallback 全失败: GitHub 错 + cache 无 + local 文件不存在 ({local_path})",
        )

    def fetch_season_if_changed(self, season_id: int) -> tuple[dict, str] | None:
        """仅在 GitHub sha 变更时返回新数据

        Args:
            season_id: 季号

        Returns:
            (data, source) 或 None (sha 没变)
        """
        path = f"data/seasons/season-{season_id:02d}.json"
        try:
            data, new_sha = self._fetch_from_github(path)
        except Exception as e:
            logger.warning(f"⚠️ fetch_season_if_changed 失败: {e}")
            return None

        cached_sha = self._load_cached_sha(season_id)
        if cached_sha == new_sha:
            logger.info(
                f"Season-{season_id:02d} sha unchanged ({new_sha[:8]}), 跳过",
            )
            return None

        self._save_cache(season_id, data, new_sha)
        logger.info(
            f"🆕 Season-{season_id:02d} sha changed "
            f"({cached_sha[:8] if cached_sha else '?'} → {new_sha[:8]})",
        )
        return data, OutlineSource.GITHUB

    # ===== GitHub API =====

    def _fetch_from_github(self, path: str) -> tuple[dict, str]:
        """从 GitHub Contents API 拉文件

        Returns:
            (data, sha): data = 解析后的 dict; sha = blob sha (供下次比对)

        Raises:
            OutlineFetcherError: 网络/HTTP 错误
        """
        url = self._url(path)
        last_err: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.get(
                    url,
                    headers=self._headers(),
                    params={"ref": self.branch},
                    timeout=(10, self.timeout_s),
                )
                if resp.status_code == 404:
                    raise OutlineFetcherError(
                        f"GitHub 404: {self.owner}/{self.name}@main:{path} 不存在",
                    )
                if 400 <= resp.status_code < 500:
                    # 4xx 是逻辑错误, 不重试, 立刻抛
                    raise OutlineFetcherError(
                        f"4xx ({resp.status_code}) GET {path}: {resp.text[:300]}",
                    )
                if resp.status_code >= 500:
                    # 5xx 走网络错误路径, 触发 retry
                    raise requests.HTTPError(
                        f"5xx ({resp.status_code}) GET {path}: {resp.text[:200]}",
                    )

                resp.raise_for_status()
                body = resp.json()
                sha = body.get("sha")
                if not sha:
                    raise OutlineFetcherError(f"GitHub 响应缺 sha: {body}")

                # GitHub Contents API: content 是 base64 编码
                encoding = body.get("encoding", "")
                content_b64 = body.get("content", "")
                if encoding != "base64" or not content_b64:
                    raise OutlineFetcherError(
                        f"GitHub 响应缺 base64 content (encoding={encoding}): {body}",
                    )

                # base64 解码 (GitHub 返回含换行, 需 strip)
                raw = base64.b64decode(content_b64).decode("utf-8")
                data = json.loads(raw)
                return data, sha
            except OutlineFetcherError:
                # 逻辑错误 (4xx/404/响应解析错) 不重试, 直接抛
                raise
            except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
                # 网络错 / 5xx 重试
                last_err = e
                logger.warning(f"GitHub fetch attempt {attempt}/{self.max_retries} 失败: {e}")
                if attempt >= self.max_retries:
                    break

        raise OutlineFetcherError(
            f"GitHub fetch 重试 {self.max_retries} 次耗尽: {last_err}",
        ) from last_err

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "obsidian-yk-script/0.3",
        }

    def _url(self, path: str) -> str:
        return f"{self.api_base}/repos/{self.owner}/{self.name}/contents/{path}"

    # ===== 本地缓存 =====

    def _cache_json_path(self, season_id: int) -> Path:
        return self.cache_dir / f"season-{season_id:02d}.json"

    def _cache_sha_path(self, season_id: int) -> Path:
        return self.cache_dir / f"season-{season_id:02d}.sha"

    def _save_cache(self, season_id: int, data: dict, sha: str) -> None:
        """原子写缓存 (json + sha)"""
        import os
        import tempfile

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        json_path = self._cache_json_path(season_id)
        sha_path = self._cache_sha_path(season_id)

        # 写 json
        fd, tmp_json = tempfile.mkstemp(dir=self.cache_dir, prefix=".season-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_json, json_path)
        except Exception:
            if Path(tmp_json).exists():
                Path(tmp_json).unlink()
            raise

        # 写 sha
        sha_path.write_text(sha, encoding="utf-8")

    def _load_cache(self, season_id: int) -> tuple[dict | None, str | None]:
        """读本地缓存"""
        json_path = self._cache_json_path(season_id)
        sha_path = self._cache_sha_path(season_id)
        if not json_path.exists():
            return None, None
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            sha = sha_path.read_text(encoding="utf-8").strip() if sha_path.exists() else None
            return data, sha
        except (json.JSONDecodeError, ValueError, OSError) as e:
            logger.warning(f"⚠️ cache 损坏: {e}")
            return None, None

    def _load_cached_sha(self, season_id: int) -> str | None:
        """只读缓存的 sha (供 if_changed 比对)"""
        sha_path = self._cache_sha_path(season_id)
        if not sha_path.exists():
            return None
        try:
            return sha_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None


# ===== 工厂 =====
def make_default_fetcher() -> OutlineFetcher:
    """工厂: 从环境变量构造默认 fetcher"""
    import os

    token = os.environ.get("GITHUB_BACKUP_TOKEN", "")
    if not token:
        raise OutlineFetcherError(
            "GITHUB_BACKUP_TOKEN 环境变量未设置 (需要 PAT 含 obsidian-yk-script: Read scope)",
        )
    repo = os.environ.get("GITHUB_OUTLINE_REPO", DEFAULT_REPO)
    return OutlineFetcher(token=token, repo=repo)


def fetch_season_with_fallback(
    season_id: int,
    *,
    token: str | None = None,
) -> tuple[dict, str]:
    """Convenience wrapper for fetch_season with graceful fallback.

    When token is None, attempts GITHUB_BACKUP_TOKEN env var;
    on failure, reads local season file directly.
    Used by daily cron at 6am_shanghai Asia/Shanghai.
    """
    # 自动 token
    if token is None:
        import os

        token = os.environ.get("GITHUB_BACKUP_TOKEN", "")

    if token:
        try:
            fetcher = OutlineFetcher(token=token)
            return fetcher.fetch_season(season_id)
        except Exception as e:
            logger.warning(f"⚠️ fetcher 失败: {e}, 直接读本地")

    # 直接读本地
    local_path = Path(f"data/seasons/season-{season_id:02d}.json")
    if local_path.exists():
        try:
            data = json.loads(local_path.read_text(encoding="utf-8"))
            logger.info(f"📂 Season-{season_id:02d} outline loaded from local (无 token)")
            return data, OutlineSource.LOCAL
        except (json.JSONDecodeError, ValueError) as e:
            raise OutlineFetcherError(f"本地 season-{season_id:02d}.json 损坏: {e}") from e

    raise OutlineFetcherError(
        f"无 GITHUB_BACKUP_TOKEN + 本地 data/seasons/season-{season_id:02d}.json 不存在",
    )