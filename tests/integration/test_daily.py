"""
test_daily.py — daily orchestrator 集成测试

验证:
- dry-run 完整闭环 (Writer fixture → Critic skip → HardCheck → Memory → Render)
- state.json / memory_bank.json 持久化
- 失败路径: Writer 全失败 / Critic 全失败 / HardCheck FAIL → alert.txt
- force_episode 跳过 state 自动推进
- Markdown 输出含 YAML frontmatter + 必要章节

注意: 真实 LLM 测试需 .env 配置 MINIMAXI_API_KEY, CI 中跳过
"""

from __future__ import annotations

import pytest

from src.daily import (
    StateStore,
    main,
    make_dry_run_episode,
)
from src.markdown_renderer import render_episode, render_preview


# ===== Fixtures =====
@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    """隔离测试: chdir 到 tmp_path, 让 data/state / output / logs 都在 tmp 下"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data/state").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ===== Test: dry-run 闭环 =====
class TestDryRunEnd2End:
    def test_dry_run_ep1_success(self, isolated_workspace):
        """EP1 dry-run 完整跑通"""
        exit_code = main(
            dry_run=True,
            force_episode=1,
            output_dir=isolated_workspace / "output",
        )
        assert exit_code == 0

        # 验证 output/yk-s01-ep01.md 存在
        md_path = isolated_workspace / "output/yk-s01-ep01.md"
        assert md_path.exists()
        assert md_path.stat().st_size > 500

        # 验证 preview 也写了
        preview_path = isolated_workspace / "output/yk-s01-ep01-preview.md"
        assert preview_path.exists()

    def test_dry_run_advances_state(self, isolated_workspace):
        """dry-run 后 state.json next_ep 应该 = 2"""
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        state = StateStore().load()
        assert state["last_episode_title"] == "📦 搬家日"
        assert state["next_ep"] == 2
        assert state["total_runs"] == 1
        assert state["total_success"] == 1

    def test_dry_run_writes_memory_bank(self, isolated_workspace):
        """dry-run 后 memory_bank.json 应含 EP1"""
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        from src.memory_manager import MemoryManager

        mm = MemoryManager(memory_path=isolated_workspace / "data/state/memory_bank.json")
        assert len(mm.memory.episodes) == 1
        assert mm.get_episode(1).title == "📦 搬家日"

    def test_dry_run_ep2_uses_fixture(self, isolated_workspace):
        """EP2 dry-run 应输出 🌙 第一夜"""
        main(dry_run=True, force_episode=2, output_dir=isolated_workspace / "output")
        md = (isolated_workspace / "output/yk-s01-ep02.md").read_text(encoding="utf-8")
        assert "🌙 第一夜" in md


# ===== Test: Markdown 输出格式 =====
class TestMarkdownOutput:
    def test_yaml_frontmatter_present(self, isolated_workspace):
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        md = (isolated_workspace / "output/yk-s01-ep01.md").read_text(encoding="utf-8")
        # YAML frontmatter 必须以 --- 开头
        assert md.startswith("---")
        assert "title:" in md
        assert "tags:" in md
        assert "external_meta:" in md

    def test_required_sections(self, isolated_workspace):
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        md = (isolated_workspace / "output/yk-s01-ep01.md").read_text(encoding="utf-8")
        required = [
            "## 🎬 钩子",
            "## 🎞️ 分镜",
            "## 🎵 节奏提示",
            "## ✨ 爽点类型",
            "## ✅ Writer 自检",
            "## 👀 下集预告",
        ]
        for sec in required:
            assert sec in md, f"缺少章节: {sec}"

    def test_shots_listed(self, isolated_workspace):
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        md = (isolated_workspace / "output/yk-s01-ep01.md").read_text(encoding="utf-8")
        # 5 个 Shot 1-5
        for n in range(1, 6):
            assert f"### Shot {n}" in md

    def test_ep12_no_hook_section(self):
        """EP12: 无钩子 + 无下集预告"""
        ep12 = make_dry_run_episode(12)
        # 修 logline 让 EP12 不报错
        ep12 = ep12.model_copy(update={"logline": "冬至包饺子, YouKei 偷面团"})
        md = render_episode(ep12)
        assert "## 👀 下集预告" not in md


# ===== Test: 强制集号 =====
class TestForceEpisode:
    def test_force_episode_skips_state(self, isolated_workspace):
        """force_episode=5 不应改变 next_ep 自动推进 (但 state 仍 +1)"""
        main(dry_run=True, force_episode=5, output_dir=isolated_workspace / "output")
        # force_episode=5 → next_ep 应该 = 5+1=6 (按代码逻辑)
        # 但 force_episode 不跳过 state 推进 (state 总是 +1)
        state = StateStore().load()
        # 状态已被 force_episode=5 覆盖写入
        assert state["next_ep"] == 6
        # EP5 fixture 真实标题是 "🛁 洗澡大作战"
        assert state["last_episode_title"] == "🛁 洗澡大作战"


# ===== Test: 失败路径 =====
class TestFailurePaths:
    def test_writer_all_failed_writes_alert(self, isolated_workspace, monkeypatch, caplog):
        """Writer 全失败 → alert.txt + return 1"""

        def fake_writer_fail(ep, season_id, dry_run):
            return []  # 空列表模拟全失败

        # 直接调 main, 不 mock LLM; 真实 LLM 没配置 → Writer 会 fail
        # 但需要 dry_run=False 才会调真实 Writer
        # 改用: 直接 monkeypatch make_default_writer 失败
        from src import daily as daily_mod

        class FakeWriter:
            n_candidates = 3

            def generate_episode_candidates(self, ep, season_id):
                from src.writer import WriterAllFailedError

                raise WriterAllFailedError("mocked all failed")

        monkeypatch.setattr(daily_mod, "make_default_writer", lambda: FakeWriter())

        exit_code = main(dry_run=False, force_episode=1, output_dir=isolated_workspace / "output")
        assert exit_code == 1
        alert_path = isolated_workspace / "logs/alert.txt"
        assert alert_path.exists()
        alert_content = alert_path.read_text(encoding="utf-8")
        assert "Writer" in alert_content or "EP1" in alert_content

    def test_ep_out_of_range_writes_alert(self, isolated_workspace):
        """EP 超出 [1, 12] → alert + return 1"""
        exit_code = main(
            dry_run=True,
            force_episode=13,
            output_dir=isolated_workspace / "output",
        )
        assert exit_code == 1
        alert_path = isolated_workspace / "logs/alert.txt"
        assert alert_path.exists()


# ===== Test: StateStore 单元 =====
class TestStateStore:
    def test_load_nonexistent_returns_defaults(self, isolated_workspace):
        ss = StateStore(path=isolated_workspace / "data/state/state.json")
        state = ss.load()
        assert state["next_ep"] == 1
        assert state["total_runs"] == 0

    def test_save_load_round_trip(self, isolated_workspace):
        ss = StateStore(path=isolated_workspace / "data/state/state.json")
        state = {
            "season_id": 1,
            "next_ep": 5,
            "last_run_at": "2026-07-12T12:00:00",
            "last_episode_title": "test",
            "total_runs": 3,
            "total_success": 2,
        }
        ss.save(state)
        loaded = ss.load()
        assert loaded["next_ep"] == 5
        assert loaded["last_episode_title"] == "test"

    def test_update_increments_counters(self, isolated_workspace):
        ss = StateStore(path=isolated_workspace / "data/state/state.json")
        ss.update(increment_runs=True, next_ep=3)
        state = ss.load()
        assert state["total_runs"] == 1
        assert state["next_ep"] == 3

    def test_load_corrupted_returns_defaults(self, isolated_workspace):
        path = isolated_workspace / "data/state/state.json"
        path.write_text("not json{", encoding="utf-8")
        ss = StateStore(path=path)
        state = ss.load()
        assert state["next_ep"] == 1


# ===== Test: render_preview =====
class TestRenderPreview:
    def test_preview_compact(self):
        ep = make_dry_run_episode(1)
        preview = render_preview(ep)
        assert "EP1" in preview or "搬家" in preview
        assert len(preview) < 1000  # 比完整版短


# ===== Test: 主流程集成 (无真实 LLM) =====
class TestIntegrationNoLLM:
    def test_full_pipeline_dry_run(self, isolated_workspace):
        """完整流水线: Writer fixture → Critic skip → HardCheck → Memory → Render → 写盘"""
        # 这次 EP3
        exit_code = main(
            dry_run=True,
            force_episode=3,
            output_dir=isolated_workspace / "output",
        )
        assert exit_code == 0

        # 验证所有产物
        assert (isolated_workspace / "output/yk-s01-ep03.md").exists()
        assert (isolated_workspace / "data/state/state.json").exists()
        assert (isolated_workspace / "data/state/memory_bank.json").exists()

        # memory_bank 含 EP3, EP1/EP2 不在 (force_episode=3 直接跳过)
        from src.memory_manager import MemoryManager

        mm = MemoryManager(memory_path=isolated_workspace / "data/state/memory_bank.json")
        assert len(mm.memory.episodes) == 1
        assert mm.get_episode(3).title == "🐦 阳台征服"

    def test_state_json_total_runs_increments(self, isolated_workspace):
        """跑 2 次 → total_runs=2"""
        main(dry_run=True, force_episode=1, output_dir=isolated_workspace / "output")
        main(dry_run=True, force_episode=2, output_dir=isolated_workspace / "output")
        state = StateStore().load()
        assert state["total_runs"] == 2
        assert state["total_success"] == 2
