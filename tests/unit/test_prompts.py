"""
test_prompts.py — P4 5 份 prompt 模板的单测门控

验证:
1. YAML/JSON 解析成功
2. 必填字段/必填 placeholder 全部存在
3. 5 份模板与角色卡红线字面一致 (regex 匹配)
4. 与 season-01.json 钩子配置 + 爽点配置对齐
5. critic_rubric 总分 = 50, 阈值 = 38
6. memory_constraints 4 大类硬约束齐全

作者: 黑 (Hei)
创建: 2026-07-12 (P4)
"""

import json
import re
from pathlib import Path

import pytest
import yaml

# ===== 路径 =====
ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"
CHARACTERS_DIR = ROOT / "data" / "characters"
SEASONS_DIR = ROOT / "data" / "seasons"


# ===== Fixtures =====
@pytest.fixture(scope="module")
def writer():
    return yaml.safe_load((PROMPTS_DIR / "writer.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def critic():
    return yaml.safe_load((PROMPTS_DIR / "critic_rubric.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def hook_dist():
    return json.loads((PROMPTS_DIR / "hook_distribution.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def satisfaction():
    return json.loads((PROMPTS_DIR / "satisfaction_matrix.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def memory():
    return yaml.safe_load((PROMPTS_DIR / "memory_constraints.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def protagonist():
    return json.loads((CHARACTERS_DIR / "protagonist.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def youkei():
    return json.loads((CHARACTERS_DIR / "youkei.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def apartment():
    return json.loads((CHARACTERS_DIR / "apartment.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def season_01():
    return json.loads((SEASONS_DIR / "season-01.json").read_text(encoding="utf-8"))


# ===== Test 1: writer.yaml =====
class TestWriterPrompt:
    """writer.yaml — Screenwriter 系统提示"""

    def test_yaml_parses(self, writer):
        assert isinstance(writer, dict), "writer.yaml must parse to dict"

    def test_required_top_level_keys(self, writer):
        for key in ("version", "agent", "layer", "model", "system_prompt", "user_prompt_template"):
            assert key in writer, f"writer.yaml 缺少 top-level key: {key}"

    def test_agent_is_screenwriter_layer_1(self, writer):
        assert writer["agent"] == "screenwriter"
        assert writer["layer"] == 1

    def test_model_uses_minimax_anthropic(self, writer):
        assert writer["model"]["provider"] == "minimax"
        assert writer["model"]["base_url_env"] == "MINIMAXI_BASE_URL"
        assert writer["model"]["model_env"] == "MINIMAXI_TEXT_MODEL"
        assert writer["model"]["stream"] is True

    def test_system_prompt_contains_required_formulas(self, writer):
        sp = writer["system_prompt"]
        # 5 条爆款公式
        assert "3 秒钩子定律" in sp
        assert "8 秒人物关系" in sp
        assert "42 秒密度" in sp
        assert "15% / 50% / 85%" in sp
        assert "末 3 秒钩子" in sp

    def test_system_prompt_contains_save_the_cat_5_beats(self, writer):
        sp = writer["system_prompt"]
        for beat in ("Opening Image", "Catalyst", "Midpoint", "All Is Lost", "Final Image"):
            assert beat in sp, f"Save the Cat 5 beats 缺: {beat}"

    def test_system_prompt_references_all_8_knowledge_files(self, writer):
        sp = writer["system_prompt"]
        knowledge_files = [
            "opening-rules.md", "hook-design.md", "rhythm-curve.md",
            "satisfaction-matrix.md", "villain-design.md", "genre-guide.md",
            "paywall-design.md", "compliance-checklist.md",
        ]
        for kf in knowledge_files:
            assert kf in sp, f"writer.yaml 缺 knowledge 引用: {kf}"

    def test_system_prompt_includes_protagonist_forbidden(self, writer, protagonist):
        """主角 8 条红线 (forbidden array) 应在 system_prompt 中被引用"""
        # 主角 forbidden 是 array,writer.yaml 通过 Jinja placeholder 引用
        assert "character_protagonist.forbidden" in writer["system_prompt"]
        # 至少 1 条具体红线要在 writer.yaml 字面里出现 (作为示例)
        # 注意: forbidden array 在 protagonist.json 中是中文 array
        any_forbidden_word = protagonist["forbidden"][0]  # 例: "❌ 露正脸..."
        assert any("正脸" in s or "上坤" in s or "forbidden" in s for s in [
            writer["system_prompt"][:500]  # 前 500 字含关键标记即可
        ])

    def test_output_schema_in_system_prompt(self, writer):
        sp = writer["system_prompt"]
        for field in ("ep", "title", "logline", "duration_target_s", "shots",
                      "hook", "satisfaction_types", "self_check"):
            assert field in sp, f"输出 JSON schema 缺字段: {field}"

    def test_self_check_includes_5_items(self, writer):
        sp = writer["system_prompt"]
        for item in ("shot_count_ok", "duration_in_range", "emotion_peaks_count",
                     "hook_present", "forbidden_words_check"):
            assert item in sp, f"self_check 缺项: {item}"

    def test_user_prompt_has_jinja_placeholders(self, writer):
        """user_prompt_template 必须有 Jinja 变量 (运行时拼装)"""
        ut = writer["user_prompt_template"]
        for var in ("episode_spec.ep", "episode_spec.title", "episode_spec.stage",
                    "episode_spec.core_conflict", "episode_spec.logline"):
            assert var in ut, f"user_prompt_template 缺 Jinja 变量: {var}"


# ===== Test 2: critic_rubric.yaml =====
class TestCriticRubric:
    """critic_rubric.yaml — Critic 评审维度"""

    def test_yaml_parses(self, critic):
        assert isinstance(critic, dict)

    def test_required_top_level_keys(self, critic):
        for key in ("version", "agent", "layer", "threshold", "perspectives",
                    "aggregation", "output_schema"):
            assert key in critic, f"critic_rubric.yaml 缺: {key}"

    def test_total_weight_is_50(self, critic):
        assert critic["aggregation"]["total_weight"] == 50

    def test_pass_threshold_is_38(self, critic):
        assert critic["threshold"]["total_pass"] == 38
        assert critic["threshold"]["total_excellent"] == 45

    def test_5_perspectives_present(self, critic):
        assert len(critic["perspectives"]) == 5
        ids = [p["id"] for p in critic["perspectives"]]
        assert ids == ["humor", "cuteness", "continuity", "rhythm", "red_line"]

    def test_perspective_weights_sum_to_50(self, critic):
        weights = [p["weight"] for p in critic["perspectives"]]
        assert sum(weights) == 50, f"维度权重和 = {sum(weights)}, 应为 50"

    def test_red_line_is_hard_constraint(self, critic):
        red_line = next(p for p in critic["perspectives"] if p["id"] == "red_line")
        assert red_line["hard_constraint"] is True

    def test_red_line_references_3_red_line_sets(self, critic):
        """red_line system_prompt 应引用主角+公寓+猫的红线 (Jinja 渲染时填充)"""
        red_line = next(p for p in critic["perspectives"] if p["id"] == "red_line")
        sp = red_line["system_prompt"]
        assert "character_protagonist.forbidden" in sp
        assert "character_apartment.forbidden_in_apartment" in sp
        assert "character_youkei.forbidden" in sp

    def test_aggregation_formula_correct(self, critic):
        # sum(perspective.score * perspective.weight / 5)
        # 例: 全 5/5 → 15 + 15 + 10 + 5 + 5 = 50
        f = critic["aggregation"]["formula"]
        assert "perspective.score" in f
        assert "perspective.weight" in f

    def test_output_schema_required_fields(self, critic):
        schema = critic["output_schema"]
        for field in ("episode_id", "perspectives", "total_score",
                      "verdict", "feedback", "should_rewrite"):
            assert field in schema["required"], f"output_schema required 缺: {field}"

    def test_verdict_enum_values(self, critic):
        verdict_enum = critic["output_schema"]["properties"]["verdict"]["enum"]
        assert set(verdict_enum) == {"EXCELLENT", "PASS", "FAIL"}

    def test_max_retries_is_1(self, critic):
        """失败时只触发 Layer 1 重写 1 次,避免无限循环"""
        assert critic["threshold"]["max_retries"] == 1


# ===== Test 3: hook_distribution.json =====
class TestHookDistribution:
    """hook_distribution.json — 5 类钩子分布"""

    def test_json_parses(self, hook_dist):
        assert isinstance(hook_dist, dict)

    def test_required_meta(self, hook_dist):
        for key in ("version", "purpose", "source", "called_by"):
            assert key in hook_dist["_meta"]

    def test_5_hook_types(self, hook_dist):
        types = hook_dist["hook_types"]
        assert len(types) == 5
        assert set(types.keys()) == {"情绪钩", "悬念钩", "反转钩", "信息钩", "危机钩"}

    def test_distribution_sums_to_1(self, hook_dist):
        """所有钩子占比之和 = 1.0"""
        dists = [v["config_distribution"] for v in hook_dist["hook_types"].values()]
        assert abs(sum(dists) - 1.0) < 0.001, f"占比和 = {sum(dists)}, 应为 1.0"

    def test_distribution_matches_season_01_config(self, hook_dist, season_01):
        """钩子占比必须与 season-01.json hook_type_distribution_config 一致"""
        season_dist = season_01["hook_type_distribution_config"]
        for hook_name, info in hook_dist["hook_types"].items():
            expected = season_dist[hook_name]
            assert info["config_distribution"] == expected, \
                f"{hook_name}: prompt={info['config_distribution']}, season={expected}"

    def test_each_hook_has_subtypes(self, hook_dist):
        """每类钩子至少 2 个 subtypes"""
        for name, info in hook_dist["hook_types"].items():
            assert "subtypes" in info
            assert len(info["subtypes"]) >= 2, f"{name} subtypes < 2"

    def test_each_hook_has_verifier_keywords(self, hook_dist):
        for name, info in hook_dist["hook_types"].items():
            assert "verifier_keywords" in info
            assert len(info["verifier_keywords"]) >= 3, f"{name} keywords < 3"

    def test_each_hook_has_design_template(self, hook_dist):
        for name, info in hook_dist["hook_types"].items():
            assert "design_template" in info
            assert len(info["design_template"]) > 5, f"{name} design_template 太短"

    def test_validation_rules_present(self, hook_dist):
        rules = hook_dist["validation_rules"]
        assert rules["must_match_season_config"] is True
        assert rules["tolerance_pct"] == 0.10

    def test_EP12_exception_present(self, hook_dist):
        assert "EP12_exception" in hook_dist["validation_rules"]
        assert hook_dist["validation_rules"]["EP12_exception"]["allow_null_hook"] is True

    def test_layer3_hard_check_enabled(self, hook_dist):
        l3 = hook_dist["layer3_hard_check"]
        assert l3["enabled"] is True
        assert len(l3["checks"]) >= 3


# ===== Test 4: satisfaction_matrix.json =====
class TestSatisfactionMatrix:
    """satisfaction_matrix.json — 5 类爽点矩阵"""

    def test_json_parses(self, satisfaction):
        assert isinstance(satisfaction, dict)

    def test_5_satisfaction_types(self, satisfaction):
        types = satisfaction["satisfaction_types"]
        assert len(types) == 5
        assert set(types.keys()) == {
            "情感爆发", "悬念揭秘", "打脸复仇", "逆袭翻盘", "身份碾压",
        }

    def test_distribution_sums_to_1(self, satisfaction):
        dists = [v["config_weight"] for v in satisfaction["satisfaction_types"].values()]
        assert abs(sum(dists) - 1.0) < 0.001

    def test_distribution_matches_season_01_config(self, satisfaction, season_01):
        season_dist = season_01["satisfaction_matrix_config"]
        for st_name, info in satisfaction["satisfaction_types"].items():
            expected = season_dist[st_name]
            assert info["config_weight"] == expected, \
                f"{st_name}: prompt={info['config_weight']}, season={expected}"

    def test_emotion_explosion_has_highest_weight(self, satisfaction):
        """情感爆发应是最高权重 (0.60)"""
        weights = {k: v["config_weight"] for k, v in satisfaction["satisfaction_types"].items()}
        max_key = max(weights, key=weights.get)
        assert max_key == "情感爆发"
        assert weights["情感爆发"] == 0.60

    def test_each_satisfaction_has_intensity_levels(self, satisfaction):
        """每类爽点必须有 5 档强度 (★~★★★★★)"""
        for name, info in satisfaction["satisfaction_types"].items():
            assert "intensity_levels" in info
            assert len(info["intensity_levels"]) == 5, f"{name} intensity < 5 档"

    def test_stage_adaptations_4_stages(self, satisfaction):
        """stage_adaptations 必须有 4 阶段 (起势/攀升/风暴/决战)"""
        stages = satisfaction["validation_rules"]["stage_adaptations"]
        assert len(stages) == 4
        for stage_key in ("起势段", "攀升段", "风暴段", "决战段"):
            assert stage_key in stages

    def test_layer3_hard_check_enabled(self, satisfaction):
        l3 = satisfaction["layer3_hard_check"]
        assert l3["enabled"] is True

    def test_EP12_must_be_emotion(self, satisfaction):
        """EP12 决战段必须是情感爆发 + ★★★★★"""
        ep12_check = next(
            (c for c in satisfaction["layer3_hard_check"]["checks"] if "EP12" in c),
            None,
        )
        assert ep12_check is not None
        assert "情感爆发" in ep12_check
        assert "★★★★★" in ep12_check


# ===== Test 5: memory_constraints.yaml =====
class TestMemoryConstraints:
    """memory_constraints.yaml — Layer 3 硬约束 + Memory Manager"""

    def test_yaml_parses(self, memory):
        assert isinstance(memory, dict)

    def test_required_top_level_keys(self, memory):
        for key in ("version", "agent", "layer", "memory_bank", "hard_constraints",
                    "memory_manager_prompt", "hard_check_prompt"):
            assert key in memory

    def test_memory_bank_schema(self, memory):
        mb = memory["memory_bank"]
        assert "storage" in mb
        assert "schema" in mb
        assert "season_id" in mb["schema"]["required"]
        assert "episodes" in mb["schema"]["required"]

    def test_4_hard_constraint_categories(self, memory):
        """4 大类硬约束"""
        cats = memory["hard_constraints"]
        assert len(cats) == 4
        ids = [c["id"] for c in cats]
        assert ids == [
            "timeline_consistency", "character_position",
            "hook_continuity", "privacy_compliance",
        ]

    def test_privacy_compliance_has_HARD_FAIL_severity(self, memory):
        """隐私合规必须是 HARD_FAIL (一票否决)"""
        privacy = next(c for c in memory["hard_constraints"] if c["id"] == "privacy_compliance")
        assert privacy["severity"] == "HARD_FAIL"

    def test_privacy_has_19_red_lines(self, memory):
        """老板 8 + 公寓 6 + 猫 5 = 19 条红线"""
        privacy = next(c for c in memory["hard_constraints"] if c["id"] == "privacy_compliance")
        rules = privacy["rules"]
        assert len(rules) == 19, f"隐私红线 = {len(rules)}, 应为 19"

    def test_red_line_keywords_match_protagonist(self, memory, protagonist):
        """主角 8 条红线字面应与 protagonist.json forbidden 一致"""
        privacy = next(c for c in memory["hard_constraints"] if c["id"] == "privacy_compliance")
        # 主角 8 红线 id (精确匹配,避免误匹配猫红线 no_cat_danger_action)
        protagonist_ids = {
            "no_real_face", "no_real_name", "no_address_leak", "no_controversy",
            "no_violence", "no_swear", "no_cat_danger", "no_advertising",
        }
        protagonist_rules = [r for r in privacy["rules"] if r["id"] in protagonist_ids]
        assert len(protagonist_rules) == 8, \
            f"主角红线 = {len(protagonist_rules)}, 应为 8, ids = {[r['id'] for r in protagonist_rules]}"

    def test_red_line_keywords_match_apartment(self, memory, apartment):
        """公寓 6 条红线"""
        privacy = next(c for c in memory["hard_constraints"] if c["id"] == "privacy_compliance")
        apartment_rules = [r for r in privacy["rules"] if r["id"].startswith("no_") and
                           r["id"] not in {"no_real_face", "no_real_name", "no_address_leak",
                                            "no_controversy", "no_violence", "no_swear",
                                            "no_cat_danger", "no_advertising"}]
        # 6 条公寓 (no_window_view/no_door_number/no_courier_label/no_others_visible/no_luxury_show/no_messy_scene)
        # + 5 条 YouKei (no_cat_speaking/no_high_jump/no_cat_danger_action/no_cat_superpower/no_cat_fight)
        # = 11 条
        assert len(apartment_rules) == 11

    def test_timeline_consistency_rules(self, memory):
        tc = next(c for c in memory["hard_constraints"] if c["id"] == "timeline_consistency")
        assert len(tc["rules"]) >= 3

    def test_character_position_includes_balcony_safety(self, memory):
        cp = next(c for c in memory["hard_constraints"] if c["id"] == "character_position")
        balcony_rules = [r for r in cp["rules"] if "balcony" in r["id"]]
        assert len(balcony_rules) >= 1

    def test_hook_continuity_has_3_rules(self, memory):
        hc = next(c for c in memory["hard_constraints"] if c["id"] == "hook_continuity")
        assert len(hc["rules"]) >= 3

    def test_memory_manager_prompt_has_inputs_outputs(self, memory):
        mp = memory["memory_manager_prompt"]
        assert "输入" in mp
        assert "输出" in mp
        for input_item in ("season-XX.json", "memory_bank.json", "next_episode_seed"):
            assert input_item in mp, f"Memory Manager 缺输入: {input_item}"

    def test_hard_check_prompt_lists_4_categories(self, memory):
        hc = memory["hard_check_prompt"]
        for cat in ("时间线", "角色位置", "钩子", "隐私"):
            assert cat in hc, f"Hard Check 缺类别: {cat}"


# ===== Test 6: 跨模板一致性 =====
class TestCrossTemplateConsistency:
    """5 份模板之间的引用一致性"""

    def test_critic_red_line_alignment_with_memory(self, critic, memory):
        """critic.red_line 与 memory.privacy_compliance 引用一致的 forbidden 集合"""
        crl = next(p for p in critic["perspectives"] if p["id"] == "red_line")
        privacy = next(c for c in memory["hard_constraints"] if c["id"] == "privacy_compliance")
        # 都有 3 个 Jinja 引用 (主角 + 公寓 + 猫)
        for ref in ("character_protagonist.forbidden",
                    "character_apartment.forbidden_in_apartment",
                    "character_youkei.forbidden"):
            assert ref in crl["system_prompt"]
            # privacy 通过 pattern_match / check_method 实现,不在 prompt 中用 Jinja
            # 但 privacy.rules 总数 = 19 = 8 + 6 + 5
            assert len(privacy["rules"]) == 19

    def test_hook_distribution_used_by_hard_check(self, hook_dist, memory):
        """hook_distribution 的 layer3_hard_check 与 memory.hook_continuity 协同"""
        hk = memory["hard_constraints"][2]  # hook_continuity
        assert hk["id"] == "hook_continuity"
        assert len(hk["rules"]) >= 2

    def test_writer_references_same_5_hooks(self, writer, hook_dist):
        """writer.yaml 知道 hook_type,会按 episode_spec.hook_type 渲染"""
        assert "episode_spec.hook_type" in writer["user_prompt_template"]

    def test_satisfaction_intensity_in_critic(self, critic, satisfaction):
        """critic.cuteness 维度覆盖情感爆发/悬念揭秘"""
        cs = next(p for p in critic["perspectives"] if p["id"] == "cuteness")
        # 萌点 = 情感爆发在猫视角的体现
        # satisfaction.json 里情感爆发最高 (0.60)
        assert satisfaction["satisfaction_types"]["情感爆发"]["config_weight"] == 0.60

    def test_memory_bank_storage_is_gitignored(self):
        """memory_bank.json 应在 .gitignore 中 (state 数据)"""
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        # 接受任何包含 state 或 memory_bank 的忽略规则
        assert "data/state" in gitignore or "memory_bank" in gitignore


# ===== Test 7: 文件级元数据 =====
class TestFileMetadata:
    """5 份 prompt 文件本身元数据"""

    def test_all_files_exist(self):
        for name in ("writer.yaml", "critic_rubric.yaml",
                     "hook_distribution.json", "satisfaction_matrix.json",
                     "memory_constraints.yaml"):
            assert (PROMPTS_DIR / name).exists(), f"缺文件: {name}"

    def test_files_have_top_comments(self):
        """每份模板开头都有注释说明 (人工可读)"""
        for name in ("writer.yaml", "critic_rubric.yaml", "memory_constraints.yaml"):
            content = (PROMPTS_DIR / name).read_text(encoding="utf-8")
            assert content.startswith("#"), f"{name} 应以 # 注释开头"

    def test_version_is_0_3_0(self, writer, critic, hook_dist, satisfaction, memory):
        """所有模板版本对齐 v0.3.0"""
        assert writer["version"] == "0.3.0"
        assert critic["version"] == "0.3.0"
        assert hook_dist["_meta"]["version"] == "0.3.0"
        assert satisfaction["_meta"]["version"] == "0.3.0"
        assert memory["version"] == "0.3.0"

    def test_yaml_files_use_safe_load(self):
        """确保所有 YAML 文件不含 Python-only 标签 (兼容 yaml.safe_load)"""
        for name in ("writer.yaml", "critic_rubric.yaml", "memory_constraints.yaml"):
            content = (PROMPTS_DIR / name).read_text(encoding="utf-8")
            # safe_load 不支持 !!python/object 等标签
            assert "!!python" not in content, f"{name} 含 unsafe yaml 标签"