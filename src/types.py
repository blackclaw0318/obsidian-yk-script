"""
types.py — 跨模块共享类型 (Pydantic v2 models)

定义:
- Shot: 单个镜头
- EpisodeScript: 一集剧本 (Writer L1 输出)
- CriticVerdict: Critic L2 评审结果
- HardCheckResult: L3 硬约束校验结果
- LLMError: LLM 调用错误基类

设计原则:
- 严格 schema (extra='forbid', 拒绝未知字段)
- 类型优先于字典 (IDE 友好 + mypy strict)
- 跟 prompts/*.yaml 中的输出 schema 字面一致
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ===== 枚举 (与 season-01.json 对齐) =====
class HookType(str, Enum):
    """5 类钩子 (跟 hook_distribution.json 一致)"""

    EMOTION = "情绪钩"
    SUSPENSE = "悬念钩"
    TWIST = "反转钩"
    INFO = "信息钩"
    CRISIS = "危机钩"


class SatisfactionType(str, Enum):
    """5 类爽点 (跟 satisfaction_matrix.json 一致)"""

    EMOTION = "情感爆发"
    REVEAL = "悬念揭秘"
    REVENGE = "打脸复仇"
    COMEBACK = "逆袭翻盘"
    STATUS = "身份碾压"


class Stage(str, Enum):
    """4 阶段 (跟 season-XX.json stage_distribution 一致)"""

    RISE = "起势段"
    CLIMB = "攀升段"
    STORM = "风暴段"
    FINALE = "决战段"


class Intensity(str, Enum):
    """爽点强度 (5 档)"""

    ONE = "★"
    TWO = "★★"
    THREE = "★★★"
    FOUR = "★★★★"
    FIVE = "★★★★★"


class Verdict(str, Enum):
    """Critic 评审结论"""

    EXCELLENT = "EXCELLENT"
    PASS = "PASS"
    FAIL = "FAIL"


class CheckSeverity(str, Enum):
    """硬约束严重等级"""

    FAIL = "FAIL"
    HARD_FAIL = "HARD_FAIL"  # 一票否决


# ===== L1 输出: Shot / EpisodeScript =====
class Shot(BaseModel):
    """单个镜头"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 额外字段不拒 (例 shot_dialogue_quote)

    shot_no: int = Field(ge=1, le=20, description="镜头序号")
    time_range: str = Field(description='时长区间, 例 "0-3s"')
    scene: str = Field(description="场景 ID 或描述")
    camera: str = Field(description='机位, 例 "固定机位" / "跟拍"')
    action: str = Field(description="动作描述")
    voiceover: str = Field(default="", description="画外音 (可选)")
    subtitle: str = Field(description="字幕 (≤12 字)")
    duration_s: int = Field(ge=1, le=30, description="镜头时长(秒)")
    emotion_peak: bool = Field(default=False, description="是否情绪波峰")
    shot_type: str = Field(
        default="other",
        description=(
            "镜头类型 (机位 或 Save the Cat beats 名)"
            " P9 fix: 改为 str, LLM 会创造 beats 名 (opening/catalyst/conflict_escalation/cute_moment/ending_hook 等), "
            "Literal 枚举无法覆盖, hard_check 阶段再验证"
        ),
    )


class HookSpec(BaseModel):
    """钩子规格"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 加 placement/next_seed_hint, 不拒

    type: HookType | None = Field(description="5 类钩子之一, EP12 可为 null")
    subtype: str | None = Field(description="子类")
    text: str | None = Field(description="钩子文本模板")


class SelfCheck(BaseModel):
    """Writer 自检 5 项"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 额外字段不拒 (例 human_red_line_check)

    shot_count_ok: bool
    duration_in_range: bool
    emotion_peaks_count: int = Field(ge=0, le=5)
    hook_present: bool
    forbidden_words_check: bool


