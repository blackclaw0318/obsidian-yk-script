"""
test_prompt_renderer.py — Jinja2 渲染测试

验证:
- 加载 prompts/*.yaml
- 渲染 system_prompt 和 user_prompt_template
- StrictUndefined 模式: 变量缺失报错
- 缓存机制
"""

from __future__ import annotations

import json

import pytest
from jinja2 import StrictUndefined

from src.prompt_renderer import (
    _compile_template,
    _load_template_file,
    clear_cache,
    render_prompt_template,
    render_string,
)


@pytest.fixture(autouse=True)
def reset_cache():
    clear_cache()
    yield
    clear_cache()


class TestLoadTemplate:
    def test_load_writer_yaml(self):
        data = _load_template_file("writer.yaml")
        assert "system_prompt" in data
        assert "user_prompt_template" in data
        assert data["version"] == "0.3.0"

    def test_load_critic_rubric(self):
        data = _load_template_file("critic_rubric.yaml")
        assert "perspectives" in data
        assert len(data["perspectives"]) == 5

    def test_load_memory_constraints(self):
        data = _load_template_file("memory_constraints.yaml")
        assert "hard_constraints" in data
        assert len(data["hard_constraints"]) == 4

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_template_file("nonexistent.yaml")


class TestRenderString:
    def test_simple_substitution(self):
        result = render_string("Hello {{ name }}!", {"name": "World"})
        assert result == "Hello World!"

    def test_strict_undefined_missing_var(self):
        """StrictUndefined: 变量缺失报错 (不静默空字符串)"""
        with pytest.raises(StrictUndefined):
            render_string("Hello {{ name }}!", {})

    def test_jinja_control_flow(self):
        template = "{% for item in items %}{{ item }},{% endfor %}"
        result = render_string(template, {"items": ["a", "b", "c"]})
        assert result == "a,b,c,"

    def test_jinja_conditional(self):
        template = "{% if x %}YES{% else %}NO{% endif %}"
        assert render_string(template, {"x": True}) == "YES"
        assert render_string(template, {"x": False}) == "NO"


class TestRenderPromptTemplate:
    def test_writer_system_prompt_with_characters(self):
        """system_prompt 用 Jinja 渲染角色红线"""
        with open("data/characters/protagonist.json") as f:
            protagonist = json.load(f)
        with open("data/characters/youkei.json") as f:
            youkei = json.load(f)
        with open("data/characters/apartment.json") as f:
            apartment = json.load(f)

        result = render_prompt_template(
            "writer.yaml",
            {
                "character_protagonist": protagonist,
                "character_youkei": youkei,
                "character_apartment": apartment,
            },
            field="system_prompt",
        )
        assert "3 秒钩子定律" in result
        assert "Save the Cat 5 beats" in result or "Opening Image" in result

    def test_writer_user_prompt_with_episode_spec(self):
        with open("data/seasons/season-01.json") as f:
            season = json.load(f)
        ep_data = season["episodes"][0]  # EP01

        result = render_prompt_template(
            "writer.yaml",
            {
                "episode_spec": ep_data,
                "character_protagonist": {"forbidden": []},
                "character_youkei": {"forbidden": []},
                "character_apartment": {"forbidden_in_apartment": []},
                "season_context": {"season_id": 1},
                "references_excerpt": "",
            },
            field="user_prompt_template",
        )
        assert "EP1" in result
        assert "📦 搬家日" in result or ep_data["title"] in result

    def test_default_field_detection(self):
        """不传 field 参数时, 自动选 system_prompt"""
        with open("data/characters/protagonist.json") as f:
            p = json.load(f)
        with open("data/characters/youkei.json") as f:
            y = json.load(f)
        with open("data/characters/apartment.json") as f:
            a = json.load(f)

        # writer.yaml 默认是 system_prompt
        result = render_prompt_template(
            "writer.yaml",
            {
                "character_protagonist": p,
                "character_youkei": y,
                "character_apartment": a,
            },
        )
        assert "3 秒钩子定律" in result

    def test_invalid_field_raises(self):
        with pytest.raises(KeyError):
            render_prompt_template("writer.yaml", {}, field="nonexistent_field")


class TestCache:
    def test_template_cache(self):
        t1 = _compile_template("test {{ x }}")
        t2 = _compile_template("test {{ x }}")
        assert t1 is t2  # 同一对象 (cache 生效)

    def test_clear_cache(self):
        _compile_template("a {{ x }}")
        clear_cache()
        # 缓存已清, 下次是新对象
        t = _compile_template("a {{ x }}")
        assert t.render(x=1) == "a 1"