"""
hmac_client.py — HMAC-SHA256 签名客户端 (publisher 侧)
=====================================================

对每次 POST 请求生成 HMAC-SHA256 签名 over (timestamp + body)

签名协议 (与 obsidian-journal P4 接收侧契约):
1. timestamp = unix milliseconds (int)
2. message = f"{timestamp}.{raw_body}"
3. signature = HMAC-SHA256(secret, message).hexdigest()
4. Headers:
   - X-Publisher-Id:        'yk-script'
   - X-Publisher-Signature: <hex>
   - X-Publisher-Timestamp: <int ms>
   - X-Idempotency-Key:     <uuid hex>
   - Content-Type:          application/json

复用自 obsidian-novel-publisher/src/hmac_client.py (整建制搬迁, 改 publish_id 默认值)。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

# 协议常量
TIMESTAMP_WINDOW_MS = 5 * 60 * 1000  # 5 分钟窗口
DEFAULT_PUBLISH_ID = "yk-script"


@dataclass(frozen=True)
class HmacConfig:
    """HMAC 客户端配置 (凭据从 .env 读)"""

    publish_id: str = DEFAULT_PUBLISH_ID
    publish_secret: str = ""
    timestamp_window_ms: int = TIMESTAMP_WINDOW_MS


class HmacError(Exception):
    """HMAC 签名 / 验签失败"""


def canonical_body(body: dict[str, Any]) -> str:
    """sort_keys + ensure_ascii + 无空白"""
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_signature(
    secret: str,
    timestamp_ms: int,
    body: dict[str, Any] | None = None,
    *,
    body_bytes: str | None = None,
) -> str:
    """二选一: body (dict, canonical 化) 或 body_bytes (str, 原样签名)"""
    if body_bytes is None:
        if body is None:
            raise HmacError("compute_signature 需传 body 或 body_bytes")
        body_bytes = canonical_body(body)
    message = f"{timestamp_ms}.{body_bytes}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def new_idempotency_key() -> str:
    """UUID v4 hex (无连字符)"""
    return uuid.uuid4().hex


class HmacClient:
    """HMAC 签名生成器"""

    def __init__(self, config: HmacConfig):
        if not config.publish_id:
            raise HmacError("publish_id 不能为空")
        if not config.publish_secret or len(config.publish_secret) < 32:
            raise HmacError(
                f"publish_secret 太短 ({len(config.publish_secret)} 字符), 建议 >= 32 字符 hex"
            )
        self.config = config

    def sign(
        self,
        body: dict[str, Any],
        *,
        timestamp_ms: int | None = None,
        idempotency_key: str | None = None,
        raw_body: str | None = None,
    ) -> dict[str, str]:
        """生成签名 headers 字典"""
        ts = timestamp_ms if timestamp_ms is not None else _now_ms()
        body_bytes = raw_body if raw_body is not None else json.dumps(body, ensure_ascii=False)
        sig = compute_signature(self.config.publish_secret, ts, body_bytes=body_bytes)
        idem = idempotency_key or new_idempotency_key()
        return {
            "X-Publisher-Id": self.config.publish_id,
            "X-Publisher-Signature": sig,
            "X-Publisher-Timestamp": str(ts),
            "X-Idempotency-Key": idem,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)
