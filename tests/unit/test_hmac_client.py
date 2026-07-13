"""
test_hmac_client.py — hmac_client 单元测试

覆盖:
- canonical_body (sort_keys + no whitespace)
- compute_signature (确定性, 不同输入 -> 不同签名)
- HmacClient.sign 生成 4 个 headers
- new_idempotency_key (UUID v4 hex, 32 chars)
- 构造校验 (publish_id 空 / secret 太短)
"""

from __future__ import annotations

from src.hmac_client import (
    HmacClient,
    HmacConfig,
    HmacError,
    canonical_body,
    compute_signature,
    new_idempotency_key,
)

SECRET = "a" * 64


# ============================================================
# canonical_body
# ============================================================

class TestCanonicalBody:
    def test_simple_dict(self):
        body = {"b": 2, "a": 1}
        assert canonical_body(body) == '{"a":1,"b":2}'

    def test_nested_dict_sorted(self):
        body = {"z": {"y": 2, "x": 1}, "a": 1}
        assert canonical_body(body) == '{"a":1,"z":{"x":1,"y":2}}'

    def test_unicode_preserved(self):
        body = {"title": "搬家日"}
        # ensure_ascii=False, 中文字符保留
        assert canonical_body(body) == '{"title":"搬家日"}'

    def test_no_whitespace(self):
        body = {"a": 1, "b": 2}
        result = canonical_body(body)
        assert " " not in result
        assert "\n" not in result


# ============================================================
# compute_signature
# ============================================================

class TestComputeSignature:
    def test_deterministic(self):
        s1 = compute_signature(SECRET, 1717699200000, {"a": 1})
        s2 = compute_signature(SECRET, 1717699200000, {"a": 1})
        assert s1 == s2

    def test_different_input_different_sig(self):
        s1 = compute_signature(SECRET, 1717699200000, {"a": 1})
        s2 = compute_signature(SECRET, 1717699200000, {"a": 2})
        assert s1 != s2

    def test_different_secret_different_sig(self):
        s1 = compute_signature(SECRET, 1717699200000, {"a": 1})
        s2 = compute_signature(SECRET + "b", 1717699200000, {"a": 1})
        assert s1 != s2

    def test_different_timestamp_different_sig(self):
        s1 = compute_signature(SECRET, 1717699200000, {"a": 1})
        s2 = compute_signature(SECRET, 1717699200001, {"a": 1})
        assert s1 != s2

    def test_body_bytes_path(self):
        body_bytes = '{"a":1}'
        s = compute_signature(SECRET, 1717699200000, body_bytes=body_bytes)
        # 等价 dict 路径应该一致 (因为 body 已是规范形式)
        s2 = compute_signature(SECRET, 1717699200000, {"a": 1})
        assert s == s2

    def test_neither_body_nor_bytes_raises(self):
        with __import__("pytest").raises(HmacError):
            compute_signature(SECRET, 1717699200000)


# ============================================================
# HmacClient
# ============================================================

class TestHmacClient:
    def test_sign_returns_4_headers(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret=SECRET))
        headers = client.sign({"slug": "yk-s01-ep01", "title": "t"})
        assert "X-Publisher-Id" in headers
        assert "X-Publisher-Signature" in headers
        assert "X-Publisher-Timestamp" in headers
        assert "X-Idempotency-Key" in headers

    def test_publisher_id_default_yk_script(self):
        cfg = HmacConfig(publish_id="yk-script", publish_secret=SECRET)
        client = HmacClient(cfg)
        headers = client.sign({"a": 1})
        assert headers["X-Publisher-Id"] == "yk-script"

    def test_idempotency_key_auto_generated(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret=SECRET))
        h1 = client.sign({"a": 1})
        h2 = client.sign({"a": 1})
        # 不同 idempotency_key (UUID)
        assert h1["X-Idempotency-Key"] != h2["X-Idempotency-Key"]
        # 都是 32 chars UUID v4 hex
        assert len(h1["X-Idempotency-Key"]) == 32

    def test_idempotency_key_provided(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret=SECRET))
        headers = client.sign({"a": 1}, idempotency_key="custom_key_abc")
        assert headers["X-Idempotency-Key"] == "custom_key_abc"

    def test_timestamp_provided(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret=SECRET))
        headers = client.sign({"a": 1}, timestamp_ms=1717699200000)
        assert headers["X-Publisher-Timestamp"] == "1717699200000"

    def test_raw_body_path(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret=SECRET))
        # 显式 raw_body 应当被签名 (与 HTTP 字节一致)
        headers = client.sign({"a": 1}, raw_body='{"a":1}')
        # 验证签名确实基于 raw_body (我们不重复验签, 仅确保不报错)
        assert "X-Publisher-Signature" in headers


# ============================================================
# 构造校验
# ============================================================

class TestConstruction:
    def test_publish_id_empty(self):
        with __import__("pytest").raises(HmacError, match="publish_id"):
            HmacClient(HmacConfig(publish_id="", publish_secret=SECRET))

    def test_secret_too_short(self):
        with __import__("pytest").raises(HmacError, match="publish_secret 太短"):
            HmacClient(HmacConfig(publish_id="yk-script", publish_secret="short"))

    def test_secret_empty(self):
        with __import__("pytest").raises(HmacError):
            HmacClient(HmacConfig(publish_id="yk-script", publish_secret=""))

    def test_secret_at_min_length(self):
        client = HmacClient(HmacConfig(publish_id="yk-script", publish_secret="a" * 32))
        assert client is not None


# ============================================================
# new_idempotency_key
# ============================================================

class TestIdempotencyKey:
    def test_format(self):
        key = new_idempotency_key()
        assert len(key) == 32
        assert "-" not in key

    def test_unique(self):
        keys = {new_idempotency_key() for _ in range(100)}
        assert len(keys) == 100