class EpisodeScript(BaseModel):
    """Writer L1 输出: 一集完整剧本"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 额外字段不拒 (例 satisfaction_intensity, compliance_notes)

    ep: int = Field(ge=1, le=12, description="集号")
    title: str = Field(description="集标题")
    logline: str = Field(max_length=50, description="一句话剧情 (≤30 字)")
    duration_target_s: int | None = Field(
        default=None,
        ge=30,
        le=90,
        description="目标时长(秒); None 时由 model_validator 从 shots 计算并填入",
    )
    shots: list[Shot] = Field(min_length=3, max_length=8, description="3-8 个镜头")
    hook: HookSpec
    satisfaction_types: list[str] = Field(
        min_length=1,
        max_length=3,
        description=(
            "爽点类型 (1-3 个)"
            " P9 fix: 改为 list[str], LLM 会加 '冷幽默反转' '反差萌' 等不在 5 选枚举里的类型"
            " 5 选是参考 (情感爆发/悬念揭秘/打脸复仇/逆袭翻盘/身份碾压), 不强制"
        ),
    )
    next_episode_seed: str | None = Field(description="留给下一集的钩子")
    rhythm_notes: str = Field(default="", description="节奏提示")
    self_check: SelfCheck

    @model_validator(mode="after")
    def validate_total_duration(self) -> EpisodeScript:
        """总时长 = shots.duration_s 之和, 应在 30-90s 范围内 (无 ±5s 容差)。

        - 若调用方未传 duration_target_s (None), 则从 shots 自动计算并填入
        - 若已传, 必须等于 shots 之和 (避免字段不一致)
        - 错误消息固定包含 "总时长" 字样, 方便上层日志聚合
        """
        total = sum(s.duration_s for s in self.shots)
        if not 30 <= total <= 90:
            raise ValueError(
                f"总时长 {total}s 不在 30-90s 范围内 (3-8 镜头 × 1-30 秒)",  # noqa: RUF001
            )
        # P9 fix: ±2s 容差 — LLM 算 60s 但 shots 总和可能 57-63s, 容忍即可, 不应严卡
        if self.duration_target_s is not None and abs(self.duration_target_s - total) > 2:
            raise ValueError(
                f"duration_target_s={self.duration_target_s} 与 shots 总时长 {total}s 不一致 (容差 ±2s)",
            )
        # 自动填字段, 保持向后兼容 (旧代码 .duration_target_s 仍可读)
        self.duration_target_s = total
        return self

    @model_validator(mode="after")
    def validate_emotion_peaks(self) -> EpisodeScript:
        """情绪波峰数 ≥ 1"""
        peak_count = sum(1 for s in self.shots if s.emotion_peak)
        if peak_count != self.self_check.emotion_peaks_count:
            raise ValueError(
                f"emotion_peak 实际={peak_count}, self_check 报告="
                f"{self.self_check.emotion_peaks_count}",
            )
        if peak_count < 1:
            raise ValueError(f"情绪波峰数 = {peak_count}, 应 ≥ 1")
        return self

    @model_validator(mode="after")
    def validate_ep12_no_hook(self) -> EpisodeScript:
        """EP12 允许 hook=null, 其他集必须有 hook.type"""
        if self.ep == 12 and self.hook.type is not None:
            raise ValueError("EP12 必须 hook.type=null (季末温馨集)")
        if self.ep != 12 and self.hook.type is None:
            raise ValueError(f"EP{self.ep} 不允许 hook=null (EP12 例外)")
        return self

    @property
    def total_duration_s(self) -> int:
        return sum(s.duration_s for s in self.shots)

    @property
    def peak_positions(self) -> list[float]:
        """情绪波峰位置百分比"""
        total = self.total_duration_s
        return [
            (sum(s.duration_s for s in self.shots[:i]) + s.duration_s / 2) / total * 100
            for i, s in enumerate(self.shots)
            if s.emotion_peak
        ]


# ===== L2 输出: CriticVerdict =====
class PerspectiveScore(BaseModel):
    """单个视角评分"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 会加额外字段, 不拒

    id: Literal["humor", "disguise", "continuity", "rhythm", "red_line"]  # 2026-07-18: cuteness → disguise (伪装喜剧适配)
    score: int = Field(ge=0, le=5, description="0-5 分")
    reason: str = Field(
        max_length=200,  # P9 fix: 100 太短, LLM 实际写 140+ 字符, 200 足够
        description="评审理由",
    )
    improvement: str = Field(default="", max_length=100, description="改进建议")  # P9 fix: 50 太短


