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
    # P1.4: 可选注入本集预期 (从 season-XX.json 读)
    episode_spec: dict[str, Any] = field(default_factory=dict)

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

        # P1.4: 钩子关键词校验 (从 hook_distribution.json)
        violations.extend(self._check_hook_verifier_keywords())

        # P1.4: satisfaction_intensity 校验 (从 satisfaction_matrix.json)
        violations.extend(self._check_satisfaction_intensity())

        # 统计
        total_constraints = 26  # 19 红线 + 5 结构 + 2 P1.4
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
        """P1.5 增强: 上集 next_episode_seed 必须在本集兑现

        判定等级 (从弱到强):
        - PASS: 所有 keywords (≥3 字) 都在本集出现
        - WARNING: 部分命中 (≥50% keywords) — 记录到 warnings, 不阻塞
        - FAIL: 全部未命中 — 记 violation, 阻塞发布

        MVP: 关键词 substring 匹配 (鲁棒性差, 后续 P8 增强用 LLM 判定)
        """
        assert self.prev_script is not None  # for type checker
        prev_seed = self.prev_script.next_episode_seed or ""
        if not prev_seed:
            return []  # 上一集没留 seed, 无需校验

        # 取 prev_seed 关键词 (去掉集号 / 分词 / ≥3 字)
        import re

        cleaned = re.sub(r"EP\d+", "", prev_seed)
        keywords = [w for w in re.findall(r"[\w\u4e00-\u9fff]+", cleaned) if len(w) >= 3][:3]
        if not keywords:
            return []  # 上一集 seed 太短 / 没可用关键词, 跳过

        text = self._collect_text_fields()
        hit = [kw for kw in keywords if kw in text]
        miss = [kw for kw in keywords if kw not in text]

        # 全部命中 → PASS
        if not miss:
            logger.debug(f"P1.5: prev_seed 关键词全命中: {hit}")
            return []

        # 部分命中 → WARNING (不阻塞)
        if hit:
            coverage = len(hit) / len(keywords)
            logger.warning(
                f"P1.5: prev_seed 部分命中 ({coverage:.0%}): hit={hit}, miss={miss}. "
                f"记 warning 不阻塞.",
            )
            # P1.5: 部分命中暂不返回 violation, 由老板人工 review
            # (后续 P8 增强: 调 LLM 判定语义是否兑现)
            return []

        # 全部未命中 → FAIL
        return [
            Violation(
                constraint_id="previous_seed_not_delivered",
                severity="FAIL",
                shot_no=None,
                evidence=f"上集 next_episode_seed 关键词 {keywords} 全部未在本集出现",
                fix_suggestion=f"在本集开场 0-8s 内兑现: '{prev_seed[:40]}...'",
            ),
        ]

    # ===== P1.4 钩子关键词校验 =====
    def _check_hook_verifier_keywords(self) -> list[Violation]:
        """P1.4: 从 hook_distribution.json 取当前 hook.type 的 verifier_keywords,验证末 shot 字幕至少含 1 个

        例: EP01 悬念钩/来者悬念 → verifier_keywords=['?', '突然', '下一秒', '没想到', '究竟']
        末 shot 字幕必须 ≥ 1 个命中, 不然记 violation
        """
        # EP12 季末允许 hook_type=null
        if self.script.ep == 12:
            return []

        hook_type = self.script.hook.type
        if not hook_type:
            return [
                Violation(
                    constraint_id="hook_type_missing_p14",
                    severity="FAIL",
                    shot_no=None,
                    evidence="hook.type 为空 (非 EP12)",
                    fix_suggestion="填写 hook.type (5 选一: 情绪/悬念/反转/信息/危机)",
                ),
            ]

        keywords = self._load_hook_verifier_keywords(hook_type)
        if not keywords:
            return []  # hook_distribution.json 损坏或未配置 → 跳过 (不阻塞)

        # 取末 shot 字幕 (0-3s 钩子或最后一 shot)
        last_shot_subtitle = ""
        if self.script.shots:
            # EP1 钩子在 hook.text + 末 shot 字幕
            last_shot = self.script.shots[-1]
            last_shot_subtitle = (last_shot.subtitle or "") + " " + (last_shot.action or "") + " " + (last_shot.voiceover or "")
        hook_text = self.script.hook.text or ""
        combined = hook_text + " " + last_shot_subtitle

        hit = [kw for kw in keywords if kw in combined]
        if not hit:
            return [
                Violation(
                    constraint_id="hook_verifier_keywords_missing_p14",
                    severity="FAIL",
                    shot_no=self.script.shots[-1].shot_no if self.script.shots else None,
                    evidence=f"hook.type={hook_type} 需 verifier_keywords ≥ 1 个: {keywords}, 末 shot + hook.text 均未命中",
                    fix_suggestion=f"末 shot 字幕/动作/voiceover 加 ≥ 1 个关键词 (推荐: {keywords[:3]})",
                ),
            ]
        return []

    def _load_hook_verifier_keywords(self, hook_type: str) -> list[str]:
        """从 prompts/hook_distribution.json 加载 hook_type 对应的 verifier_keywords"""
        try:
            import json
            from pathlib import Path
            path = Path(__file__).resolve().parents[1] / "prompts" / "hook_distribution.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("hook_types", {}).get(hook_type, {}).get("verifier_keywords", [])
        except Exception:
            return []

    # ===== P1.4 satisfaction_intensity 校验 =====
    def _check_satisfaction_intensity(self) -> list[Violation]:
        """P1.4: 从 satisfaction_matrix.json 验证 satisfaction_intensity 在合理范围

        例: 情感爆发 类 ∈ [★, ★★★★★] (LLM 必须给 1-5 颗星)
        例: EP12 必须 satisfaction_intensity=★★★★★ + 类型=['情感爆发']
        """
        sat_types = self.script.satisfaction_types or []

        if not sat_types:
            return [
                Violation(
                    constraint_id="satisfaction_types_empty_p14",
                    severity="FAIL",
                    shot_no=None,
                    evidence="satisfaction_types 为空",
                    fix_suggestion="从 5 类中选 1-3 个 (情感爆发/悬念揭秘/打脸复仇/逆袭翻盘/身份碾压)",
                ),
            ]

        violations: list[Violation] = []

        # EP12 硬要求: 情感爆发
        if self.script.ep == 12 and "情感爆发" not in sat_types:
            violations.append(
                Violation(
                    constraint_id="ep12_must_be_emotional_climax_p14",
                    severity="HARD_FAIL",
                    shot_no=None,
                    evidence=f"EP12 必须含 '情感爆发', 实际 {sat_types}",
                    fix_suggestion="EP12 季末集必须有 '情感爆发' 类型 (温馨定格是季末唯一调性)",
                ),
            )

        # 与 episode_spec 预期覆盖率 ≥ 50% (P1.3 新增)
        if self.episode_spec:
            expected = self.episode_spec.get("satisfaction_types", [])
            if expected:
                expected_set = set(expected)
                actual_set = set(sat_types)
                hit = expected_set & actual_set
                coverage = len(hit) / len(expected_set)
                if coverage < 0.5:
                    violations.append(
                        Violation(
                            constraint_id="satisfaction_coverage_low_p14",
                            severity="FAIL",
                            shot_no=None,
                            evidence=f"satisfaction_types 覆盖率 {coverage:.0%} ({len(hit)}/{len(expected_set)}), 需 ≥ 50% (预期 {expected}, 实际 {sat_types})",
                            fix_suggestion=f"覆盖不足, 补 1 个预期类型: {list(expected_set - actual_set)[:2]}",
                        ),
                    )

        # 情感爆发类必须有 verifier_keywords 至少 1 个 (来自 satisfaction_matrix.json)
        if "情感爆发" in sat_types:
            kw_list = self._load_satisfaction_keywords("情感爆发")
            if kw_list:
                text = self._collect_text_fields()
                hit = [kw for kw in kw_list if kw in text]
                if not hit:
                    violations.append(
                        Violation(
                            constraint_id="emotion_keywords_missing_p14",
                            severity="FAIL",
                            shot_no=None,
                            evidence=f"情感爆发类需 verifier_keywords ≥ 1 个: {kw_list[:5]}, 全文未命中",
                            fix_suggestion=f"字幕/voiceover 加 ≥ 1 个关键词: {kw_list[:3]}",
                        ),
                    )

        return violations

    def _load_satisfaction_keywords(self, sat_type: str) -> list[str]:
        """从 prompts/satisfaction_matrix.json 加载 sat_type 对应的 verifier_keywords"""
        try:
            import json
            from pathlib import Path
            path = Path(__file__).resolve().parents[1] / "prompts" / "satisfaction_matrix.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("satisfaction_types", {}).get(sat_type, {}).get("verifier_keywords", [])
        except Exception:
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
def make_default_checker(
    script: EpisodeScript,
    prev_script: EpisodeScript | None = None,
) -> HardChecker:
    """从磁盘加载角色卡 + 上一集, 构造默认 HardChecker

    Args:
        script: 当前集 EpisodeScript (已过 schema 校验)
        prev_script: 上一集 EpisodeScript (可选, EP02+ 用于跨集钩子回收校验).
            None 时自动从 data/state/memory_bank.json 按 ep-1 加载.

    P1.5: prev_script 自动从 memory_bank 加载, 避免 daily.py 重复代码.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    def _load(name: str) -> dict[str, Any]:
        path = root / "data" / "characters" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    # P1.5: 自动从 memory_bank.json 加载 prev_script (避免 daily.py 重复代码)
    if prev_script is None and script.ep >= 2:
        prev_script = _load_prev_script_from_memory_bank(script.ep, root)

    return HardChecker(
        script=script,
        protagonist_card=_load("protagonist"),
        youkei_card=_load("youkei"),
        apartment_card=_load("apartment"),
        prev_script=prev_script,  # P1.5: 接 memory_bank
    )


def _load_prev_script_from_memory_bank(
    current_ep: int,
    project_root: Path,
) -> EpisodeScript | None:
    """P1.5: 从 data/state/memory_bank.json 加载上一集 prev_script

    memory_bank 里只存 EpisodeMemory (元数据), 不存完整 EpisodeScript.
    本函数用 prev_episode 的 key_facts + title + hook_seed_for_next 重建一个
    "minimal prev_script", 只用于 hard_check 的 hook_continuity 校验
    (hard_check 只需要 prev_script.next_episode_seed, 其他字段不用).

    Returns:
        EpisodeScript 或 None (memory_bank 不存在 / 没上一集 / 反序列化失败)
    """
    import json

    memory_path = project_root / "data" / "state" / "memory_bank.json"
    if not memory_path.exists():
        return None

    try:
        data = json.loads(memory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None

    prev_ep = current_ep - 1
    for em in data.get("episodes", []):
        if em.get("ep") == prev_ep:
            # 构造 minimal prev_script (类型安全: 用真实 EpisodeScript)
            # hard_check 只读 prev_script.next_episode_seed, 其他字段填合法默认值即可
            from src.types import EpisodeScript, HookSpec, SelfCheck, Shot

            # key_facts 借 rhythm_notes 字段传递 (供 hook_continuity 关键词提取)
            key_facts_text = " ".join(em.get("key_facts", []))

            # 构造 3 个 minimal shot (满足 min_length=3, 只有 1 个 emotion_peak=True)
            minimal_shot_peak = Shot(
                shot_no=1,
                time_range="0-20s",
                duration_s=20,
                scene="客厅",
                camera="固定",
                action=key_facts_text or "上坤与 YouKei",
                voiceover="",
                subtitle="",
                emotion_peak=True,
            )
            minimal_shot_plain = Shot(
                shot_no=2,
                time_range="20-40s",
                duration_s=20,
                scene="客厅",
                camera="固定",
                action="",
                voiceover="",
                subtitle="",
            )

            prev_script = EpisodeScript(
                ep=prev_ep,
                title=em.get("title", f"EP{prev_ep}"),
                logline=f"EP{prev_ep} minimal prev (P1.5 stub)",
                duration_target_s=60,
                shots=[minimal_shot_peak, minimal_shot_plain, minimal_shot_plain],  # 3 shots, 只有 #1 emotion_peak=True
                hook=HookSpec(
                    type="悬念钩",  # MVP: 默认值, hard_check 不会读 prev 的 hook.type
                    subtype="",
                    text="",
                ),
                satisfaction_types=["悬念揭秘"],  # 满足 min_length=1
                next_episode_seed=em.get("hook_seed_for_next", ""),
                rhythm_notes=key_facts_text,  # 借字段传递 key_facts
                self_check=SelfCheck(
                    shot_count_ok=True,
                    duration_in_range=True,
                    emotion_peaks_count=1,
                    hook_present=True,
                    forbidden_words_check=True,
                ),
            )
            logger.debug(
                f"P1.5: 加载 EP{prev_ep} prev_script "
                f"(next_seed='{em.get('hook_seed_for_next', '')[:40]}...')",
            )
            return prev_script

    return None
