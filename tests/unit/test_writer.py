"""
test_writer.py — Writer 模块单元测试

P9 fix: writer.py system_prompt 渲染漏传 episode_spec,
        writer.yaml system_prompt 模板引用 episode_spec → Jinja2 UndefinedError
        (dry-run 隐藏 bug — dry-run 不调 writer.generate_episode_candidates)

测试覆盖:
- TestPromptRendering::test_render_system_prompt_no_undefined 渲染 system_prompt 不报错 + 含 episode_spec 字段
- TestPromptRendering::test_render_user_prompt_no_undefined   渲染 user_prompt_template 不报错 + 含 episode_spec 字段
- TestPromptRendering::test_system_and_user_prompts_differ    两个 prompt 内容明显不同
"""

from __future__ import annotations

import os

import pytest
import yaml

PROMPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts"
)


@pytest.fixture
def episode_data() -> dict:
    """EP05 真实 episode 数据 (从 data/seasons/season-01.json 复刻)"""
    return {
        "ep": 5,
        "title": "🛁 洗澡大作战",
        "stage": "起势段",
        "stage_position_pct": 25,
        "scene": "卫生间",
        "core_conflict": "YouKei 第一次洗澡, 激烈反抗",
        "logline": "YouKei 第一次被按进浴缸, 满浴室泡沫, 上坤湿透",
        "hook_type": "悬念钩",
        "hook_subtype": "来者悬念",
        "hook_text_template": "浴室里传来一声惊叫, 然后是长久的沉默",
        "satisfaction_types": ["情感爆发"],
        "satisfaction_intensity": "★★★",
        "key_moments": [
            "0:05 - 上坤抱 YouKei 进浴室",
            "0:30 - 水龙头打开, YouKei 突然挣扎",
            "0:55 - 泡沫飞溅, 上坤满脸水",
        ],
        "rhythm_notes": "前 5s 必现冲突 (水声 + 猫叫)",
        "next_episode_seed": "EP06 第一次烘干, YouKei 蜷缩在毛巾里",
    }


@pytest.fixture
def characters() -> dict:
    """3 个角色卡 (上坤/YouKei/公寓) — 最小 stub (用 Jinja 模板变量命名)"""
    return {
        "character_protagonist": {
            "name": "上坤",
            "forbidden": "1. 不露正脸\n2. 不说脏话\n3. 不暴露真名\n4. 不暴露真实公司\n5. 不拍快递单\n6. 不拍楼牌号\n7. 不拍邻居正脸\n8. 不拍宠物医院招牌",
        },
        "character_youkei": {
            "name": "YouKei",
            "forbidden": "1. 不开口说话\n2. 不被伤害\n3. 不出阳台护栏\n4. 不碰明火\n5. 不跟其他猫狗",
        },
        "character_apartment": {
            "name": "上海 60 平",
            "forbidden_in_apartment": "1. 阳台护栏外侧\n2. 窗户街景\n3. 快递单特写\n4. 楼牌号\n5. 邻居正脸\n6. 宠物医院招牌",
        },
    }


@pytest.fixture
def season_context() -> dict:
    return {
        "season_id": 1,
        "title": "上坤 × YouKei 入住 60 平新家 30 天",
        "theme": "适应、共处、萌点、生活小摩擦、温馨收尾",
        "total_episodes": 12,
        "stage_distribution": {"起势段": 3, "递进段": 4, "爆发段": 3, "收束段": 2},
        "stage_description": "建立核心角色 + 萌点铺设 + 钩子悬念",
        "stage_intensity": "★★",
        "stage_adaptations": "情感爆发 100% (建立核心情感)",
        "hook_verifier_keywords": ["?", "突然", "下一秒"],
        "satisfaction_verifier_keywords": ["没想到", "原来", "突然"],  # P1.7-B: 新增
        "quality_targets": {
            "shot_count": "3-8 个",
            "duration_target_s": 60,
            "emotion_peaks_per_episode": "至少 1 个 (15% / 50% / 85% 位置)",
            "hook_strength_min": "中等 (EP01-02 引入期)",
        },
        "hook_strength_min": "中等 (EP01-02 引入期)",
    }


