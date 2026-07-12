"""
markdown_renderer.py — EpisodeScript → Markdown 渲染

职责:
- 把 EpisodeScript 渲染成 obsidian-journal 可消费的 Markdown
- 包含: 标题 / 钩子 / shots / 节奏分析 / 红线自检 / 下集预告

调用方:
- src/daily.py (P9 主流程)
- scripts/render-preview.py (单独调试)

设计:
- 模板硬编码 (不引入 jinja2, 简单可读)
- 输出格式: GitHub-flavored Markdown + 中文标点
- 自动生成 TOC (基于 hook + shots)
"""

from __future__ import annotations

from datetime import datetime

from src.types import EpisodeScript, SelfCheck


def render_episode(script: EpisodeScript) -> str:
    """把 EpisodeScript 渲染成 Markdown

    Args:
        script: 已通过 HardCheck + Memory 校验的剧本

    Returns:
        Markdown 字符串 (含 YAML frontmatter, 方便 obsidian-journal 解析)
    """
    lines: list[str] = []

    # ===== YAML Frontmatter (obsidian-journal 解析用) =====
    lines.append("---")
    lines.append(f'title: "EP{script.ep:02d} · {script.title}"')
    lines.append(f"slug: yk-s01-ep{script.ep:02d}")
    lines.append("category: life")
    tags = [
        "YouKei",
        "缅因猫",
        "上坤×YouKei",  # noqa: RUF001
        f"季01-EP{script.ep:02d}",
        "单元剧",
    ]
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append("external_meta:")
    lines.append("  source: yk-script-p9")
    lines.append(f"  ep: {script.ep}")
    lines.append(f"  duration_s: {script.total_duration_s}")
    lines.append(f"  shot_count: {len(script.shots)}")
    lines.append("---")
    lines.append("")

    # ===== 标题 + 元信息 =====
    lines.append(f"# 📺 EP{script.ep:02d} · {script.title}")
    lines.append("")
    lines.append(f"> {script.logline}")
    lines.append("")
    lines.append(
        f"**时长**: {script.total_duration_s}s · "
        f"**镜头**: {len(script.shots)} · "
        f"**钩子**: {script.hook.type.value if script.hook.type else '无 (EP12 季末)'}",
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 钩子 (0-3s) =====
    if script.hook.text:
        lines.append("## 🎬 钩子 (0-3s)")
        lines.append("")
        lines.append(f"> **{script.hook.type.value}** · {script.hook.subtype or ''}")
        lines.append("")
        lines.append(f"_{script.hook.text}_")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ===== Shots 分镜 =====
    lines.append("## 🎞️ 分镜")
    lines.append("")
    for shot in script.shots:
        peak_mark = " 🔥" if shot.emotion_peak else ""
        lines.append(f"### Shot {shot.shot_no} · {shot.time_range}{peak_mark}")
        lines.append("")
        lines.append(f"- **场景**: {shot.scene}")
        lines.append(f"- **机位**: {shot.camera}")
        lines.append(f"- **动作**: {shot.action}")
        if shot.voiceover:
            lines.append(f"- **画外音**: _{shot.voiceover}_")
        if shot.subtitle:
            lines.append(f"- **字幕**: `{shot.subtitle}`")
        lines.append(f"- **时长**: {shot.duration_s}s · **类型**: {shot.shot_type}")
        lines.append("")

    lines.append("---")
    lines.append("")

    # ===== 节奏分析 =====
    if script.rhythm_notes:
        lines.append("## 🎵 节奏提示")
        lines.append("")
        lines.append(script.rhythm_notes)
        lines.append("")

    if script.peak_positions:
        pos_str = ", ".join(f"{p:.0f}%" for p in script.peak_positions)
        lines.append(f"**情绪波峰位置**: {pos_str} (理想: 15% / 50% / 85%)")
        lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 爽点 + 类型 =====
    lines.append("## ✨ 爽点类型")
    lines.append("")
    satisfaction_str = " · ".join(s.value for s in script.satisfaction_types)
    lines.append(f"**{satisfaction_str}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== Writer 自检 (5 项) =====
    lines.append("## ✅ Writer 自检")
    lines.append("")
    sc: SelfCheck = script.self_check
    check_items = [
        ("镜头数 3-8", sc.shot_count_ok),
        ("时长在 30-90s", sc.duration_in_range),
        (f"情绪波峰数 {sc.emotion_peaks_count}", sc.emotion_peaks_count >= 1),
        ("钩子存在", sc.hook_present),
        ("无 forbidden words", sc.forbidden_words_check),
    ]
    for label, ok in check_items:
        mark = "✅" if ok else "❌"
        lines.append(f"- {mark} {label}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ===== 下集预告 =====
    if script.next_episode_seed:
        lines.append("## 👀 下集预告")
        lines.append("")
        lines.append(f"_{script.next_episode_seed}_")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ===== Footer =====
    lines.append("---")
    lines.append("")
    lines.append(
        f"*由黑 (Hei) 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
        f"Pipeline: Writer → Critic → HardCheck → Memory → Render*",
    )
    lines.append("")

    return "\n".join(lines)


def render_preview(script: EpisodeScript) -> str:
    """极简预览版本 (用于调试 / dry-run 输出)

    Args:
        script: 任意 EpisodeScript

    Returns:
        简化版 Markdown (仅含 title + logline + shots 简表)
    """
    lines = [
        f"# {script.title}",
        "",
        f"> {script.logline}",
        "",
        f"**EP{script.ep}** · {script.total_duration_s}s · {len(script.shots)} shots",
        "",
        "## Shots",
        "",
    ]
    for shot in script.shots:
        peak = "🔥 " if shot.emotion_peak else ""
        lines.append(
            f"- {peak}**{shot.time_range}** {shot.scene} - {shot.action[:40]}...",
        )
    return "\n".join(lines)