class CriticVerdict(BaseModel):
    """Critic L2 输出: 评审结论"""

    model_config = ConfigDict(extra="ignore")  # P9 fix: LLM 会加 feedback_extra/notes 等, 不拒

    episode_id: int = Field(ge=1, le=12)
    perspectives: list[PerspectiveScore] = Field(min_length=5, max_length=5)
    total_score: int = Field(ge=0, le=50)
    verdict: Verdict
    feedback: str = Field(max_length=800)  # 2026-07-18: 200→800 (LLM 实际 300-500 字, 200 严了)
    should_rewrite: bool
    improvement_suggestion: str | None = Field(default=None, max_length=400)  # 2026-07-18 新增: FAIL 时详细改进建议

    @model_validator(mode="after")
    def validate_score_aggregation(self) -> CriticVerdict:
        """总分必须符合聚合公式: sum(score * weight / 5)

        P9 fix: LLM 评分总有偏差 (±3), 阈值严格会误伤:
          - 偏差 ≤3 → 静默覆盖 total_score 为聚合值
          - 偏差 >3  → 报 ValueError (说明 LLM 没理解公式, 严重异常)
        """
        weights = {
            "humor": 15,
            "disguise": 15,  # 2026-07-18: cuteness → disguise
            "continuity": 10,
            "rhythm": 5,
            "red_line": 5,
        }
        expected = sum(p.score * weights[p.id] // 5 for p in self.perspectives)
        diff = abs(expected - self.total_score)
        if diff > 3:
            raise ValueError(
                f"total_score={self.total_score} 偏离聚合值 {expected} 超过 ±3 (LLM 公式理解有严重问题)",
            )
        # P9 fix: 偏差 ≤3 → 静默修正为聚合值, 下游 verdict_thresholds 跟它走
        self.total_score = expected
        return self

    @model_validator(mode="after")
    def validate_verdict_thresholds(self) -> CriticVerdict:
        """verdict 必须跟 total_score 一致

        P9 fix: LLM 经常弄错阈值 (例如 35 分给 PASS), 自动覆盖 verdict 为正确值
        """
        if self.total_score >= 45:
            self.verdict = Verdict.EXCELLENT
        elif self.total_score >= 38:
            self.verdict = Verdict.PASS
        else:
            self.verdict = Verdict.FAIL
        return self

    @model_validator(mode="after")
    def validate_should_rewrite_consistency(self) -> CriticVerdict:
        """should_rewrite = (verdict == FAIL)

        P9 fix: 同 verdict_thresholds, 静默覆盖不一致值
        """
        self.should_rewrite = (self.verdict == Verdict.FAIL)
        return self


# ===== L3 输出: HardCheckResult =====
class Violation(BaseModel):
    """单条违规"""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    severity: CheckSeverity
    shot_no: int | None = None
    evidence: str = Field(description="违规证据")
    fix_suggestion: str = Field(default="")


class HardCheckResult(BaseModel):
    """L3 硬约束校验结果"""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["PASS", "FAIL"]
    violations: list[Violation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    passed_constraints: int = Field(ge=0)
    total_constraints: int = Field(ge=0)
    should_publish: bool

    @model_validator(mode="after")
    def validate_should_publish(self) -> HardCheckResult:
        """should_publish = (violations 为空)"""
        expected = len(self.violations) == 0
        if self.should_publish != expected:
            raise ValueError(
                f"should_publish={self.should_publish} 应等于 无违规? {expected}",
            )
        return self


# ===== 异常类 =====
class LLMError(Exception):
    """LLM 调用错误基类"""

    def __init__(self, message: str, status_code: int | None = None, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ZeroLengthResponseError(LLMError):
    """LLM 返回 0 字符响应 (v0.40 fix: 必须硬校验抛错)"""

    pass


class InvalidJSONError(LLMError):
    """LLM 返回无法解析的 JSON"""

    pass


# ===== Episode Spec (输入, 来自 season-XX.json) =====
class EpisodeSpec(BaseModel):
    """单集规格 (来自 season-XX.json episodes[N])"""

    model_config = ConfigDict(extra="ignore")  # season JSON 可能有额外字段

    ep: int = Field(ge=1, le=12)
    title: str
    stage: Stage
    stage_position_pct: int = Field(ge=0, le=100)
    scene: str
    core_conflict: str
    logline: str
    hook_type: HookType | None = None
    hook_subtype: str | None = None
    hook_text_template: str | None = None
    satisfaction_types: list[SatisfactionType] = Field(default_factory=list)
    satisfaction_intensity: Intensity = Intensity.THREE
    key_moments: list[str] = Field(default_factory=list)
    rhythm_notes: str = ""
    next_episode_seed: str | None = None

    @field_validator("key_moments", mode="before")
    @classmethod
    def _parse_key_moments(cls, v: Any) -> list[str]:
        """season JSON 中 key_moments 是 list[str]"""
        if isinstance(v, list):
            return [str(item) for item in v]
        return []


# ===== 工厂函数 =====
def make_episode_spec_from_json(data: dict[str, Any]) -> EpisodeSpec:
    """从 season-XX.json 单集 dict 构建 EpisodeSpec"""
    return EpisodeSpec.model_validate(data)


def make_episode_script_from_json(data: dict[str, Any]) -> EpisodeScript:
    """从 LLM 响应 JSON 构建 EpisodeScript"""
    return EpisodeScript.model_validate(data)