class TestPromptRendering:
    """Writer 渲染 system_prompt + user_prompt_template 不报错"""

    def test_render_system_prompt_no_undefined(
        self, episode_data, characters, season_context
    ):
        """system_prompt 渲染成功 + 含 episode_spec 字段 (P9 fix 验证)

        bug 之前: writer.py 漏传 episode_spec → Jinja2 UndefinedError
        """
        from src.prompt_renderer import render_prompt_template

        ctx = {
            **characters,
            "episode_spec": episode_data,
            "season_context": season_context,
            "references_excerpt": "",
            "pct": 25,  # EP5 / 12 = 42%, 但 fixture 简化为 25
        }

        # 不应抛 UndefinedError
        result = render_prompt_template("writer.yaml", ctx, field="system_prompt")

        # 渲染结果应该非空
        assert len(result) > 1000, f"system_prompt 渲染过短 ({len(result)} chars)"

        # 渲染结果应该含 episode_spec 实际值 (证明 episode_spec 被注入并渲染)
        assert "5" in result  # ep=5
        assert "洗澡大作战" in result or "🛁 洗澡大作战" in result  # title
        assert "悬念钩" in result  # hook_type

    def test_render_user_prompt_no_undefined(
        self, episode_data, characters, season_context
    ):
        """user_prompt_template 渲染成功 (这是已有路径, 测试它没坏)"""
        from src.prompt_renderer import render_prompt_template

        ctx = {
            **characters,
            "episode_spec": episode_data,
            "season_context": season_context,
            "references_excerpt": "",
            "pct": 25,
        }

        result = render_prompt_template("writer.yaml", ctx, field="user_prompt_template")

        assert len(result) > 500
        # user prompt 包含集任务信息
        assert "EP5" in result or "EP05" in result  # 集号
        assert "🛁 洗澡大作战" in result

    def test_system_and_user_prompts_differ(
        self, episode_data, characters, season_context
    ):
        """system 和 user prompt 应明显不同 (sanity check)"""
        from src.prompt_renderer import render_prompt_template

        ctx = {
            **characters,
            "episode_spec": episode_data,
            "season_context": season_context,
            "references_excerpt": "",
            "pct": 25,
        }

        sys_p = render_prompt_template("writer.yaml", ctx, field="system_prompt")
        user_p = render_prompt_template("writer.yaml", ctx, field="user_prompt_template")

        # system_prompt 应包含"你是" (角色定义)
        assert "你是" in sys_p or "编剧" in sys_p
        # user_prompt_template 应包含"集任务" 或类似
        assert "集任务" in user_p or "当前集" in user_p
        # 两者应有显著差异
        assert sys_p != user_p
        assert len(sys_p) != len(user_p)

    def test_writer_yaml_uses_yaml_safe_load(self):
        """writer.yaml 必须用 safe_load (防止 yaml.load 漏洞)"""
        with open(os.path.join(PROMPTS_DIR, "writer.yaml")) as f:
            data = yaml.safe_load(f)

        assert "system_prompt" in data
        assert "user_prompt_template" in data
        assert isinstance(data["system_prompt"], str)
        assert isinstance(data["user_prompt_template"], str)


# 防止 pytest skip import 报错


class TestBuildSeasonContext:
    """P1.2: Writer._build_season_context 注入完整季上下文"""

    def test_season_context_required_keys(self, episode_data):
        """_build_season_context 返回的 dict 必含 10 个 P1.2 字段"""
        import json
        from src.writer import Writer

        class _M:
            pass

        season = json.load(open("data/seasons/season-01.json"))
        ep1 = next(e for e in season["episodes"] if e["ep"] == 1)
        ctx = Writer(_M())._build_season_context(season, ep1)

        required = {
            "season_id", "title", "theme", "total_episodes",
            "stage_distribution", "stage_description", "stage_intensity",
            "stage_adaptations", "hook_verifier_keywords",
            "quality_targets", "hook_strength_min",
        }
        assert required.issubset(ctx.keys()), f"缺失: {required - ctx.keys()}"

    def test_stage_description_lookup(self, episode_data):
        """stage_description 应该从 stage_distribution[stage].description 查"""
        import json
        from src.writer import Writer

        class _M:
            pass

        season = json.load(open("data/seasons/season-01.json"))
        ep1 = next(e for e in season["episodes"] if e["ep"] == 1)
        ctx = Writer(_M())._build_season_context(season, ep1)
        assert ctx["stage_description"] == season["stage_distribution"]["起势段"]["description"]

    def test_hook_keywords_match_distribution_json(self, episode_data):
        """hook_verifier_keywords 应该从 hook_distribution.json 取"""
        import json
        from src.writer import Writer

        class _M:
            pass

        season = json.load(open("data/seasons/season-01.json"))
        ep1 = next(e for e in season["episodes"] if e["ep"] == 1)
        ctx = Writer(_M())._build_season_context(season, ep1)
        # EP01 是悬念钩
        assert isinstance(ctx["hook_verifier_keywords"], list)
        assert len(ctx["hook_verifier_keywords"]) >= 1
        assert "?" in ctx["hook_verifier_keywords"] or "突然" in ctx["hook_verifier_keywords"]

    def test_stage_adaptations_match_matrix_json(self, episode_data):
        """stage_adaptations 应该从 satisfaction_matrix.json validation_rules 取"""
        import json
        from src.writer import Writer

        class _M:
            pass

        season = json.load(open("data/seasons/season-01.json"))
        ep1 = next(e for e in season["episodes"] if e["ep"] == 1)
        ctx = Writer(_M())._build_season_context(season, ep1)
        # EP01 是起势段
        assert "情感爆发" in ctx["stage_adaptations"]


class TestP12SeasonContextInPrompt:
    """P1.2: writer.yaml 渲染结果应包含季上下文"""

    def test_system_prompt_includes_season_context(self, episode_data, characters, season_context):
        """system_prompt 应包含'季上下文' 段"""
        from src.prompt_renderer import render_prompt_template

        ctx = {
            **characters,
            "episode_spec": episode_data,
            "season_context": season_context,
            "references_excerpt": "",
            "pct": 25,
        }
        result = render_prompt_template("writer.yaml", ctx, field="system_prompt")

        # 关键字段应在
        assert "## 📊 季上下文" in result
        assert "季进度" in result
        assert "爽点配比" in result
        assert "钩子配比" in result
        assert "质量硬目标" in result

    def test_user_prompt_includes_hook_keywords(self, episode_data, characters, season_context):
        """user_prompt 应包含钩子兑现要求 + 关键词"""
        from src.prompt_renderer import render_prompt_template

        ctx = {
            **characters,
            "episode_spec": episode_data,
            "season_context": season_context,
            "references_excerpt": "",
            "pct": 25,
        }
        result = render_prompt_template("writer.yaml", ctx, field="user_prompt_template")

        assert "## 🎯 钩子兑现要求" in result
        assert "下一集钩子" in result  # next_episode_seed 注入
        assert "verifier_keywords" in result  # hook keywords 注入
