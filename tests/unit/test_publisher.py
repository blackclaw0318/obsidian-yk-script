"""
test_publisher.py — publisher 单元测试

覆盖:
- EpisodePayload slug / external_id / to_body
- _make_excerpt (从 markdown 提取首段)
- PublisherConfig.from_env (凭据缺失 raise)
- Publisher.push_one: 201 OK / 4xx 不重试 / 5xx 重试到耗尽 / 网络错
- make_default_publisher: 凭据缺失返回 None (不抛)
- get_post_url (提取 url)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.publisher import (
    EpisodePayload,
    Publisher,
    PublisherConfig,
    PublisherError,
    get_post_url,
    make_default_publisher,
)

SECRET = "a" * 64
URL = "https://www.shangkun.uk/api/external/posts"


# ============================================================
# EpisodePayload
# ============================================================

class TestEpisodePayload:
    def test_slug_and_id(self):
        p = EpisodePayload(
            season_id=1,
            episode_idx=1,
            title="搬家日",
            content_md="# EP1 ...",
        )
        assert p.slug == "yk-s01-ep01"
        assert p.external_id == "yk-s01-ep01"

    def test_slug_season_2(self):
        p = EpisodePayload(season_id=2, episode_idx=12, title="x", content_md="x")
        assert p.slug == "yk-s02-ep12"

    def test_to_body_required_fields(self):
        p = EpisodePayload(season_id=1, episode_idx=1, title="搬家日", content_md="正文")
        body = p.to_body()
        for k in ("slug", "title", "content", "category", "external_id", "idempotency_key"):
            assert k in body, f"缺少字段 {k}"

    def test_to_body_category_life(self):
        p = EpisodePayload(season_id=1, episode_idx=1, title="t", content_md="x")
        body = p.to_body()
        assert body["category"] == "life"

    def test_to_body_external_meta(self):
        p = EpisodePayload(season_id=1, episode_idx=5, title="t", content_md="x", word_count=2000)
        body = p.to_body()
        assert body["external_meta"]["episode"] == 5
        assert body["external_meta"]["word_count"] == 2000
        assert body["external_meta"]["source"] == "yk-script-p12"

    def test_idempotency_key_per_call(self):
        p = EpisodePayload(season_id=1, episode_idx=1, title="t", content_md="x")
        keys = {p.to_body()["idempotency_key"] for _ in range(20)}
        # 每次 to_body 生成新 key
        assert len(keys) == 20


# ============================================================
# _make_excerpt
# ============================================================

class TestExcerpt:
    def test_simple(self):
        p = EpisodePayload(
            season_id=1,
            episode_idx=1,
            title="t",
            content_md="# Header\n\nFirst paragraph is the excerpt.\n\nMore text.",
        )
        body = p.to_body()
        assert "excerpt" in body
        assert "First paragraph" in body["excerpt"]

    def test_truncated_to_max_len(self):
        long_line = "x" * 500
        p = EpisodePayload(
            season_id=1,
            episode_idx=1,
            title="t",
            content_md=f"# H\n\n{long_line}\n",
        )
        body = p.to_body()
        assert len(body["excerpt"]) <= 240


# ============================================================
# PublisherConfig.from_env
# ============================================================

class TestPublisherConfig:
    def test_missing_url(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_PUBLISH_URL", raising=False)
        monkeypatch.setenv("OBSIDIAN_PUBLISH_SECRET", SECRET)
        with pytest.raises(PublisherError, match="OBSIDIAN_PUBLISH_URL"):
            PublisherConfig.from_env()

    def test_missing_secret(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_PUBLISH_URL", URL)
        monkeypatch.delenv("OBSIDIAN_PUBLISH_SECRET", raising=False)
        with pytest.raises(PublisherError, match="OBSIDIAN_PUBLISH_SECRET"):
            PublisherConfig.from_env()

    def test_all_ok(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_PUBLISH_URL", URL)
        monkeypatch.setenv("OBSIDIAN_PUBLISH_SECRET", SECRET)
        monkeypatch.setenv("YK_PUBLISHER_ID", "yk-script")
        cfg = PublisherConfig.from_env()
        assert cfg.publish_url == URL
        assert cfg.publish_secret == SECRET


# ============================================================
# Publisher.push_one
# ============================================================

def _ok_response():
    resp = MagicMock()
    resp.status_code = 201
    resp.json.return_value = {
        "ok": True,
        "post": {
            "id": "post_123",
            "slug": "yk-s01-ep01",
            "url": "https://www.shangkun.uk/posts/yk-s01-ep01",
        },
    }
    resp.raise_for_status = MagicMock()
    return resp


def _4xx_response():
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "bad_slug"
    return resp


def _5xx_response():
    resp = MagicMock()
    resp.status_code = 500
    resp.text = "Internal Server Error"
    return resp


def _make_publisher():
    return Publisher(PublisherConfig(publish_url=URL, publish_secret=SECRET))


def _make_payload():
    return EpisodePayload(
        season_id=1,
        episode_idx=1,
        title="搬家日",
        content_md="# EP1\n\nFirst line",
        word_count=1800,
    )


class TestPushOne:
    def test_201_ok(self):
        pub = _make_publisher()
        with patch("src.publisher.requests.post", return_value=_ok_response()) as m:
            result = pub.push_one(_make_payload())
        assert result["post"]["id"] == "post_123"
        # 验证 HMAC headers 被加进去
        headers = m.call_args.kwargs["headers"]
        assert headers["X-Publisher-Id"] == "yk-script"
        assert "X-Publisher-Signature" in headers
        # raw_body 与 data 一致
        assert m.call_args.kwargs["data"] is not None

    def test_4xx_no_retry(self):
        pub = _make_publisher()
        with patch("src.publisher.requests.post", return_value=_4xx_response()) as m:
            with pytest.raises(PublisherError, match="4xx"):
                pub.push_one(_make_payload())
        assert m.call_count == 1

    def test_5xx_retries_then_raises(self):
        pub = Publisher(PublisherConfig(publish_url=URL, publish_secret=SECRET, max_retries=2))
        with patch("src.publisher.requests.post", return_value=_5xx_response()) as m, \
             patch("src.publisher.time.sleep"):
            with pytest.raises(PublisherError, match="重试 2 次后仍失败"):
                pub.push_one(_make_payload())
        assert m.call_count == 2

    def test_5xx_retry_succeed(self):
        pub = Publisher(PublisherConfig(publish_url=URL, publish_secret=SECRET, max_retries=3))
        seq = [_5xx_response(), _5xx_response(), _ok_response()]
        with patch("src.publisher.requests.post", side_effect=seq), \
             patch("src.publisher.time.sleep"):
            result = pub.push_one(_make_payload())
        assert result["post"]["id"] == "post_123"

    def test_network_error_retries(self):
        pub = Publisher(PublisherConfig(publish_url=URL, publish_secret=SECRET, max_retries=2))
        seq = [requests.ConnectionError("boom"), _ok_response()]
        with patch("src.publisher.requests.post", side_effect=seq), \
             patch("src.publisher.time.sleep"):
            result = pub.push_one(_make_payload())
        assert result["post"]["id"] == "post_123"


# ============================================================
# make_default_publisher / get_post_url
# ============================================================

class TestFactory:
    def test_no_creds_returns_none(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_PUBLISH_URL", raising=False)
        monkeypatch.delenv("OBSIDIAN_PUBLISH_SECRET", raising=False)
        assert make_default_publisher() is None

    def test_with_creds_returns_publisher(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_PUBLISH_URL", URL)
        monkeypatch.setenv("OBSIDIAN_PUBLISH_SECRET", SECRET)
        p = make_default_publisher()
        assert isinstance(p, Publisher)


class TestGetPostUrl:
    def test_extracts_url(self):
        result = {"post": {"url": "https://x.com/y"}}
        assert get_post_url(result) == "https://x.com/y"

    def test_missing_post(self):
        assert get_post_url({}) == ""
        assert get_post_url(None) == ""
        assert get_post_url("not dict") == ""
