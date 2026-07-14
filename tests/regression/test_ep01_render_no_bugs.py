"""
test_ep01_render_no_bugs.py — EP01 markdown 渲染回归测试 (v0.42 fix)

老板截图 (2026-07-14) 暴露的 5 个渲染 bug:
1. frontmatter 整段 raw 泄露到正文
2. H1 重复 3 次 (副标题 / frontmatter / H2)
3. emoji 不统一 (📦 / 📺 / 🎬)
4. EP01 编号在 H1 缺失
5. meta 信息裸 inline

本测试每次跑都对 EP01 markdown 做完整断言,
任何一项 fail = 截图回归。

CI 友好: 不需要 LLM, 用 fixtures 构造 EpisodeScript
"""

from __future__ import annotations

import pytest

from src.markdown_renderer import render_episode
from src.types import (
    EpisodeScript,
    HookSpec,
    HookType,
    SelfCheck,
    Shot,
)


# ===== Fixtures =====

def _make_ep01_script() -> EpisodeScript:
    """复刻老板截图里的 EP01 内容 (用于回归测试)"""
    shots = [
        Shot(
            shot_no=1,
            time_range="0-3s",
            scene="客厅纸箱堆",
            camera="固定机位低角度仰拍(只拍背部+手)",
            action="我搬第3个箱子进屋,客厅尽头最大箱子突然晃了一下",
            voiceover="下午3点,搬第3个箱子的时候——",
            subtitle="下午 3 点,搬第 3 个箱子的时候——",
            duration_s=3,
            emotion_peak=False,
            shot_type="opening_image",
        ),
        Shot(
            shot_no=2,
            time_range="3-8s",
            scene="客厅,纸箱区",
            camera="手持跟拍(背面)",
            action="我放下箱子走过去,尾巴缩回去了",
            voiceover="尾巴缩回去了。我假装没看见",
            subtitle="尾巴缩回去了。 我假装没看见",
            duration_s=5,
            emotion_peak=False,
            shot_type="catalyst",
        ),
        Shot(
            shot_no=3,
            time_range="8-25s",
            scene="客厅→厨房→卫生间",
            camera="手持跟拍(背影移动)",
            action="我继续搬箱子进厨房、卫生间,回头瞄一眼,客厅安静",
            voiceover="搬了第5个,第6个,第7个",
            subtitle="搬了第 5 个,第 6 个,第 7 个",
            duration_s=17,
            emotion_peak=True,
            shot_type="rising_action",
        ),
        Shot(
            shot_no=4,
            time_range="25-32s",
            scene="客厅中央",
            camera="固定中景",
            action="我放下最后一个箱子,清点——少一个",
            voiceover="等等。猫呢?",
            subtitle="等等。 猫呢?",
            duration_s=7,
            emotion_peak=False,
            shot_type="discovery",
        ),
        Shot(
            shot_no=5,
            time_range="32-50s",
            scene="客厅纸箱堆",
            camera="手持跟拍(俯拍手部动作)",
            action="我开始翻箱子。第1个——空的。第2个——我的冬装",
            voiceover="翻了6个箱子。全是我自己的东西",
            subtitle="翻了 6 个箱子。 全是我自己的东西",
            duration_s=18,
            emotion_peak=True,
            shot_type="all_is_lost_setup",
        ),
        Shot(
            shot_no=6,
            time_range="50-57s",
            scene="客厅尽头最大纸箱",
            camera="固定特写(箱子侧面)",
            action="我盯着客厅尽头那个最大的箱子,慢慢走过去",
            voiceover="找到了",
            subtitle="找到了。",
            duration_s=7,
            emotion_peak=True,
            shot_type="midpoint",
        ),
        Shot(
            shot_no=7,
            time_range="57-60s",
            scene="客厅,大纸箱特写",
            camera="固定微距",
            action="我伸手想摸,YouKei 又缩回去了",
            voiceover="你到底在箱子里藏了什么?——是我吗",
            subtitle="你到底在箱子里藏了什么? ——是我吗",
            duration_s=3,
            emotion_peak=False,
            shot_type="final_image_hook",
        ),
    ]
    return EpisodeScript(
        ep=1,
        title="搬家日",
        logline="搬家日60平堆满纸箱,YouKei钻入最大箱子不出来",
        duration_target_s=60,
        shots=shots,
        hook=HookSpec(
            type=HookType.SUSPENSE,
            subtype="来者悬念",
            text="客厅尽头那个最大的纸箱,突然动了一下",
        ),
        satisfaction_types=["情感爆发"],
        next_episode_seed="EP02 第一夜,YouKei 不肯上床,蹲在搬进来的猫窝里瞪我",
        rhythm_notes="前3s钩子画面(箱子晃动露尾巴);15%情绪波峰(假装没看见的冷幽默);50%情绪波峰(翻遍6箱找不到);85%情绪波峰(半张脸探出) + 末3s悬念",
        self_check=SelfCheck(
            shot_count_ok=True,
            duration_in_range=True,
            emotion_peaks_count=3,
            hook_present=True,
            forbidden_words_check=True,
        ),
    )


