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
