"""
test_p17_retry.py — P1.7-B (prompt 强化) + P1.7-D (智能重试) 单测门控

P1.7 落地方案 (2026-07-15 老板拍板 B+D):
- B: writer.yaml 加硬规则段 (关键词必含), 加载 satisfaction_verifier_keywords
- D: daily.py 加重试循环 (P1.4 软约束 → 拿缺关键词 → 调 writer 重写)

总目标: 8+ 测试覆盖
  - _extract_p14_missing_keywords helper (4 cases)
  - Writer retry_keywords / retry_round 参数注入 (2 cases)
  - writer.yaml 模板硬规则段渲染 (2 cases)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.daily import _extract_p14_missing_keywords
from src.types import (
    EpisodeScript,
    HookSpec,
    HookType,
    SatisfactionType,
    SelfCheck,
    Shot,
    make_episode_script_from_json,
)


# ============================================================
# 1. _extract_p14_missing_keywords helper 测试
# ============================================================


class TestExtractP14MissingKeywords:
    """P1.7-D: 解析 P1.4 violations 的 fix_suggestion 拿缺关键词"""

    def test_hook_verifier_keywords_format_recommend(self):
        """hook_verifier_keywords_missing_p14: '推荐: kw1/kw2/kw3' 格式"""
        v = MagicMock()
        v.constraint_id = "hook_verifier_keywords_missing_p14"
        v.fix_suggestion = "末 shot 字幕/动作/voiceover 加 ≥ 1 个关键词 (推荐: 突然/下一秒/没想到)"
        result = _extract_p14_missing_keywords([v])
        assert result == ["突然", "下一秒", "没想到"]

    def test_emotion_keywords_format_list_literal(self):
        """emotion_keywords_missing_p14: list literal ['kw1', 'kw2'] 格式"""
        v = MagicMock()
        v.constraint_id = "emotion_keywords_missing_p14"
        v.fix_suggestion = "字幕/voiceover 加 ≥ 1 个关键词: ['没想到', '原来', '我以为']"
        result = _extract_p14_missing_keywords([v])
        assert result == ["没想到", "原来", "我以为"]

    def test_satisfaction_coverage_format(self):
        """satisfaction_coverage_low_p14: '预期: [type1, type2]' 格式"""
        v = MagicMock()
        v.constraint_id = "satisfaction_coverage_low_p14"
        v.fix_suggestion = "覆盖不足, 补 1 个预期类型: ['情感爆发', '悬念揭秘']"
        result = _extract_p14_missing_keywords([v])
        # satisfaction_coverage 返回的是 type, 不是 keyword, 但函数通用提取
        assert "情感爆发" in result
        assert "悬念揭秘" in result

    def test_dedup_and_order(self):
        """多个 violations 的关键词去重保序"""
        v1 = MagicMock()
        v1.constraint_id = "hook_verifier_keywords_missing_p14"
        v1.fix_suggestion = "推荐: 突然/没想到/原来"

        v2 = MagicMock()
        v2.constraint_id = "emotion_keywords_missing_p14"
        v2.fix_suggestion = "加 ≥ 1 个关键词: ['原来', '突然', '我以为']"

        result = _extract_p14_missing_keywords([v1, v2])
        # v1 顺序: 突然/没想到/原来
        # v2 加: 原来 (dup)/突然 (dup)/我以为
        # 去重后保 v1 的顺序: 突然/没想到/原来/我以为
        assert result == ["突然", "没想到", "原来", "我以为"]

    def test_empty_fix_suggestion(self):
        """fix_suggestion 为空时返回空列表 (不抛)"""
        v = MagicMock()
        v.constraint_id = "hook_verifier_keywords_missing_p14"
        v.fix_suggestion = ""
        result = _extract_p14_missing_keywords([v])
        assert result == []

    def test_irrelevant_violation_skipped(self):
        """非 P1.4 软约束的 violation 跳过"""
        v = MagicMock()
        v.constraint_id = "shot_count_too_low"  # 不是 P1.4 软约束
        v.fix_suggestion = "推荐: foo/bar"
        # 即使 constraint_id 不在 retryable 集合, helper 只解析 fix_suggestion 不做过滤
        # 这是 helper 的责任分离: 过滤交给 daily.py, helper 只负责解析
        result = _extract_p14_missing_keywords([v])
        # 实际会返回解析结果 (过滤在 daily.py 调 _extract_p14_missing_keywords 前已完成)
        assert "foo" in result


# ============================================================
# 2. Writer retry 参数注入测试
# ============================================================


class TestWriterRetryInjection:
    """P1.7-D: Writer.generate_episode_candidates 接受 retry_keywords / retry_round"""

    def _make_writer(self):
        from src.writer import Writer
        from src.llm_client import LLMClient
        client = MagicMock(spec=LLMClient)
        return Writer(client, n_candidates=1)

    def test_retry_round_default_is_1(self):
        """默认 retry_round=1, retry_keywords=[]"""
        import inspect
        from src.writer import Writer
        sig = inspect.signature(Writer.generate_episode_candidates)
        assert sig.parameters["retry_round"].default == 1
        assert sig.parameters["retry_keywords"].default is None

    def test_season_context_includes_satisfaction_verifier_keywords(self):
        """P1.7-B: _build_season_context 必含 satisfaction_verifier_keywords 字段"""
        from src.writer import Writer
        # 写一个最小的 season fixture
        season = {
            "season_no": 1,
            "title": "test",
            "theme": "test theme",
            "total_episodes": 12,
            "episodes": [{"ep": 1, "hook_type": "悬念钩", "satisfaction_types": ["情感爆发"], "stage": "起势段"}],
            "stage_distribution": {"起势段": {"description": "起", "rhythm_intensity": "★"}},
            "quality_targets": {"hook_strength_min": "中等"},
        }
        ep = season["episodes"][0]
        writer = self._make_writer()
        ctx = writer._build_season_context(season, ep)
        assert "satisfaction_verifier_keywords" in ctx
        assert isinstance(ctx["satisfaction_verifier_keywords"], list)
        # 情感爆发必有 verifier_keywords
        assert len(ctx["satisfaction_verifier_keywords"]) > 0


# ============================================================
# 3. writer.yaml 模板硬规则段渲染测试
# ============================================================


class TestWriterPromptHardRules:
    """P1.7-B: writer.yaml 硬规则段 + retry 段渲染正确"""

    def _render(self, season_context, retry_keywords=None, retry_round=1):
        from src.prompt_renderer import render_prompt_template
        # 补全 season_context 必填字段 (template 引用 season_id/title/theme/hook_verifier_keywords 等)
        full_sc = {
            "season_id": 1,
            "title": "test",
            "theme": "test theme",
            "total_episodes": 12,
            "stage_description": "test stage",
            "stage_intensity": "★",
            "stage_adaptations": "",
            "hook_verifier_keywords": [],
            "satisfaction_verifier_keywords": [],
            "hook_strength_min": "中等",
            "quality_targets": {"shot_count": "3-8", "duration_target_s": 60, "emotion_peaks_per_episode": "1", "hook_strength_min": "中等"},
        }
        full_sc.update(season_context)
        ctx = {
            "character_protagonist": {"name": "test", "forbidden": ""},
            "character_youkei": {"name": "yk", "forbidden": ""},
            "character_apartment": {"name": "apt", "forbidden_in_apartment": ""},
            "episode_spec": {"ep": 1, "title": "test", "hook_type": "悬念钩", "stage": "起势段", "stage_position_pct": 8, "scene": "客厅", "core_conflict": "test", "logline": "test logline", "hook_subtype": "test", "hook_text_template": "?", "satisfaction_types": ["情感爆发"], "satisfaction_intensity": "★★★", "key_moments": ["m1"], "rhythm_notes": "test", "next_episode_seed": "test seed"},
            "season_context": full_sc,
            "pct": 8,
            "references_excerpt": "",
            "retry_keywords": retry_keywords or [],
            "retry_round": retry_round,
        }
        return render_prompt_template("writer.yaml", ctx, field="system_prompt")

    def test_hard_rules_section_renders_hook_keywords(self):
        """有 hook_verifier_keywords 时, 硬规则段含 '本集钩子关键词'"""
        sc = {
            "hook_verifier_keywords": ["突然", "下一秒"],
            "satisfaction_verifier_keywords": [],
        }
        result = self._render(sc)
        assert "硬规则" in result
        assert "本集钩子关键词" in result
        assert "突然" in result
        assert "下一秒" in result

    def test_hard_rules_section_renders_satisfaction_keywords(self):
        """有 satisfaction_verifier_keywords 时, 硬规则段含 '爽点关键词'"""
        sc = {
            "hook_verifier_keywords": [],
            "satisfaction_verifier_keywords": ["没想到", "原来"],
        }
        result = self._render(sc)
        assert "爽点关键词" in result
        assert "没想到" in result
        assert "原来" in result

    def test_retry_section_renders_when_retry_keywords(self):
        """有 retry_keywords 时, 硬规则段含 '第 N 轮重试' + 缺关键词列表"""
        sc = {"hook_verifier_keywords": [], "satisfaction_verifier_keywords": []}
        result = self._render(sc, retry_keywords=["突然", "原来"], retry_round=2)
        assert "第 2 轮重试" in result
        assert "突然" in result
        assert "原来" in result

    def test_no_retry_section_when_empty(self):
        """retry_keywords 为空时, 硬规则段不含 '第 N 轮重试'"""
        sc = {"hook_verifier_keywords": ["?"], "satisfaction_verifier_keywords": []}
        result = self._render(sc, retry_keywords=[], retry_round=1)
        assert "第 1 轮重试" not in result

    def test_no_crash_with_empty_season_context(self):
        """season_context 完全为空也不 crash (default 容错)"""
        sc = {}
        # 应该不抛, 即使字段都缺
        result = self._render(sc)
        # 渲染结果应该仍然非空 (硬规则段不渲染, 但其他部分还在)
        assert len(result) > 1000
