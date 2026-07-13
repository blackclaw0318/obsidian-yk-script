"""
test_types.py — Pydantic schemas 单测门控

验证:
- Shot / EpisodeScript / CriticVerdict / HardCheckResult / EpisodeSpec
- 校验器 (model_validator) 触发异常
- 枚举值与 prompts/*.yaml 对齐
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.types import (
    CriticVerdict,
    EpisodeScript,
    EpisodeSpec,
    HardCheckResult,
    HookSpec,
    HookType,
    Intensity,
    LLMError,
    PerspectiveScore,
    SatisfactionType,
    SelfCheck,
    Shot,
    Stage,
    Verdict,
    Violation,
    ZeroLengthResponseError,
)


# ===== Helpers =====
def make_shot(
    *,
    shot_no: int = 1,
    duration_s: int = 5,
    emotion_peak: bool = False,
    shot_type: str = "other",
) -> Shot:
    return Shot(
        shot_no=shot_no,
        time_range=f"{sum(range(shot_no))}-{sum(range(shot_no + 1))}s",
        scene="客厅",
        camera="固定机位",
        action="主人搬箱子,猫钻入",
        voiceover="我以为我在搬家",
        subtitle="我以为我在搬家",
        duration_s=duration_s,
        emotion_peak=emotion_peak,
        shot_type=shot_type,  # type: ignore[arg-type]
    )


def make_episode(
    *,
    ep: int = 1,
    n_shots: int = 5,
    shot_duration: int = 8,
    hook_type: HookType | None = HookType.SUSPENSE,
    n_peaks: int = 1,
    title: str = "📦 搬家日",
    pass_duration_target: bool = True,
    duration_target_s_override: int | None = None,
) -> EpisodeScript:
    """构造合法的 EpisodeScript

    Args:
        pass_duration_target: 是否显式传 duration_target_s。
            True (默认) → 传 shots 之和, 用于验证 model_validator 一致性检查。
            False → 不传, 让 model_validator 自动计算 + 触发 "总时长" 越界错误 (用于 _too_short/_too_long 测试)。
        duration_target_s_override: 显式指定 duration_target_s (默认 None)。
            - None → 跟 pass_duration_target 走 (要么传 total, 要么不传)
            - 整数 → 强制传指定值 (用于 P9 ±2s 容差测试)
    """
    total_dur = shot_duration * n_shots
    shots = [
        make_shot(
            shot_no=i + 1,
            duration_s=shot_duration,
            emotion_peak=(i < n_peaks),
        )
        for i in range(n_shots)
    ]
    kwargs: dict = {
        "ep": ep,
        "title": title,
        "logline": "搬家日, 60 平里全是纸箱, 猫钻进最大纸箱",
        "shots": shots,
        "hook": HookSpec(
            type=hook_type, subtype="来者悬念", text="客厅尽头那个最大的纸箱, 突然动了一下"
        ),
        "satisfaction_types": [SatisfactionType.EMOTION],
        "next_episode_seed": "EP02 第一夜, YouKei 不敢上床",
        "rhythm_notes": "前 5s 必现冲突",
        "self_check": SelfCheck(
            shot_count_ok=True,
            duration_in_range=True,
            emotion_peaks_count=n_peaks,
            hook_present=(hook_type is not None),
            forbidden_words_check=True,
        ),
    }
    if duration_target_s_override is not None:
        kwargs["duration_target_s"] = duration_target_s_override
    elif pass_duration_target:
        kwargs["duration_target_s"] = total_dur
    return EpisodeScript(**kwargs)


def make_critic_verdict(
    *,
    episode_id: int = 1,
    scores: dict[str, int] | None = None,
    verdict: Verdict = Verdict.PASS,
) -> CriticVerdict:
    """构造合法的 CriticVerdict"""
    if scores is None:
        scores = {"humor": 4, "cuteness": 4, "continuity": 4, "rhythm": 4, "red_line": 5}
    weights = {"humor": 15, "cuteness": 15, "continuity": 10, "rhythm": 5, "red_line": 5}
    total = sum(scores[k] * weights[k] // 5 for k in scores)
    perspectives = [
        PerspectiveScore(id=k, score=scores[k], reason=f"{k} 评审理由", improvement="建议改进")
        for k in ("humor", "cuteness", "continuity", "rhythm", "red_line")
    ]
    return CriticVerdict(
        episode_id=episode_id,
        perspectives=perspectives,
        total_score=total,
        verdict=verdict,
        feedback="综合反馈",
        should_rewrite=(verdict == Verdict.FAIL),
    )


# ===== Test: Shot =====
class TestShot:
    def test_minimal_valid_shot(self):
        s = make_shot()
        assert s.shot_no == 1
        assert s.shot_type == "other"

    def test_shot_no_bounds(self):
        with pytest.raises(ValidationError):
            make_shot(shot_no=0)  # ge=1
        with pytest.raises(ValidationError):
            make_shot(shot_no=21)  # le=20

    def test_shot_duration_bounds(self):
        with pytest.raises(ValidationError):
            make_shot(duration_s=0)
        with pytest.raises(ValidationError):
            make_shot(duration_s=31)

    def test_shot_extra_field_forbidden(self):
        # P9 fix: Shot 改为 extra="ignore" (LLM 输出宽容, LLM 会有 shot_dialogue_quote 等额外字段)
        # 旧测试期望 ValidationError, 现期望静默忽略
        shot = Shot(
            shot_no=1,
            time_range="0-3s",
            scene="x",
            camera="x",
            action="x",
            subtitle="x",
            duration_s=3,
            unknown_field="bad",  # type: ignore[call-arg]
        )
        assert shot.shot_no == 1
        assert not hasattr(shot, "unknown_field")  # extra 字段被忽略

    def test_shot_type_enum(self):
        for st in (
            "establishing",
            "dialogue",
            "reaction",
            "insert",
            "transition",
            "finale",
            "other",
        ):
            s = make_shot(shot_type=st)
            assert s.shot_type == st


# ===== Test: EpisodeScript =====
class TestEpisodeScript:
    def test_valid_5_shot_episode(self):
        ep = make_episode()
        assert ep.ep == 1
        assert len(ep.shots) == 5
        assert ep.total_duration_s == 40

    def test_peak_positions(self):
        ep = make_episode(n_shots=4, shot_duration=10, n_peaks=1)
        # shots 0 情绪波峰, 位置 = (0 + 5) / 40 = 12.5%
        assert len(ep.peak_positions) == 1
        assert abs(ep.peak_positions[0] - 12.5) < 0.01

    def test_min_shots_required(self):
        with pytest.raises(ValidationError):
            make_episode(n_shots=2)  # min_length=3

    def test_max_shots_required(self):
        with pytest.raises(ValidationError):
            make_episode(n_shots=9)  # max_length=8

    def test_total_duration_too_short(self):
        with pytest.raises(ValidationError, match="总时长"):
            make_episode(n_shots=3, shot_duration=5, pass_duration_target=False)  # 15s < 30s

    def test_total_duration_too_long(self):
        with pytest.raises(ValidationError, match="总时长"):
            make_episode(n_shots=8, shot_duration=15, pass_duration_target=False)  # 120s > 90s

    def test_duration_target_within_tolerance_ok(self):
        """P9 fix: duration_target_s 与 shots 总和 ±2s 容差内合法
        (LLM 经常给 60s 但 shots 总和 57-63s, 容忍即可)
        """
        # 5 shots × 8s = 40s, 传 42s (差 2s) → OK
        ep = make_episode(n_shots=5, shot_duration=8, duration_target_s_override=42)
        assert ep.total_duration_s == 40
        assert ep.duration_target_s == 40  # 自动修正为聚合值

    def test_duration_target_out_of_tolerance_rejected(self):
        """duration_target_s 与 shots 总和 > 2s 偏离仍应拒"""
        with pytest.raises(ValidationError, match="不一致"):
            make_episode(n_shots=5, shot_duration=8, duration_target_s_override=50)  # 差 10s

    def test_duration_target_zero_diff_ok(self):
        """duration_target_s 完全相等 → OK (历史行为)"""
        ep = make_episode(n_shots=5, shot_duration=8, duration_target_s_override=40)
        assert ep.duration_target_s == 40

    def test_emotion_peaks_mismatch(self):
        """emotion_peak 实际数 ≠ self_check.emotion_peaks_count → 异常"""
        # 构造不一致的场景: 5 个 shot, 总时长 40s 合法,
        # 但 self_check.emotion_peaks_count=3 而实际只 1 个波峰
        ep_dict = {
            "ep": 1,
            "title": "test",
            "logline": "test",
            "duration_target_s": 40,
            "shots": [
                make_shot(shot_no=1, duration_s=8, emotion_peak=True).model_dump(),
                make_shot(shot_no=2, duration_s=8, emotion_peak=False).model_dump(),
                make_shot(shot_no=3, duration_s=8, emotion_peak=False).model_dump(),
                make_shot(shot_no=4, duration_s=8, emotion_peak=False).model_dump(),
                make_shot(shot_no=5, duration_s=8, emotion_peak=False).model_dump(),
            ],
            "hook": {"type": "悬念钩", "subtype": "x", "text": "x"},
            "satisfaction_types": ["情感爆发"],
            "next_episode_seed": "x",
            "rhythm_notes": "x",
            "self_check": {
                "shot_count_ok": True,
                "duration_in_range": True,
                "emotion_peaks_count": 3,  # 实际只 1 个波峰
                "hook_present": True,
                "forbidden_words_check": True,
            },
        }
        with pytest.raises(ValidationError, match="emotion_peak"):
            EpisodeScript.model_validate(ep_dict)

    def test_no_emotion_peak(self):
        """情绪波峰数 = 0 → 异常"""
        with pytest.raises(ValidationError, match="情绪波峰"):
            make_episode(n_peaks=0)

    def test_EP12_must_have_null_hook(self):
        """EP12 hook.type 必须为 None"""
        with pytest.raises(ValidationError, match="EP12 必须 hook.type=null"):
            make_episode(ep=12, hook_type=HookType.EMOTION)

    def test_non_EP12_must_have_hook(self):
        """非 EP12 hook.type 不能为 None"""
        with pytest.raises(ValidationError, match="不允许 hook=null"):
            make_episode(ep=1, hook_type=None)

    def test_EP12_can_have_null_hook(self):
        ep = make_episode(ep=12, hook_type=None, n_peaks=3, n_shots=6, shot_duration=12)
        assert ep.hook.type is None
        assert ep.total_duration_s == 72

    def test_logline_max_length(self):
        # model_copy(update=...) 不重校验, 必须走 model_validate 触发 Field
        with pytest.raises(ValidationError):
            EpisodeScript.model_validate(
                make_episode().model_dump() | {"logline": "x" * 100},
            )


# ===== Test: CriticVerdict =====
class TestCriticVerdict:
    def test_valid_pass_verdict(self):
        cv = make_critic_verdict()
        assert cv.total_score == 4 * 15 // 5 + 4 * 15 // 5 + 4 * 10 // 5 + 4 * 5 // 5 + 5 * 5 // 5
        # = 12 + 12 + 8 + 4 + 5 = 41
        assert cv.total_score == 41
        assert cv.verdict == Verdict.PASS

    def test_excellent_thresholds(self):
        cv = make_critic_verdict(
            scores={
                "humor": 5,
                "cuteness": 5,
                "continuity": 5,
                "rhythm": 5,
                "red_line": 5,
            },
            verdict=Verdict.EXCELLENT,
        )
        assert cv.total_score == 50
        assert cv.verdict == Verdict.EXCELLENT

    def test_fail_thresholds(self):
        cv = make_critic_verdict(
            scores={
                "humor": 2,
                "cuteness": 2,
                "continuity": 2,
                "rhythm": 3,
                "red_line": 5,
            },
            verdict=Verdict.FAIL,
        )
        # 2*3 + 2*3 + 2*2 + 3*1 + 5*1 = 6+6+4+3+5 = 24
        assert cv.total_score == 24
        assert cv.verdict == Verdict.FAIL

    def test_score_aggregation_mismatch(self):
        """total_score 与聚合公式不一致超过 ±3 → 异常 (LLM 公式理解有严重问题)"""
        perspectives = [
            PerspectiveScore(id=k, score=4, reason="x", improvement="x")
            for k in ("humor", "cuteness", "continuity", "rhythm", "red_line")
        ]
        # 聚合值 = 12+12+8+4+4 = 40; total_score=45 偏差 5 → 超 ±3 应拒
        with pytest.raises(ValidationError, match="超过"):
            CriticVerdict(
                episode_id=1,
                perspectives=perspectives,
                total_score=45,  # 偏差 5, 超过 ±3
                verdict=Verdict.PASS,
                feedback="x",
                should_rewrite=False,
            )

    def test_score_aggregation_within_tolerance_silently_corrected(self):
        """P9 fix: total_score 偏差 ≤3 → 静默覆盖为聚合值 (LLM 正常偏差范围)"""
        perspectives = [
            PerspectiveScore(id=k, score=4, reason="x", improvement="x")
            for k in ("humor", "cuteness", "continuity", "rhythm", "red_line")
        ]
        # 聚合值 = 40; total_score=43 偏差 3 → 静默修正为 40
        cv = CriticVerdict(
            episode_id=1,
            perspectives=perspectives,
            total_score=43,
            verdict=Verdict.PASS,
            feedback="x",
            should_rewrite=False,
        )
        assert cv.total_score == 40, "偏差 ≤3 应被静默修正为聚合值"

    def test_verdict_thresholds_mismatch(self):
        """verdict 与 total_score 不一致 → 自动覆盖 (P9 fix)
        历史: 原本抛异常, 但 LLM 经常 (35 分 → PASS), 静默覆盖更鲁棒
        """
        # total=41 但 verdict=FAIL (实际应为 PASS) → 自动覆盖为 PASS
        cv = make_critic_verdict(verdict=Verdict.FAIL)
        assert cv.verdict == Verdict.PASS, "verdict 应被自动覆盖为 PASS"
        assert cv.should_rewrite is False, "PASS 时 should_rewrite 应为 False"

    def test_should_rewrite_mismatch(self):
        """P9 fix: should_rewrite 不一致 → 静默覆盖为 verdict==FAIL
        历史: 原本 raise ValueError, 但 LLM 经常 (PASS 但 should_rewrite=True), 静默覆盖更鲁棒
        """
        cv_dict = {
            "episode_id": 1,
            "perspectives": [
                {"id": k, "score": 4, "reason": "x", "improvement": "x"}
                for k in ("humor", "cuteness", "continuity", "rhythm", "red_line")
            ],
            "total_score": 41,
            "verdict": "PASS",
            "feedback": "x",
            "should_rewrite": True,  # 错误: PASS 时应为 False
        }
        cv = CriticVerdict.model_validate(cv_dict)
        assert cv.verdict == Verdict.PASS
        assert cv.should_rewrite is False, "PASS 时 should_rewrite 应被静默覆盖为 False"

    def test_perspectives_count_must_be_5(self):
        with pytest.raises(ValidationError):
            CriticVerdict(
                episode_id=1,
                perspectives=[
                    PerspectiveScore(id="humor", score=4, reason="x", improvement="x"),
                ],  # 太少
                total_score=12,
                verdict=Verdict.FAIL,
                feedback="x",
                should_rewrite=True,
            )


# ===== Test: HardCheckResult =====
class TestHardCheckResult:
    def test_pass_no_violations(self):
        r = HardCheckResult(
            verdict="PASS",
            violations=[],
            warnings=[],
            passed_constraints=19,
            total_constraints=19,
            should_publish=True,
        )
        assert r.should_publish is True

    def test_violation_sets_should_publish_false(self):
        r = HardCheckResult(
            verdict="FAIL",
            violations=[
                Violation(
                    constraint_id="no_real_face",
                    severity="HARD_FAIL",
                    shot_no=3,
                    evidence="x",
                    fix_suggestion="y",
                )
            ],
            warnings=[],
            passed_constraints=18,
            total_constraints=19,
            should_publish=False,
        )
        assert r.should_publish is False

    def test_should_publish_mismatch(self):
        with pytest.raises(ValidationError, match="should_publish"):
            HardCheckResult(
                verdict="PASS",
                violations=[
                    Violation(
                        constraint_id="x",
                        severity="FAIL",
                        shot_no=None,
                        evidence="x",
                        fix_suggestion="x",
                    )
                ],
                warnings=[],
                passed_constraints=18,
                total_constraints=19,
                should_publish=True,  # 错误: 有违规就不应 publish
            )


# ===== Test: EpisodeSpec =====
class TestEpisodeSpec:
    def test_from_season_json(self):
        data = {
            "ep": 1,
            "title": "📦 搬家日",
            "stage": "起势段",
            "stage_position_pct": 8,
            "scene": "客厅纸箱堆",
            "core_conflict": "YouKei 钻进最大箱子不出来",
            "logline": "搬家日, 60 平里全是纸箱",
            "hook_type": "悬念钩",
            "hook_subtype": "来者悬念",
            "hook_text_template": "客厅尽头那个最大的纸箱, 突然动了一下",
            "satisfaction_types": ["情感爆发"],
            "satisfaction_intensity": "★★★",
            "key_moments": ["0:05 - 主人搬第 3 个箱子", "0:30 - 主人发现猫不见了"],
            "rhythm_notes": "前 5s 必现冲突",
            "next_episode_seed": "EP02 第一夜",
        }
        spec = EpisodeSpec.model_validate(data)
        assert spec.ep == 1
        assert spec.stage == Stage.RISE
        assert spec.hook_type == HookType.SUSPENSE
        assert spec.satisfaction_intensity == Intensity.THREE
        assert len(spec.key_moments) == 2

    def test_ignores_unknown_fields(self):
        """EpisodeSpec 是 extra='ignore' (season JSON 可能含未建模字段)"""
        spec = EpisodeSpec.model_validate(
            {
                "ep": 1,
                "title": "x",
                "stage": "起势段",
                "stage_position_pct": 0,
                "scene": "x",
                "core_conflict": "x",
                "logline": "x",
                "future_field": "future_value",  # 未知字段
            }
        )
        assert spec.ep == 1

    def test_hook_type_null_allowed(self):
        """EP12 hook_type=null 允许"""
        spec = EpisodeSpec.model_validate(
            {
                "ep": 12,
                "title": "🎄 季末冬至",
                "stage": "决战段",
                "stage_position_pct": 100,
                "scene": "客厅+阳台",
                "core_conflict": "(无冲突, 温馨收束)",
                "logline": "冬至包饺子, YouKei 偷面团",
                "hook_type": None,
                "hook_subtype": None,
                "hook_text_template": None,
                "satisfaction_types": ["情感爆发"],
                "satisfaction_intensity": "★★★★★",
            }
        )
        assert spec.hook_type is None


# ===== Test: Exceptions =====
class TestExceptions:
    def test_llm_error(self):
        e = LLMError("test", status_code=500, response_body="x")
        assert e.status_code == 500
        assert "test" in str(e)

    def test_zero_length_response_error(self):
        e = ZeroLengthResponseError("0 字符", status_code=200)
        assert isinstance(e, LLMError)
        assert e.status_code == 200

    def test_enums_align_with_yaml(self):
        """枚举值必须与 prompts/*.yaml 字面一致"""
        # hook_distribution.json
        assert HookType.EMOTION.value == "情绪钩"
        assert HookType.SUSPENSE.value == "悬念钩"
        assert HookType.TWIST.value == "反转钩"
        assert HookType.INFO.value == "信息钩"
        assert HookType.CRISIS.value == "危机钩"

        # satisfaction_matrix.json
        assert SatisfactionType.EMOTION.value == "情感爆发"
        assert SatisfactionType.REVEAL.value == "悬念揭秘"
        assert SatisfactionType.REVENGE.value == "打脸复仇"
        assert SatisfactionType.COMEBACK.value == "逆袭翻盘"
        assert SatisfactionType.STATUS.value == "身份碾压"

        # season-01.json stage_distribution
        assert Stage.RISE.value == "起势段"
        assert Stage.CLIMB.value == "攀升段"
        assert Stage.STORM.value == "风暴段"
        assert Stage.FINALE.value == "决战段"

        # critic_rubric.yaml verdict
        assert Verdict.EXCELLENT.value == "EXCELLENT"
        assert Verdict.PASS.value == "PASS"
        assert Verdict.FAIL.value == "FAIL"
