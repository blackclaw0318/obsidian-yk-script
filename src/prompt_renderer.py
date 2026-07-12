"""
prompt_renderer.py — Jinja2 加载与渲染

设计:
- 加载 prompts/*.yaml 中的 system_prompt + user_prompt_template
- 渲染时填充变量 (character_*, episode_spec, references_excerpt)
- 模板缓存 (避免重复读盘)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, Template

ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT / "prompts"


@lru_cache(maxsize=16)
def _load_template_file(name: str) -> dict[str, Any]:
    """加载 prompts/<name> 文件 (YAML)"""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"prompt 模板不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _make_jinja_env() -> Environment:
    """Jinja2 严格模式: 变量未定义报错 (不静默空字符串)"""
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,  # 我们处理的是 LLM prompt, 不是 HTML
        keep_trailing_newline=True,
    )


@lru_cache(maxsize=16)
def _compile_template(source: str) -> Template:
    """编译 Jinja2 模板"""
    return _make_jinja_env().from_string(source)


def render_string(source: str, context: dict[str, Any]) -> str:
    """渲染 Jinja2 字符串模板"""
    template = _compile_template(source)
    return template.render(**context)


def render_prompt_template(
    name: str,
    context: dict[str, Any],
    *,
    field: str | None = None,
) -> str:
    """加载并渲染 prompts/<name>

    Args:
        name: 文件名 (例 "writer.yaml")
        context: Jinja2 变量字典
        field: 指定字段 (默认 "system_prompt" 或 "user_prompt_template")

    Returns:
        渲染后的字符串

    Examples:
        >>> render_prompt_template("writer.yaml", ctx)  # 渲染 system_prompt
        >>> render_prompt_template("writer.yaml", ctx, field="user_prompt_template")
    """
    data = _load_template_file(name)
    if field is None:
        # 默认: Writer 用 system_prompt, Critic 用 system_prompt
        # user 端用 field="user_prompt_template"
        if "system_prompt" in data:
            field = "system_prompt"
        elif "user_prompt_template" in data:
            field = "user_prompt_template"
        else:
            raise KeyError(f"{name} 缺少 system_prompt / user_prompt_template")
    if field not in data:
        raise KeyError(f"{name} 缺少字段: {field}")
    return render_string(data[field], context)


def clear_cache() -> None:
    """清除模板缓存 (测试用)"""
    _load_template_file.cache_clear()
    _compile_template.cache_clear()
