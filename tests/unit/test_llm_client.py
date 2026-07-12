"""
test_llm_client.py — minimax Anthropic-compatible 客户端测试

验证:
- Headers 用 X-Api-Key (不是 Bearer!) — v0.40 教训
- 成功响应解析
- 0 字符 → ZeroLengthResponseError (v0.40 fix)
- 超时 / 非 200 / JSON 解析失败 → LLMError
- from_env 加载环境变量
"""

from __future__ import annotations

import pytest
import requests_mock

from src.llm_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMClient,
    LLMConfig,
    LLMError,
    ZeroLengthResponseError,
)


@pytest.fixture
def client() -> LLMClient:
    return LLMClient(LLMConfig(api_key="test-key-abc"))


@pytest.fixture
def anthropic_url() -> str:
    return f"{DEFAULT_BASE_URL}/v1/messages"


def make_anthropic_response(
    text: str = "Hello world",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 200,
    model: str = DEFAULT_MODEL,
) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


class TestLLMClientHeaders:
    """v0.40 教训: X-Api-Key header (不是 Bearer)"""

    def test_uses_x_api_key_not_bearer(self, client):
        h = client.headers
        assert "X-Api-Key" in h
        assert h["X-Api-Key"] == "test-key-abc"
        assert "Authorization" not in h
        assert "Bearer" not in str(h)

    def test_has_anthropic_version_header(self, client):
        assert client.headers["anthropic-version"] == "2023-06-01"

    def test_content_type_is_json(self, client):
        assert client.headers["Content-Type"] == "application/json"


class TestLLMClientSuccess:
    def test_messages_create_success(self, client, anthropic_url):
        with requests_mock.Mocker() as m:
            m.post(
                anthropic_url,
                json=make_anthropic_response(
                    text="生成的剧本内容",
                    stop_reason="end_turn",
                    input_tokens=944,
                    output_tokens=2579,
                ),
                status_code=200,
            )
            resp = client.messages_create(
                system="你是编剧", user="写 EP1", temperature=0.85, max_tokens=8000,
            )
            assert resp.text == "生成的剧本内容"
            assert resp.stop_reason == "end_turn"
            assert resp.input_tokens == 944
            assert resp.output_tokens == 2579
            assert resp.model == DEFAULT_MODEL

    def test_request_payload_structure(self, client, anthropic_url):
        with requests_mock.Mocker() as m:
            m.post(anthropic_url, json=make_anthropic_response(), status_code=200)
            client.messages_create(
                system="sys", user="usr",
                temperature=0.7, max_tokens=4096, stream=True,
            )
            # 验证请求体结构
            sent = m.last_request.json()
            assert sent["model"] == DEFAULT_MODEL
            assert sent["system"] == "sys"
            assert sent["messages"] == [{"role": "user", "content": "usr"}]
            assert sent["temperature"] == 0.7
            assert sent["max_tokens"] == 4096
            assert sent["stream"] is True

    def test_extract_text_with_multiple_blocks(self, client, anthropic_url):
        """content 是 list, 取所有 text block 拼接"""
        with requests_mock.Mocker() as m:
            m.post(
                anthropic_url,
                json={
                    "content": [
                        {"type": "text", "text": "第一段"},
                        {"type": "text", "text": "第二段"},
                    ],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "model": DEFAULT_MODEL,
                },
                status_code=200,
            )
            resp = client.messages_create(system="x", user="y")
            assert resp.text == "第一段第二段"


class TestLLMClientErrors:
    """v0.40 fix: 0 字符必须硬校验抛错"""

    def test_zero_length_response_raises(self, client, anthropic_url):
        """0 字符响应 → ZeroLengthResponseError"""
        with requests_mock.Mocker() as m:
            m.post(
                anthropic_url,
                json={
                    "content": [{"type": "text", "text": ""}],
                    "stop_reason": "refusal",
                    "usage": {"input_tokens": 100, "output_tokens": 0},
                    "model": DEFAULT_MODEL,
                },
                status_code=200,
            )
            with pytest.raises(ZeroLengthResponseError) as exc_info:
                client.messages_create(system="x", user="y")
            assert exc_info.value.status_code == 200
            assert "refusal" in str(exc_info.value)

    def test_whitespace_only_response_raises(self, client, anthropic_url):
        """只有空白字符 → ZeroLengthResponseError"""
        with requests_mock.Mocker() as m:
            m.post(
                anthropic_url,
                json={
                    "content": [{"type": "text", "text": "   \n\t  "}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "model": DEFAULT_MODEL,
                },
                status_code=200,
            )
            with pytest.raises(ZeroLengthResponseError):
                client.messages_create(system="x", user="y")

    def test_non_200_raises_llm_error(self, client, anthropic_url):
        with requests_mock.Mocker() as m:
            m.post(
                anthropic_url,
                text="Unauthorized",
                status_code=401,
            )
            with pytest.raises(LLMError) as exc_info:
                client.messages_create(system="x", user="y")
            assert exc_info.value.status_code == 401
            assert "401" in str(exc_info.value)

    def test_invalid_json_raises_llm_error(self, client, anthropic_url):
        with requests_mock.Mocker() as m:
            m.post(anthropic_url, text="not json", status_code=200)
            with pytest.raises(LLMError, match="JSON 解析失败"):
                client.messages_create(system="x", user="y")

    def test_timeout_raises_llm_error(self, anthropic_url):
        client = LLMClient(LLMConfig(api_key="x", timeout_s=1))
        with requests_mock.Mocker() as m:
            import requests as _req
            m.post(anthropic_url, exc=_req.Timeout("Timeout"))
            with pytest.raises(LLMError, match="超时"):
                client.messages_create(system="x", user="y")


class TestLLMConfig:
    def test_from_env_loads_api_key(self, monkeypatch):
        monkeypatch.setenv("MINIMAXI_API_KEY", "test-key-xyz")
        monkeypatch.setenv("MINIMAXI_BASE_URL", "https://custom.example/anthropic")
        monkeypatch.setenv("MINIMAXI_TEXT_MODEL", "MiniMax-M3")
        monkeypatch.setenv("MINIMAXI_TIMEOUT_S", "60")
        cfg = LLMConfig.from_env()
        assert cfg.api_key == "test-key-xyz"
        assert cfg.base_url == "https://custom.example/anthropic"
        assert cfg.model == "MiniMax-M3"
        assert cfg.timeout_s == 60

    def test_from_env_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("MINIMAXI_API_KEY", raising=False)
        with pytest.raises(LLMError, match="未设置"):
            LLMConfig.from_env()

    def test_defaults(self):
        cfg = LLMConfig(api_key="x")
        assert cfg.base_url == DEFAULT_BASE_URL
        assert cfg.model == DEFAULT_MODEL
        assert cfg.timeout_s == 180
        assert cfg.max_retries == 2
