"""
publisher.py - 推送 1 集 daily 产物到 obsidian-journal 公仓博客
================================================================

职责 (v0.3 §3.9 增项 P12):
- 把 episode markdown 通过 HMAC 鉴权 POST 到 obsidian-journal /api/external/posts
- category = "life" (生活分类)
- slug 唯一, idempotency_key 防双发
- 失败抛 PublisherError (外层 daily.py try/except 捕获 → 不阻塞下一步)

依赖:
- requests
- src.hmac_client (本仓库)
- .env: OBSIDIAN_PUBLISH_URL / OBSIDIAN_PUBLISH_SECRET / YK_PUBLISHER_ID

调用方:
- src/daily.py stage 7 publish

设计:
- 单 push_one() 函数, 1 章 1 次调用
- 不管理 state (daily.py 自己管 state.json)
- 失败抛 PublisherError (4xx 参数错 / 5xx 重试 / 网络错)
- 重试: 5xx / 网络错重试 3 次 (1s/2s/4s 退避), 4xx 不重试
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import requests

from src.hmac_client import HmacClient, HmacConfig, new_idempotency_key

logger = logging.getLogger(__name__)


# 协议常量
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_CATEGORY = "life"  # yk-script 是生活类短视频脚本
DEFAULT_PUBLISH_ID = "yk-script"

_RETRY_BACKOFF_S = (1, 2, 4)


# ============================================================
# 异常
# ============================================================


class PublisherError(Exception):
    """推送失败 (4xx / 5xx 重试耗尽 / 网络错)"""


# ============================================================
# 数据类
# ============================================================


@dataclass
class EpisodePayload:
    """1 集 episode 要推送的字段"""

    season_id: int
    episode_idx: int  # 1-12
    title: str
    content_md: str  # 完整 markdown
    word_count: int = 0
    cover_url: str | None = None

    @property
    def slug(self) -> str:
        return f"yk-s{self.season_id:02d}-ep{self.episode_idx:02d}"

    @property
    def external_id(self) -> str:
        return self.slug

    def to_body(self) -> dict:
        """生成 POST body (按 obsidian-journal API_INTEGRATION.md 契约)"""
        return {
            "slug": self.slug,
            "title": self.title,
            "content": self.content_md,
            "category": DEFAULT_CATEGORY,
            "external_id": self.external_id,
            "excerpt": _make_excerpt(self.content_md, max_len=240),
            "tags": "YouKei,缅因猫,上坤×YouKei,单元剧",
            "cover_image": self.cover_url,
            "external_meta": {
                "source": "yk-script-p12",
                "season": self.season_id,
                "episode": self.episode_idx,
                "word_count": self.word_count,
                "pipeline": "writer→critic→hard_check→memory→render→publish",
            },
            "idempotency_key": new_idempotency_key(),
        }


def _make_excerpt(md: str, max_len: int = 240) -> str:
    """从 markdown 提取摘要

    跳过: 标题行 (`# ...`) / 块引 (`> ...`) / 分隔线 (`---`) / 强调 (`**...**`)
    取第一个非上述行
    """
    skip_prefixes = ("#", ">", "-", "*", "**")
    for raw in md.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(skip_prefixes):
            continue
        if line in ("---", "***"):
            continue
        return line[:max_len]
    # 极端兜底: 返回全部文本前 max_len
    return md[:max_len]


# ============================================================
# 主类
# ============================================================


@dataclass
class PublisherConfig:
    """publisher 凭据 (从 .env 读)"""

    publish_url: str  # https://www.shangkun.uk/api/external/posts
    publish_secret: str  # hex >= 32 chars
    publish_id: str = DEFAULT_PUBLISH_ID
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_MAX_RETRIES

    @classmethod
    def from_env(cls) -> PublisherConfig:
        url = os.environ.get("OBSIDIAN_PUBLISH_URL", "").rstrip("/")
        secret = os.environ.get("OBSIDIAN_PUBLISH_SECRET", "")
        publish_id = os.environ.get("YK_PUBLISHER_ID", DEFAULT_PUBLISH_ID)
        if not url:
            raise PublisherError("OBSIDIAN_PUBLISH_URL 环境变量未设置")
        if not secret:
            raise PublisherError("OBSIDIAN_PUBLISH_SECRET 环境变量未设置")
        return cls(publish_url=url, publish_secret=secret, publish_id=publish_id)


class Publisher:
    """obsidian-journal HMAC POST 客户端"""

    def __init__(self, config: PublisherConfig):
        if not config.publish_url:
            raise PublisherError("publish_url 不能为空")
        if not config.publish_secret:
            raise PublisherError("publish_secret 不能为空")
        self.config = config
        self.hmac = HmacClient(HmacConfig(publish_id=config.publish_id, publish_secret=config.publish_secret))

    def push_one(self, payload: EpisodePayload) -> dict:
        """推送 1 集 episode

        Returns:
            dict: obsidian-journal 响应内容, e.g. {"ok": true, "post": {"id": ..., "slug": ..., "url": "..."}}

        Raises:
            PublisherError: 4xx 参数错 / 5xx 重试耗尽 / 网络错
        """
        body = payload.to_body()
        raw_body = json.dumps(body, ensure_ascii=False)  # 与服务端 rawBody 验签契约一致
        headers = self.hmac.sign(body, raw_body=raw_body)
        headers["Content-Type"] = "application/json"

        url = self.config.publish_url
        last_err: Exception | None = None

        for attempt in range(1, self.config.max_retries + 1):
            try:
                logger.info(
                    "[publisher] POST attempt %d/%d slug=%s",
                    attempt,
                    self.config.max_retries,
                    payload.slug,
                )
                resp = requests.post(
                    url,
                    headers=headers,
                    data=raw_body.encode("utf-8"),
                    timeout=(10, self.config.timeout_s),
                )

                # 4xx: 参数错, 不重试
                if 400 <= resp.status_code < 500:
                    raise PublisherError(
                        f"4xx ({resp.status_code}) POST {payload.slug}: {resp.text[:300]}"
                    )

                if resp.status_code >= 500:
                    raise PublisherError(
                        f"5xx ({resp.status_code}) POST {payload.slug}: {resp.text[:200]}"
                    )

                resp.raise_for_status()
                result = resp.json()
                logger.info(
                    "[publisher] ✅ slug=%s post_id=%s",
                    payload.slug,
                    result.get("post", {}).get("id", "(no id)"),
                )
                return result

            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning(
                    "[publisher] slug=%s 网络错 (attempt %d/%d): %s",
                    payload.slug,
                    attempt,
                    self.config.max_retries,
                    e,
                )
            except PublisherError as e:
                last_err = e
                if "4xx" in str(e):
                    raise  # 4xx 立即抛
                logger.warning(
                    "[publisher] slug=%s 5xx (attempt %d/%d): %s",
                    payload.slug,
                    attempt,
                    self.config.max_retries,
                    e,
                )

            if attempt < self.config.max_retries:
                sleep_s = _RETRY_BACKOFF_S[min(attempt - 1, len(_RETRY_BACKOFF_S) - 1)]
                time.sleep(sleep_s)

        raise PublisherError(
            f"推送 slug={payload.slug} 重试 {self.config.max_retries} 次后仍失败: {last_err}"
        )


def make_default_publisher() -> Publisher | None:
    """工厂: 从 .env 构造, 凭据缺失返回 None (不抛, 让 daily.py 优雅降级)"""
    try:
        cfg = PublisherConfig.from_env()
        return Publisher(cfg)
    except PublisherError as e:
        logger.warning(f"[publisher] 凭据缺失, publisher 不可用: {e}")
        return None


def get_post_url(result: dict) -> str:
    """从 obsidian-journal 响应里取 URL, 缺失返回空串"""
    if not isinstance(result, dict):
        return ""
    post = result.get("post") or {}
    return post.get("url") or ""