@pytest.fixture
def ep01_script() -> EpisodeScript:
    return _make_ep01_script()


@pytest.fixture
def ep01_md(ep01_script: EpisodeScript) -> str:
    """渲染好的 EP01 markdown"""
    return render_episode(ep01_script)


# ===== Bug 1: frontmatter 应该只出现一次, 且必须在文档顶部 =====

class TestFrontmatterStructure:
    """markdown_renderer 输出 frontmatter 是设计如此 (给 obsidian-journal 解析),
    但必须只出现一次, 且必须在文档顶部。
    真正的 frontmatter 剥离在 obsidian-journal 渲染层 (lib/utils.ts stripFrontmatter)。
    """

    def test_frontmatter_at_top(self, ep01_md: str) -> None:
        """frontmatter 必须以 --- 开头 (即 markdown 文档最开头就是 ---)"""
        assert ep01_md.startswith("---\n"), "frontmatter 必须从文档最开头开始"

    def test_frontmatter_block_appears_exactly_once(self, ep01_md: str) -> None:
        """frontmatter 的 `---` 闭合符必须只出现 1 次"""
        # 文档里 --- 用作分隔符, 但 frontmatter 块只有 1 个
        # 数连续的 --- 模式 (--- 开头后跟非空字符): 应该是 2 个 (开闭)
        # 简单做法: 数 `slug:` 出现次数, 应只在 frontmatter 里 = 1
        assert ep01_md.count("slug:") == 1, (
            "slug 字段只能在前置 frontmatter 出现一次"
        )

    def test_external_meta_field_appears_once(self, ep01_md: str) -> None:
        """external_meta 嵌套字段必须只出现在 frontmatter 内"""
        assert ep01_md.count("external_meta:") == 1, (
            "external_meta 字段只能在前置 frontmatter 出现一次"
        )

    def test_no_frontmatter_in_body_after_h1(self, ep01_md: str) -> None:
        """H1 之后不应再有 frontmatter 字段"""
        # 找到 H1 位置, 之后的正文不应再有 raw YAML 字段
        h1_idx = ep01_md.find("\n# EP01")
        body = ep01_md[h1_idx:]
        assert "slug:" not in body, "H1 之后的正文不应再有 slug 字段"
        assert "category: life" not in body, "H1 之后的正文不应再有 category 字段"
        assert "external_meta:" not in body, "H1 之后的正文不应再有 external_meta 字段"


# ===== Bug 2: 标题重复 =====

class TestTitleNoDuplication:
    """H1 应该只出现 1 次, 标题内容不应重复"""

    def test_h1_appears_exactly_once(self, ep01_md: str) -> None:
        """# EP01 这种 H1 应该只出现 1 次"""
        # 数所有 "EP01 · " 出现次数, 应该 = 1 (H1) + 1 (frontmatter title) = 2
        count = ep01_md.count("EP01 · ")
        assert count == 2, (
            f"标题 'EP01 · ' 出现 {count} 次, 应该是 2 次 (frontmatter + H1)"
        )

    def test_h1_contains_ep_number(self, ep01_md: str) -> None:
        """H1 必须包含 EP 编号 (老板截图里 H1 只有 '📦 搬家日', 缺 EP01)"""
        lines = ep01_md.split("\n")
        h1_lines = [l for l in lines if l.startswith("# ")]
        assert len(h1_lines) == 1, f"应该只有 1 个 H1, 实际 {len(h1_lines)} 个"
        assert "EP01" in h1_lines[0], f"H1 必须含 EP01: {h1_lines[0]}"


