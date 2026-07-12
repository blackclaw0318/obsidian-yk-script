"""
test_memory_manager.py — Agent 3 Memory Manager 单测门控

验证:
- MemoryBank / YoukeiState / EpisodeMemory Pydantic schema
- 加载不存在的 memory_bank.json → 空 bank
- add_episode 写入 + 查询
- save/load round-trip (atomic write 防并发)
- hard_check: 时间线倒退 / 钩子回收 / 末钩必设
- 钩子回收 keyword 匹配 (MVP 实现)

总目标: 25+ 测试覆盖状态机 + 跨集校验
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.memory_manager import (
    EpisodeMemory,
    MemoryBank,
    MemoryManager,
    YoukeiState,
    make_default_manager,
)
from src.types import (
    EpisodeScript,
    HookSpec,
    HookType,
    SatisfactionType,
    SelfCheck,
    Shot,
)


# ===== Fixtures =====
@pytest.fixture
def tmp_memory_path(tmp_path: Path) -> Path:
    """临时 memory_bank.json 路径 (隔离测试)"""
    return tmp_path / "memory_bank.json"


@pytest.fixture
def mm(tmp_memory_path: Path) -> MemoryManager:
    return MemoryManager(memory_path=tmp_memory_path)


def _make_shot(
    shot_no: int,
    *,
    action: str = "主人搬箱子",
    subtitle: str = "我以为我在搬家",
    duration_s: int = 8,
    emotion_peak: bool = False,
    scene: str = "客厅",
) -> Shot:
    return Shot(
        shot_no=shot_no,
        time_range=f"{sum(range(shot_no))}-{sum(range(shot_no + 1))}s",
        scene=scene,
        camera="固定机位",
        action=action,
        voiceover="",
        subtitle=subtitle,
        duration_s=duration_s,
        emotion_peak=emotion_peak,
        shot_type="other",
    )


def _make_episode(
    ep: int = 1,
    title: str = "📦 搬家日",
    hook_text: str = "客厅尽头那个最大的纸箱, 突然动了一下",
    next_seed: str = "EP02 第一夜, YouKei 不敢上床",
    n_shots: int = 5,
    n_peaks: int = 1,
    shot_action: str = "YouKei 在客厅玩纸箱",
) -> EpisodeScript:
    # EP12 例外: hook=null + next_seed=null
    is_ep12 = ep == 12
    hook_type = None if is_ep12 else HookType.SUSPENSE
    final_hook_text = None if is_ep12 else hook_text
    final_next_seed = None if is_ep12 else next_seed
    shots = [
        _make_shot(shot_no=i + 1, action=shot_action, emotion_peak=(i < n_peaks))
        for i in range(n_shots)
    ]
    return EpisodeScript(
        ep=ep,
        title=title,
        logline=f"EP{ep} 一句话剧情",
        shots=shots,
        hook=HookSpec(type=hook_type, subtype="x", text=final_hook_text),
        satisfaction_types=[SatisfactionType.EMOTION],
        next_episode_seed=final_next_seed,
        rhythm_notes="",
        self_check=SelfCheck(
            shot_count_ok=True,
            duration_in_range=True,
            emotion_peaks_count=n_peaks,
            hook_present=(not is_ep12),
            forbidden_words_check=True,
        ),
    )


# ===== Test: Pydantic Schemas =====
class TestSchemas:
    def test_youkei_state_defaults(self):
        s = YoukeiState()
        assert s.position == "客厅"
        assert s.age_months == 7.0
        assert s.learned_skills == []

    def test_youkei_state_age_bounds(self):
        with pytest.raises(ValidationError):  # ValidationError
            YoukeiState(age_months=-1)
        with pytest.raises(ValidationError):
            YoukeiState(age_months=30)

    def test_episode_memory_required_fields(self):
        em = EpisodeMemory(ep=1, title="test", stage="起势段")
        assert em.ep == 1
        assert em.stage == "起势段"
        assert em.hook_delivered == ""

    def test_episode_memory_extra_forbidden(self):
        with pytest.raises(ValidationError):
            EpisodeMemory.model_validate(
                {"ep": 1, "title": "test", "stage": "起势段", "unknown": "x"},
            )

    def test_memory_bank_extra_ignored(self):
        """MemoryBank extra='ignore' (允许备份加额外元数据)"""
        mb = MemoryBank.model_validate(
            {"season_id": 1, "future_field": "future"},
        )
        assert mb.season_id == 1


# ===== Test: 加载/初始化 =====
class TestLoad:
    def test_load_nonexistent_returns_empty(self, tmp_memory_path):
        mm = MemoryManager(memory_path=tmp_memory_path)
        assert mm.memory.episodes == []
        assert mm.memory.season_id == 1

    def test_load_corrupted_returns_empty(self, tmp_memory_path):
        tmp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_memory_path.write_text("not json{", encoding="utf-8")
        mm = MemoryManager(memory_path=tmp_memory_path)
        assert mm.memory.episodes == []

    def test_load_existing(self, tmp_memory_path):
        tmp_memory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_memory_path.write_text(
            json.dumps(
                {
                    "season_id": 1,
                    "last_updated": "2026-07-12T00:00:00",
                    "youkei_age_months_start": 7.0,
                    "episodes": [
                        {
                            "ep": 1,
                            "title": "📦 搬家日",
                            "stage": "起势段",
                            "key_facts": ["YouKei 钻入纸箱"],
                            "locations_used": ["room_living"],
                            "time_markers": ["20:00"],
                            "youkei_state": {
                                "position": "客厅",
                                "emotion": "curious",
                                "learned_skills": [],
                                "age_months": 7.0,
                            },
                            "hook_delivered": "",
                            "hook_seed_for_next": "EP02 第一夜",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        mm = MemoryManager(memory_path=tmp_memory_path)
        assert len(mm.memory.episodes) == 1
        assert mm.get_episode(1) is not None
        assert mm.get_episode(1).title == "📦 搬家日"


# ===== Test: 写入接口 =====
class TestAddEpisode:
    def test_add_ep01(self, mm):
        ep1 = _make_episode(ep=1)
        entry = mm.add_episode(
            ep1,
            key_facts=["YouKei 钻入最大纸箱"],
            locations_used=["room_living"],
            time_markers=["20:00"],
        )
        assert entry.ep == 1
        assert entry.title == "📦 搬家日"
        assert entry.key_facts == ["YouKei 钻入最大纸箱"]
        assert len(mm.memory.episodes) == 1

    def test_add_ep01_then_ep02(self, mm):
        ep1 = _make_episode(ep=1)
        ep2 = _make_episode(ep=2, title="🌙 第一夜")
        mm.add_episode(ep1, key_facts=["x"])
        mm.add_episode(ep2, key_facts=["y"])
        assert len(mm.memory.episodes) == 2
        assert mm.get_episode(1).title == "📦 搬家日"
        assert mm.get_episode(2).title == "🌙 第一夜"

    def test_add_ep_duplicate_overwrites(self, mm, caplog):
        ep1 = _make_episode(ep=1, title="EP01 v1")
        mm.add_episode(ep1)
        ep1_v2 = _make_episode(ep=1, title="EP01 v2")
        mm.add_episode(ep1_v2)
        assert len(mm.memory.episodes) == 1
        assert mm.get_episode(1).title == "EP01 v2"

    def test_add_ep_auto_stage(self, mm):
        """stage 按 ep 推: 1-3 起势段, 4-6 攀升段, 7-9 风暴段, 10-12 决战段"""
        for ep in [1, 3, 4, 6, 7, 9, 10, 12]:
            mm.add_episode(_make_episode(ep=ep, title=f"EP{ep}"), key_facts=[])
        assert mm.get_episode(1).stage == "起势段"
        assert mm.get_episode(3).stage == "起势段"
        assert mm.get_episode(4).stage == "攀升段"
        assert mm.get_episode(6).stage == "攀升段"
        assert mm.get_episode(7).stage == "风暴段"
        assert mm.get_episode(9).stage == "风暴段"
        assert mm.get_episode(10).stage == "决战段"
        assert mm.get_episode(12).stage == "决战段"

    def test_add_ep_auto_youkei_age_increments(self, mm):
        """每过一集, 猫月龄 +0.03 (1 个月 ≈ 30 天, 一周约 0.03 月)"""
        mm.add_episode(_make_episode(ep=1), key_facts=[])
        mm.add_episode(_make_episode(ep=2), key_facts=[])
        age_ep1 = mm.get_episode(1).youkei_state.age_months
        age_ep2 = mm.get_episode(2).youkei_state.age_months
        assert abs(age_ep2 - age_ep1 - 0.03) < 0.001


# ===== Test: 查询接口 =====
class TestQuery:
    def test_get_episode_returns_none_if_missing(self, mm):
        assert mm.get_episode(99) is None

    def test_get_prev_episode(self, mm):
        mm.add_episode(_make_episode(ep=1, title="EP01"), key_facts=[])
        mm.add_episode(_make_episode(ep=2, title="EP02"), key_facts=[])
        assert mm.get_prev_episode(2).title == "EP01"
        assert mm.get_prev_episode(1) is None  # EP01 无 prev


# ===== Test: save/load 往返 =====
class TestSaveLoad:
    def test_save_creates_file(self, mm, tmp_memory_path):
        mm.add_episode(_make_episode(ep=1), key_facts=["x"])
        mm.save()
        assert tmp_memory_path.exists()

    def test_save_atomic_uses_tempfile(self, mm, tmp_memory_path):
        """save() 用 tempfile + rename, 中途失败不污染目标文件"""
        mm.add_episode(_make_episode(ep=1), key_facts=["x"])
        mm.save()
        # 验证 last_updated 自动填
        data = json.loads(tmp_memory_path.read_text(encoding="utf-8"))
        assert data["last_updated"] != ""
        assert "T" in data["last_updated"]  # ISO 8601

    def test_load_after_save(self, tmp_memory_path):
        """写盘 → 重新构造 → 数据一致"""
        mm1 = MemoryManager(memory_path=tmp_memory_path)
        mm1.add_episode(
            _make_episode(ep=1, title="EP01 持久化"),
            key_facts=["x"],
            locations_used=["room_living"],
        )
        mm1.save()

        mm2 = MemoryManager(memory_path=tmp_memory_path)
        assert len(mm2.memory.episodes) == 1
        assert mm2.get_episode(1).title == "EP01 持久化"
        assert mm2.get_episode(1).key_facts == ["x"]

    def test_save_sets_last_updated(self, mm, tmp_memory_path):
        mm.save()
        data = json.loads(tmp_memory_path.read_text(encoding="utf-8"))
        assert "last_updated" in data
        assert data["last_updated"].count("T") == 1  # ISO 8601 含 T


# ===== Test: 跨集硬约束 hard_check =====
class TestHardCheck:
    def test_first_ep_no_prev_no_errors(self, mm):
        """EP01 无 prev, 默认通过 (除了末钩必设)"""
        ep1 = _make_episode(ep=1, next_seed="EP02 第一夜, YouKei 不敢上床")
        is_valid, errors, _warnings = mm.hard_check(ep1)
        assert is_valid is True
        assert errors == []

    def test_EP02_prev_hook_recovered(self, mm):
        mm.add_episode(
            _make_episode(ep=1, next_seed="EP02 第一夜, YouKei 不敢上床"),
            key_facts=[],
        )
        # EP02 文本含 "第一夜" / "YouKei 不敢" 关键词
        ep2 = _make_episode(
            ep=2,
            shot_action="第一夜里, YouKei 不敢上床",
        )
        is_valid, errors, _warnings = mm.hard_check(ep2)
        assert is_valid is True
        assert errors == []

    def test_EP02_prev_hook_NOT_recovered(self, mm):
        mm.add_episode(
            _make_episode(ep=1, next_seed="EP02 第一夜, YouKei 不敢上床"),
            key_facts=[],
        )
        # EP02 文本完全不沾边 (避开 "第一夜"/"YouKei"/"不敢上床" 3 关键词)
        ep2 = _make_episode(
            ep=2,
            title="阳台征服",
            hook_text="阳台顶上的花盆被风吹动",
            next_seed="EP03 厨房事变",
            shot_action="阳台征服场景",
        )
        is_valid, errors, _warnings = mm.hard_check(ep2)
        assert is_valid is False
        assert any("prev_hook_not_recovered" in e for e in errors)

    def test_missing_final_hook(self, mm):
        """非 EP12 缺 next_episode_seed → error"""
        ep5 = _make_episode(ep=5, next_seed="")
        is_valid, errors, _warnings = mm.hard_check(ep5)
        assert is_valid is False
        assert any("missing_final_hook" in e for e in errors)

    def test_EP12_no_hook_allowed(self, mm):
        """EP12 允许 next_episode_seed 为空"""
        ep12 = _make_episode(ep=12)
        is_valid, errors, _warnings = mm.hard_check(ep12)
        assert is_valid is True
        assert errors == []


# ===== Test: 钩子回收关键词提取 =====
class TestHookKeywords:
    def test_extract_keywords_basic(self, mm):
        kws = mm._extract_keywords("EP02 第一夜, YouKei 不敢上床")
        # regex 是连续汉字不分词, 所以 "第一夜" / "YouKei" / "不敢上床" 是整体
        assert "第一夜" in kws
        assert "YouKei" in kws
        assert "不敢上床" in kws

    def test_extract_keywords_filters_short(self, mm):
        """< 3 字符的词过滤掉"""
        kws = mm._extract_keywords("EP2 上")
        assert all(len(k) >= 3 for k in kws)

    def test_extract_keywords_limits_to_3(self, mm):
        kws = mm._extract_keywords("abcdef ghijkl mnopqr stuvwx yz1234")
        assert len(kws) <= 3


# ===== Test: 工厂 =====
class TestFactory:
    def test_make_default_manager(self, tmp_path, monkeypatch):
        """make_default_manager 使用默认路径"""
        # 用 monkeypatch 改 cwd 让默认路径在 tmp
        monkeypatch.chdir(tmp_path)
        mm = make_default_manager()
        assert str(mm.memory_path).endswith("data/state/memory_bank.json")
        assert mm.memory_path.is_absolute()
