"""
test_critic.py — Critic 模块单元测试

P9 fix: select_best 返回 verdict_map 改为 dict[int, CriticVerdict],
        EpisodeScript 不可哈希 (Pydantic BaseModel), 用 ep 编号当 key。

测试覆盖:
- TestSelectBest::test_select_best_returns_ep_keyed_map  返回 dict[int, CriticVerdict]
- TestSelectBest::test_select_best_no_hashable_error     不再抛 TypeError unhashable
- TestSelectBest::test_select_best_picks_highest_score   选最高分
- TestSelectBest::test_select_best_empty_candidates      全失败 → (None, {})
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.critic import Critic
from src.llm_client import LLMClient
from src.types import EpisodeScript, Verdict


def _make_ep(ep: int, title: str) -> EpisodeScript:
    """构造合法 EpisodeScript"""
    from tests.unit.test_types import make_episode

    return make_episode(ep=ep, title=title)


def _mock_verdict(ep: int, total: int, verdict: Verdict = Verdict.PASS) -> MagicMock:
    """构造 mock CriticResult, .verdict.total_score"""
    result = MagicMock()
    v = MagicMock()
    v.total_score = total
    v.verdict = verdict
    result.verdict = v
    return result


class TestSelectBest:
    """P9 fix: select_best 返回值 key 类型修复"""

    def test_select_best_returns_ep_keyed_map(self):
        """verdict_map 必须是 dict[int, CriticVerdict] (key 是 ep 编号)"""
        critic = Critic(MagicMock(spec=LLMClient))
        ep1, ep2 = _make_ep(1, "EP1"), _make_ep(2, "EP2")

        # mock critique_episode: ep1=42, ep2=35
        critic.critique_episode = MagicMock(side_effect=[
            _mock_verdict(1, 42),
            _mock_verdict(2, 35),
        ])

        best, verdicts = critic.select_best([ep1, ep2])

        assert best is ep1  # 42 > 35
        assert isinstance(verdicts, dict)
        # key 必须是 int (ep 编号), 不能是 EpisodeScript (会 unhashable)
        for k in verdicts.keys():
            assert isinstance(k, int), f"verdict_map key 必须是 int, 得到 {type(k)}"
        assert 1 in verdicts
        assert 2 in verdicts

    def test_select_best_no_hashable_error(self):
        """P9 fix: 不再抛 TypeError: unhashable type: 'EpisodeScript'"""
        critic = Critic(MagicMock(spec=LLMClient))
        ep1 = _make_ep(1, "EP1")

        critic.critique_episode = MagicMock(return_value=_mock_verdict(1, 38))

        # 不应抛 unhashable 异常
        best, verdicts = critic.select_best([ep1])
        assert best is ep1
        assert verdicts[1].total_score == 38

    def test_select_best_picks_highest_score(self):
        """选 total_score 最高者"""
        critic = Critic(MagicMock(spec=LLMClient))
        eps = [_make_ep(i, f"EP{i}") for i in range(1, 4)]

        # ep1=35, ep2=42, ep3=30 → 选 ep2
        critic.critique_episode = MagicMock(side_effect=[
            _mock_verdict(1, 35),
            _mock_verdict(2, 42),
            _mock_verdict(3, 30),
        ])

        best, verdicts = critic.select_best(eps)
        assert best is eps[1]  # ep2
        assert verdicts[1].total_score == 35
        assert verdicts[2].total_score == 42
        assert verdicts[3].total_score == 30

    def test_select_best_excellent_priority(self):
        """同分时 EXCELLENT 优先"""
        critic = Critic(MagicMock(spec=LLMClient))
        ep1, ep2 = _make_ep(1, "EP1"), _make_ep(2, "EP2")

        # ep1=PASS=40, ep2=EXCELLENT=40 → 选 ep2
        critic.critique_episode = MagicMock(side_effect=[
            _mock_verdict(1, 40, Verdict.PASS),
            _mock_verdict(2, 40, Verdict.EXCELLENT),
        ])

        best, verdicts = critic.select_best([ep1, ep2])
        assert best is ep2

    def test_select_best_empty_candidates(self):
        """空候选 → (None, {})"""
        critic = Critic(MagicMock(spec=LLMClient))
        best, verdicts = critic.select_best([])
        assert best is None
        assert verdicts == {}

    def test_select_best_all_critique_failed(self):
        """全部 critique_episode 返 None verdict → (None, {})"""
        critic = Critic(MagicMock(spec=LLMClient))
        ep1 = _make_ep(1, "EP1")

        failed_result = MagicMock()
        failed_result.verdict = None
        critic.critique_episode = MagicMock(return_value=failed_result)

        best, verdicts = critic.select_best([ep1])
        assert best is None
        assert verdicts == {}


# ===== P1.3 — Critic 接收 episode_spec + season_context =====

class TestP13CriticAcceptsSpec:
    """P1.3: critic 注入 episode_spec + season_context"""

    def test_critique_episode_with_spec(self):
        """critique_episode(script, ep_spec, season_ctx) 应渲染成功 (mock LLM)"""
        from unittest.mock import MagicMock
        from src.critic import Critic
        from src.types import CriticVerdict, Verdict
        from tests.unit.test_types import make_episode

        # Mock LLM 返回合法 CriticVerdict JSON
        mock_client = MagicMock()
        mock_client.messages_create.return_value = MagicMock(
            text=json.dumps({
                "episode_id": 1,
                "perspectives": [
                    {"id": "humor", "score": 4, "reason": "ok", "improvement": "无"},
                    {"id": "cuteness", "score": 4, "reason": "ok", "improvement": "无"},
                    {"id": "continuity", "score": 4, "reason": "ok", "improvement": "无"},
                    {"id": "rhythm", "score": 4, "reason": "ok", "improvement": "无"},
                    {"id": "red_line", "score": 5, "reason": "ok", "improvement": "无"},
                ],
                "total_score": 41,
                "verdict": "PASS",
                "feedback": "ok",
                "should_rewrite": False,
            }),
            duration_ms=100,
            input_tokens=100,
            output_tokens=50,
            stop_reason="end_turn",
        )

        critic = Critic(mock_client)
        ep = make_episode(ep=1, title="📦 搬家日")

        # P1.3: 注入 ep_spec + season_ctx
        ep_spec = {
            "ep": 1, "title": "📦 搬家日",
            "hook_type": "悬念钩", "hook_subtype": "来者悬念",
            "hook_text_template": "客厅尽头那个最大的纸箱, 突然动了一下",
            "satisfaction_types": ["情感爆发"], "satisfaction_intensity": "★★★",
            "key_moments": ["0:05 钻纸箱", "0:30 找猫", "0:50 探头"],
            "rhythm_notes": "前 5s 必现冲突",
            "next_episode_seed": "EP02 第一夜",
            "stage": "起势段",
        }
        season_ctx = {
            "season_id": 1, "title": "上坤 × YouKei", "theme": "适应",
            "total_episodes": 12,
            "stage_description": "建立核心",
            "stage_intensity": "★★",
            "stage_adaptations": "情感爆发 100%",
            "hook_verifier_keywords": ["?", "突然"],
            "quality_targets": {"shot_count": "3-8", "duration_target_s": 60},
            "hook_strength_min": "中等",
        }

        result = critic.critique_episode(ep, ep_spec, season_ctx)
        assert result.error is None, f"Critic 失败: {result.error}"
        assert result.verdict is not None
        assert result.verdict.total_score == 41
        assert result.verdict.verdict == Verdict.PASS

    def test_system_prompt_includes_episode_spec(self):
        """system_prompt 渲染结果应包含本集预期字段 (无 LLM 调用)"""
        import json
        from src.critic import Critic

        mock_client = MagicMock()
        critic = Critic(mock_client)

        rubric = critic._load_rubric()
        characters = critic._load_characters()
        ep_spec = {
            "ep": 1, "title": "📦 搬家日",
            "hook_type": "悬念钩", "hook_subtype": "来者悬念",
            "hook_text_template": "客厅尽头那个最大的纸箱, 突然动了一下",
            "satisfaction_types": ["情感爆发"], "satisfaction_intensity": "★★★",
            "key_moments": ["0:05"], "rhythm_notes": "前 5s 必现冲突",
            "next_episode_seed": "EP02", "stage": "起势段",
        }
        season_ctx = {
            "stage_intensity": "★★",
            "hook_verifier_keywords": ["?", "突然"],
        }

        sp = critic._build_system_prompt(rubric, characters, ep_spec, season_ctx)
        # 关键字段
        assert "本集预期" in sp
        assert "悬念钩" in sp
        assert "客厅尽头那个最大的纸箱" in sp
        assert "情感爆发" in sp
        assert "?" in sp or "突然" in sp  # hook_verifier_keywords
        assert "一致性检查" in sp

    def test_system_prompt_works_without_episode_spec(self):
        """向后兼容: 不传 ep_spec 也能渲染"""
        from unittest.mock import MagicMock
        from src.critic import Critic

        mock_client = MagicMock()
        critic = Critic(mock_client)

        rubric = critic._load_rubric()
        characters = critic._load_characters()

        sp = critic._build_system_prompt(rubric, characters, None, None)
        # 不报错 + 不含"本集预期"
        assert len(sp) > 500
        assert "未提供 episode_spec" in sp or "P1.3" in sp


# Helper for json import (上面用了 json)
import json