# ===== Bug 3: emoji 不统一 =====

class TestEmojiConsistency:
    """H1 不应有 emoji, 只在 chip / logline / 章节标题用"""

    def test_h1_has_no_emoji(self, ep01_md: str) -> None:
        """H1 不应有 emoji (老板截图里 '# 📺 EP01 · 📦 搬家日' 是错的)"""
        lines = ep01_md.split("\n")
        h1 = next(l for l in lines if l.startswith("# "))
        # H1 允许中文 / 数字 / 空格 / ·, 不允许 emoji
        # 简单判定: 不含 📺 📦 🎬 这些
        assert "📺" not in h1, f"H1 不应有 📺: {h1}"
        assert "📦" not in h1, f"H1 不应有 📦: {h1}"


# ===== Bug 4: meta 信息 chip 化 =====

class TestMetaChipStyle:
    """meta 信息应该是 chip 样式, 不是裸 inline"""

    def test_meta_line_has_chip_format(self, ep01_md: str) -> None:
        """meta 行应该是 | ⏱️ ... | 样式"""
        assert "| ⏱️" in ep01_md, (
            "meta 应该 chip 化, 如 `| ⏱️ 60s | 🎞️ 7 shots |`"
        )
        assert "| 🎞️" in ep01_md

    def test_no_old_inline_meta(self, ep01_md: str) -> None:
        """顶部 meta 行不应再用 `**时长**:` 这种裸 inline 样式 (shot 字段里的 `**时长**:` 是允许的)"""
        # 找到 H1 之后的第一段, 验证它是 chip 格式而非裸 inline
        lines = ep01_md.split("\n")
        # 找第一个 H1 行
        h1_idx = next(i for i, l in enumerate(lines) if l.startswith("# "))
        # H1 之后到 --- 之间的几行就是 meta 区
        meta_lines: list[str] = []
        for l in lines[h1_idx + 1:]:
            if l.strip() == "---":
                break
            meta_lines.append(l)
        meta_text = "\n".join(meta_lines)
        # 顶部 meta 区不应该有 `**时长**:` 这种裸 inline
        assert "**时长**:" not in meta_text, (
            "顶部 meta 区不应该再用 `**时长**: 60s` 这种裸 inline 样式, 应改为 chip 格式"
        )
        assert "**镜头**:" not in meta_text, "顶部 meta 区不应该用 `**镜头**:` 裸 inline"


# ===== 渲染完整性 =====

class TestRenderIntegrity:
    """整体结构完整, 不漏内容"""

    def test_contains_all_sections(self, ep01_md: str) -> None:
        """必须包含所有关键 section"""
        for marker in [
            "## 🎬 钩子",
            "## 🎞️ 分镜",
            "## 🎵 节奏提示",
            "## ✨ 爽点类型",
            "## ✅ Writer 自检",
            "## 👀 下集预告",
        ]:
            assert marker in ep01_md, f"缺少 section: {marker}"

    def test_contains_all_shots(self, ep01_md: str) -> None:
        """7 个 shot 必须全部出现"""
        for i in range(1, 8):
            assert f"### Shot {i}" in ep01_md, f"缺少 Shot {i}"

    def test_logline_present(self, ep01_md: str) -> None:
        """logline 应该出现 (作为 blockquote)"""
        assert "搬家日60平堆满纸箱" in ep01_md

    def test_no_excessive_separator(self, ep01_md: str) -> None:
        """不应该有过多分割线 (老板截图里每个 section 都有 `---`, 视觉太碎)"""
        # 老板截图里大约 8 个 `---`
        # 修复后应该 ≤ 6 个
        sep_count = ep01_md.count("\n---\n")
        assert sep_count <= 6, f"分割线太多 ({sep_count} 个), 视觉太碎, 应 ≤ 6 个"