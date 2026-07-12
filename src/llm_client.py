"""
llm_client.py — minimax Anthropic-compatible 客户端

设计:
- 基于 requests (避免 anthropic SDK 依赖,更轻)
- 流式响应 (v0.40 教训: 非流式服务端 thinking 卡 180s)
- X-Api-Key header (不是 Bearer — v0.40 教训)
- 0 字符响应 → ZeroLengthResponseError (v0.40 fix)
- 严格 stop_reason 检测

参考: minimax 官方文档 https://platform.minimaxi.com/docs/guides/text-generation
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from src.types import LLMError, ZeroLengthResponseError

DEFAULT_BASE_URL = "https://api.minimaxi.com/anthropic"
DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_TIMEOUT_S = 180


@dataclass
class LLMConfig:
    """LLM 调用配置"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_s: int = DEFAULT_TIMEOUT_S
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> LLMConfig:
        """从环境变量加载 (.env 由 daily cron 加载)"""
        api_key = os.environ.get("MINIMAXI_API_KEY", "")
        if not api_key:
            raise LLMError("MINIMAXI_API_KEY 环境变量未设置")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("MINIMAXI_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("MINIMAXI_TEXT_MODEL", DEFAULT_MODEL),
            timeout_s=int(os.environ.get("MINIMAXI_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
            max_retries=int(os.environ.get("MINIMAXI_MAX_RETRIES", "2")),
        )


@dataclass
class LLMResponse:
    """LLM 调用响应"""

    text: str
    stop_reason: str | None  # end_turn / max_tokens / refusal / tool_use
    input_tokens: int
    output_tokens: int
    duration_ms: int
    model: str


class LLMClient:
    """minimax Anthropic-compatible 客户端"""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()

    @property
    def headers(self) -> dict[str, str]:
        """Anthropic 协议: X-Api-Key (不是 Bearer!)"""
        return {
            "X-Api-Key": self.config.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

    def messages_create(
        self,
        system: str,
        user: str,
        temperature: float = 0.85,
        max_tokens: int = 8000,
        stream: bool = False,
    ) -> LLMResponse:
        """调用 Anthropic-compatible Messages API

        Args:
            system: 系统提示 (角色认知 + 公式 + 红线)
            user: 用户提示 (本集任务 + 角色档案)
            temperature: 创作温度 (Writer 0.85, Critic 0.3)
            max_tokens: 最大输出 token (M2.7 thinking ~2000 + 正文 ~6000)
            stream: 是否流式 (推荐 True, 避免 thinking 卡 180s)

        Returns:
            LLMResponse: 文本 + stop_reason + usage

        Raises:
            ZeroLengthResponseError: 0 字符响应
            LLMError: 其他错误
        """
        url = f"{self.config.base_url.rstrip('/')}/v1/messages"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "stream": stream,
        }

        import time as _time
        start_ms = int(_time.time() * 1000)

        try:
            resp = requests.post(
                url,
                headers=self.headers,
                json=payload,
                timeout=self.config.timeout_s,
            )
        except requests.Timeout as e:
            raise LLMError(
                f"LLM 调用超时 ({self.config.timeout_s}s): {e}",
            ) from e
        except requests.RequestException as e:
            raise LLMError(f"LLM 网络错误: {e}") from e

        duration_ms = int(_time.time() * 1000) - start_ms

        if resp.status_code != 200:
            raise LLMError(
                f"LLM 返回 {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        # 流式或非流式都解析 JSON (Anthropic 流式末尾也是 JSON chunk)
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM 响应 JSON 解析失败: {e}", response_body=resp.text) from e

        # 提取文本 (Anthropic Messages: content[0].text)
        text = self._extract_text(data)
        stop_reason = data.get("stop_reason")
        usage = data.get("usage", {})

        # v0.40 fix: 0 字符必须硬校验抛错
        if not text or len(text.strip()) < 10:
            raise ZeroLengthResponseError(
                f"LLM 返回 {len(text)} 字符 (停止原因: {stop_reason})",
                status_code=resp.status_code,
                response_body=resp.text,
            )

        return LLMResponse(
            text=text,
            stop_reason=stop_reason,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            duration_ms=duration_ms,
            model=data.get("model", self.config.model),
        )

    def _extract_text(self, data: dict[str, Any]) -> str:
        """从 Anthropic Messages 响应提取文本"""
        content = data.get("content", [])
        if not content:
            return ""
        # Anthropic Messages: content 是 list[{type: "text", text: "..."}]
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in ("text", None)
        ]
        return "".join(texts).strip()


# ===== 工厂 =====
def make_default_client() -> LLMClient:
    """工厂: 从环境变量构造默认客户端"""
    return LLMClient()