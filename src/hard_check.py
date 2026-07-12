"""
hard_check.py — Layer 3 Hard Check (硬约束校验)

职责 (v0.3 文档 §3.7):
- 不靠 LLM,纯规则校验 EpisodeScript
- 19 条隐私合规红线 (8 主角 + 6 公寓 + 5 YouKei)
- 5 项结构校验 (shot 数 / 总时长 / 波峰 / hook / next_seed)
- 上集钩子回收 (如果 prev_script)

调用方:
- src/daily.py (cron entry, P5 Writer → P6 Critic → P7 Hard Check → P8 Memory)
- 输出 HardCheckResult: verdict / violations / warnings / should_publish

设计原则:
- 每条约束一个 method,返回 Optional[Violation]
- substring_match 用 kwargs 模式,支持单条或多条 keyword
- severity=HARD_FAIL 任一命中 → verdict=FAIL + should_publish=False
- evidence 标出命中关键词 + 所在字段, 方便 fix_suggestion 自动填充

参考: prompts/memory_constraints.yaml hard_constraints 章节
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.types import EpisodeScript, HardCheckResult, Violation

logger = logging.getLogger(__name__)


# ===== 隐私红线模式 (跟 memory_constraints.yaml privacy_compliance 对齐) =====
# 每条: (constraint_id, severity, keywords, fix_hint)
# keyword 为空列表 → 需 AI 二次判定 (本 MVP 暂不实现,记 warning)

_PROTAGONIST_RULES: list[tuple[str, str, list[str], str]] = [
    (
        "no_real_face",
        "HARD_FAIL",
        ["正脸", "全脸", "45 度侧脸", "正脸微笑"],
        "改为背影/手部/配音露脸后期, 移除正脸相关描述",
    ),
    (
        "no_real_name",
        "HARD_FAIL",
        ["身份证", "工作单位", "公司名", "真名"],
        "全部化名'上坤', 删真实身份字段",
    ),
    (
        "no_address_leak",
        "HARD_FAIL",
        ["楼栋号", "门牌号", "快递单", "街景"],
        "窗户不出镜, 抹去门牌/快递等可识别信息",
    ),
    (
        "no_controversy",
        "HARD_FAIL",
        ["政治", "宗教", "性别对立"],
        "删除争议话题, 专注猫与主人日常",
    ),
    (
        "no_violence",
        "HARD_FAIL",
        ["血腥", "伤口", "暴力"],
        "删除血腥/伤口描写, 用卡通化处理",
    ),
    (
        "no_cat_danger",
        "HARD_FAIL",
        ["爬窗台外侧", "啃电线", "上灶台"],
        "改为室内安全场景, 不拍猫危险动作",
    ),
    (
        "no_advertising",
        "FAIL",
        [],  # AI judge only
        "删除商业植入, 本季不接广告",
    ),
    (
        "no_swear",
        "HARD_FAIL",
        [],  # AI judge (脏话列表难以穷举)
        "字幕/配音避免脏话, 必要时用'哔'消音",
    ),
]


_APARTMENT_RULES: list[tuple[str, str, list[str], str]] = [
    (
        "no_window_view",
        "FAIL",
        ["窗外", "街景", "标志性建筑"],
        "窗户后期遮罩或换空镜",
    ),
    (
        "no_door_number",
        "HARD_FAIL",
        ["门牌号", "楼层", "楼栋号"],
        "删除门牌/楼层/楼栋相关字幕",
    ),
    (
        "no_courier_label",
        "HARD_FAIL",
        ["快递单", "身份证", "银行卡"],
        "删除快递单/身份证/银行卡特写",
    ),
    (
        "no_others_visible",
        "FAIL",
        [],  # 需视频后期校验 (image_meta_check)
        "他人必须打码或侧脸",
    ),
    (
        "no_luxury_show",
        "FAIL",
        [],  # AI judge
        "避免炫富争议, 不强调价格",
    ),
    (
        "no_messy_scene",
        "FAIL",
        ["脏乱", "杂乱"],
        "收拾好再拍, 避免脏乱差",
    ),
]


_YOUKEI_RULES: list[tuple[str, str, list[str], str]] = [
    (
        "no_cat_speaking",
        "HARD_FAIL",
        [],  # AI judge (字幕里完整句子 = 违规)
        "YouKei 用'喵/咔/嘶'字幕, 不开口说话",
    ),
    (
        "no_high_jump",
        "FAIL",
        [],  # 视频后期校验
        "降低跳跃高度, 拍细节",
    ),
    (
        "no_cat_danger_action",
        "HARD_FAIL",
        ["爬窗台外侧", "啃电线", "上灶台"],
        "改拍室内安全动作",
    ),
    (
        "no_cat_superpower",
        "FAIL",
        ["开微波炉", "拧水龙头"],
        "删除超能力表现, 猫符合生理常识",
    ),
    (
        "no_cat_fight",
        "HARD_FAIL",
        [],  # 视频后期校验
        "不拍真打架, 用玩耍代替",
    ),
]


@dataclass
class HardChecker:
    """Layer 3 Hard Check 硬约束校验器

    Args:
        script: 本集 EpisodeScript (Writer L1 输出)
        protagonist_card: data/characters/protagonist.json (for 8 条主角红线)
        youkei_card: data/characters/youkei.json (for 5 条 YouKei 红线)
        apartment_card: data/characters/apartment.json (for 6 条公寓红线)
        prev_script: 上一集 EpisodeScript (None = EP01, 无需回收钩子)

    用法:
        checker = HardChecker(script, prot, you, apt, prev)
        result = checker.run()
        if not result.should_publish:
            send_alert(result.violations)
    """

    script: EpisodeScript
    protagonist_card: dict[str, Any] = field(default_factory=dict)
    youkei_card: dict[str, Any] = field(default_factory=dict)
    apartment_card: dict[str, Any] = field(default_factory=dict)
    prev_script: EpisodeScript | None = None

    # ===== 入口 =====
    def run(self) -> HardCheckResult:
        """执行全部硬约束校验

        Returns:
            HardCheckResult: 任一 HARD_FAIL 命中 → verdict=FAIL + should_publish=False
        """
        violations: list[Violation] = []
        warnings: list[str] = []

        # 19 条隐私红线 (8 + 6 + 5)
        violations.extend(self._check_protag_red_lines())
        violations.extend(self._check_apartment_red_lines())
        violations.extend(self._check_youkei_red_lines())

        # 5 项结构校验
        violations.extend(self._check_structural())

        # 上集钩子回收 (EP01 跳过)
        if self.prev_script is not None:
            violations.extend(self._check_hook_continuity())

        # 统计
        total_constraints = 24  # 19 红线 + 5 结构
        passed = total_constraints - len(violations)
        # 任何 violation (FAIL 或 HARD_FAIL) → verdict=FAIL + should_publish=False
        # severity 仅用于老板人工分优先级 (HARD_FAIL = 整集作废 / FAIL = 需修复后可发)
        verdict = "FAIL" if violations else "PASS"

        # 未实现 AI judge 的规则 → warning (不计入 violations, 但提示老板)
        warnings.extend(self._collect_ai_judge_warnings())

        result = HardCheckResult(
            verdict=verdict,  # type: ignore[arg-type]
            violations=violations,
            warnings=warnings,
            passed_constraints=passed,
            total_constraints=total_constraints,
            should_publish=(verdict == "PASS"),
        )
        logger.info(
            f"EP{self.script.ep} L3: verdict={verdict}, "
            f"violations={len(violations)}, warnings={len(warnings)}",
        )
        return result

    # ===== 文本聚合 =====
    def _collect_text_fields(self) -> str:
        """把 script 所有文本字段拼成单字符串, 用于 substring 检测"""
        parts: list[str] = []
        for shot in self.script.shots:
            parts.extend(
                [
                    shot.action or "",
                    shot.voiceover or "",
                    shot.subtitle or "",
                    shot.scene or "",
                    shot.camera or "",
                ],
            )
        # 也加入 hook.text 和 rhythm_notes
        if self.script.hook.text:
            parts.append(self.script.hook.text)
        if self.script.rhythm_notes:
            parts.append(self.script.rhythm_notes)
        if self.script.next_episode_seed:
            parts.append(self.script.next_episode_seed)
        return "\n".join(parts)

    def _find_violation_shot(
        self,
        keyword: str,
    ) -> tuple[int | None, str]:
        """找到 keyword 出现在哪个 shot + 哪个字段

        Returns:
            (shot_no, field_name); 没找到 → (None, "")
        """
        for shot in self.script.shots:
            for fld in ("action", "voiceover", "subtitle", "scene", "camera"):
                val = getattr(shot, fld, "") or ""
                if keyword in val:
                    return shot.shot_no, fld
        if self.script.hook.text and keyword in self.script.hook.text:
            return None, "hook.text"
        return None, ""

    # ===== 19 条隐私红线 =====
    def _check_rules(
        self,
        rules: list[tuple[str, str, list[str], str]],
        text: str,
    ) -> list[Violation]:
        """通用规则检查: 对每条规则做 substring 匹配

        Args:
            rules: (constraint_id, severity, keywords, fix_hint)
            text: 聚合后的全文

        Returns:
            命中的 violation 列表 (severity FAIL 时也输出, 由 model_validator 决定 publish)
        """
        violations: list[Violation] = []
        for cid, severity, keywords, fix_hint in rules:
            if not keywords:
                continue  # AI judge only, 跳过 substring
            for kw in keywords:
                if kw in text:
                    shot_no, fld = self._find_violation_shot(kw)
                    violations.append(
                        Violation(
                            constraint_id=cid,
                            severity=severity,  # type: ignore[arg-type]
                            shot_no=shot_no,
                            evidence=f"字段 [{fld or '?'}] 含禁用词 '{kw}'",
                            fix_suggestion=fix_hint,
                        ),
                    )
                    break  # 同一条规则只报一次
        return violations

    def _check_protag_red_lines(self) -> list[Violation]:
        return self._check_rules(_PROTAGONIST_RULES, self._collect_text_fields())

    def _check_apartment_red_lines(self) -> list[Violation]:
        return self._check_rules(_APARTMENT_RULES, self._collect_text_fields())

    def _check_youkei_red_lines(self) -> list[Violation]:
        return self._check_rules(_YOUKEI_RULES, self._collect_text_fields())

    # ===== 5 项结构校验 =====
    def _check_structural(self) -> list[Violation]:
        violations: list[Violation] = []
        n_shots = len(self.script.shots)
        if n_shots < 3 or n_shots > 8:
            violations.append(
                Violation(
                    constraint_id="shot_count_in_range",
                    severity="FAIL",
                    shot_no=None,
                    evidence=f"shot 数={n_shots}, 应在 [3, 8] 范围内",
                    fix_suggestion="调整镜头数为 3-8 之间",
                ),
            )

        total_dur = self.script.total_duration_s
        if not 30 <= total_dur <= 90:
            violations.append(
                Violation(
                    constraint_id="total_duration_in_range",
                    severity="FAIL",
                    shot_no=None,
                    evidence=f"总时长 {total_dur}s, 应在 [30, 90]s",
                    fix_suggestion=f"调整总时长到 30-90s (当前 {total_dur}s)",
                ),
            )

        peak_count = sum(1 for s in self.script.shots if s.emotion_peak)
        if peak_count < 1:
            violations.append(
                Violation(
                    constraint_id="emotion_peak_at_least_one",
                    severity="FAIL",
                    shot_no=None,
                    evidence=f"情绪波峰数 {peak_count}, 应 ≥ 1",
                    fix_suggestion="至少 1 个 shot 设 emotion_peak=True (推荐 15%/50%/85% 位置)",
                ),
            )

        # hook.text 校验 (EP12 允许 None)
        if self.script.ep != 12 and not (self.script.hook.text or "").strip():
            violations.append(
                Violation(
                    constraint_id="hook_text_present",
                    severity="FAIL",
                    shot_no=None,
                    evidence="hook.text 为空",
                    fix_suggestion="填充 0-3s 开场钩子文本 (例: '客厅尽头那个最大的纸箱, 突然动了一下')",
                ),
            )

        # next_episode_seed 校验 (EP12 允许 None)
        if self.script.ep != 12 and not (self.script.next_episode_seed or "").strip():
            violations.append(
                Violation(
                    constraint_id="next_episode_seed_present",
                    severity="FAIL",
                    shot_no=None,
                    evidence="next_episode_seed 为空",
                    fix_suggestion="填充留给下一集的钩子 (例: 'EP02 第一夜, YouKei 不敢上床')",
                ),
            )

        return violations

    # ===== 钩子连续性 =====
    def _check_hook_continuity(self) -> list[Violation]:
        """上集 next_episode_seed 必须在本集兑现

        MVP 实现: 简单检查 prev_seed 关键词是否在本集 text 中出现
        更复杂实现 (P8 Memory Manager): 用 LLM 判定"是否兑现"
        """
        assert self.prev_script is not None  # for type checker
        prev_seed = self.prev_script.next_episode_seed or ""
        if not prev_seed:
            return []  # 上一集没留 seed, 无需校验

        # 取 prev_seed 前 5 个非空字符作为关键词
        keywords = [w for w in prev_seed.replace("EP02", "").split() if len(w) >= 3][:3]
        if not keywords:
            return []  # 上一集 seed 太短, 跳过

        text = self._collect_text_fields()
        delivered = any(kw in text for kw in keywords)
        if not delivered:
            return [
                Violation(
                    constraint_id="previous_seed_not_delivered",
                    severity="FAIL",
                    shot_no=None,
                    evidence=f"上集 next_episode_seed 关键词 {keywords} 未在本集出现",
                    fix_suggestion=f"在本集开场 0-8s 内兑现: '{prev_seed[:30]}...'",
                ),
            ]
        return []

    # ===== AI judge 警告 =====
    def _collect_ai_judge_warnings(self) -> list[str]:
        """列出需要 AI 二次判定但当前 MVP 未实现的约束

        这些规则触发时不算 violation (不算入 should_publish=False),
        但会在 warnings 里提示老板手动 review。
        """
        ai_judge_rules = [
            ("no_advertising", "商业植入检测需 AI judge"),
            ("no_swear", "脏话检测需 AI judge"),
            ("no_others_visible", "他人入镜需视频后期校验"),
            ("no_luxury_show", "炫富检测需 AI judge"),
            ("no_messy_scene", "脏乱差检测需 AI judge"),
            ("no_cat_speaking", "YouKei 开口检测需 AI judge"),
            ("no_high_jump", "跳跃过高需视频后期校验"),
            ("no_cat_fight", "真打架需视频后期校验"),
        ]
        # 当前实现: 仅警告存在性, 不实际检测
        return [f"{cid}: {desc}" for cid, desc in ai_judge_rules]


# ===== 工厂 =====
def make_default_checker(script: EpisodeScript) -> HardChecker:
    """从磁盘加载角色卡 + 上一集, 构造默认 HardChecker

    上集暂传 None (P8 Memory Manager 实现后再接 memory_bank.json)
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def _load(name: str) -> dict[str, Any]:
        path = root / "data" / "characters" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    return HardChecker(
        script=script,
        protagonist_card=_load("protagonist"),
        youkei_card=_load("youkei"),
        apartment_card=_load("apartment"),
        prev_script=None,  # P8 Memory Manager 接入
    )
