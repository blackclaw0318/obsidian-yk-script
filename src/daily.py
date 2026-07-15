"""
daily.py — 主入口 orchestrator (cron 06:00 触发)

职责 (v0.3 文档 §3.6):
- 全链路编排: Writer → Critic → HardCheck → Memory → Render → Publish
- 状态持久化 (state.json + memory_bank.json)
- 失败告警 (logs/alert.txt + 返回非 0 exit code)
- dry-run 模式 (不调 LLM / 不推送, 只生成 md → output/)

调用方:
- cron / systemd timer 06:00 每日触发
- 手动: python -m src.daily --dry-run [--force-episode N]

设计原则:
- 任一关键阶段失败 → 写 alert + return 1 (老板 cron 兜底推送微信)
- 不阻塞日志: 每步独立 logger
- P11-P14 (GitHub 拉大纲 / 备份 / 微信 notifier) 暂未实现, 用 TODO 占位
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv  # P11+P13 fix: 手动跑 cli() 自动读 .env

from src.backup import Backup, BackupError, EpisodeMeta  # P13
from src.critic import make_default_critic
from src.hard_check import HardCheckResult, make_default_checker
from src.markdown_renderer import render_episode, render_preview
from src.memory_manager import MemoryManager

# v0.3 增项
from src.outline_fetcher import fetch_season_with_fallback  # P11
from src.publisher import (  # P12
    EpisodePayload,
    get_post_url,
    make_default_publisher,
)
from src.types import EpisodeScript, HookSpec, HookType, SatisfactionType, SelfCheck, Shot
from src.wechat_notifier import (  # P14
    WechatNotifierConfig,
)
from src.wechat_notifier import (
    notify_backup_warning as wechat_notify_backup_warning,
)
from src.wechat_notifier import (
    notify_failure as wechat_notify_failure,
)
from src.wechat_notifier import (
    notify_success as wechat_notify_success,
)
from src.writer import WriterAllFailedError, make_default_writer

logger = logging.getLogger("yk-script.daily")


# ===== 状态持久化 =====
@dataclass
class StateStore:
    """记录全局状态 (data/state/state.json, gitignored)

    与 memory_bank.json 的区别:
    - memory_bank: 业务状态 (跨集记忆)
    - state.json: 工程状态 (last_run_at / next_ep / season_id / 累计统计)
    """

    path: Path = Path("data/state/state.json")

    def load(self) -> dict:
        if not self.path.exists():
            return {
                "season_id": 1,
                "next_ep": 1,
                "last_run_at": "",
                "last_episode_title": "",
                "total_runs": 0,
                "total_success": 0,
            }
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"state.json 损坏 ({e}), 重置")
            return {
                "season_id": 1,
                "next_ep": 1,
                "last_run_at": "",
                "last_episode_title": "",
                "total_runs": 0,
                "total_success": 0,
            }

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # atomic write
        import os
        import tempfile

        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state.", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            if Path(tmp).exists():
                Path(tmp).unlink()
            raise

    def update(
        self,
        *,
        next_ep: int | None = None,
        last_episode_title: str | None = None,
        increment_runs: bool = False,
        increment_success: bool = False,
    ) -> dict:
        state = self.load()
        state["total_runs"] = state.get("total_runs", 0) + (1 if increment_runs else 0)
        state["total_success"] = state.get("total_success", 0) + (1 if increment_success else 0)
        state["last_run_at"] = datetime.now().isoformat(timespec="seconds")
        if next_ep is not None:
            state["next_ep"] = next_ep
        if last_episode_title is not None:
            state["last_episode_title"] = last_episode_title
        self.save(state)
        return state


# ===== Dry-run Fixture =====
def make_dry_run_episode(ep: int = 1) -> EpisodeScript:
    """Dry-run 模式: 不调 LLM, 返回预生成合规 EpisodeScript

    用途:
    - 验证 daily.py 主流程 (Writer → Critic → HardCheck → Memory → Render)
    - 调试 Markdown 渲染
    - 不消耗 LLM token
    """
    titles = {
        1: "📦 搬家日",
        2: "🌙 第一夜",
        3: "🐦 阳台征服",
        4: "🐟 厨房事变",
        5: "🛁 洗澡大作战",
    }
    loglines = {
        1: "搬家日, 60 平里全是纸箱, YouKei 钻进最大纸箱不出来",
        2: "第一夜, YouKei 不敢上床, 蜷在客厅纸箱里",
        3: "阳台征服, YouKei 学会跳窗台看鸟",
        4: "厨房事变, YouKei 偷吃三文鱼",
        5: "洗澡大作战, YouKei 第一次接触水",
    }
    is_ep12 = ep == 12
    shots = [
        Shot(
            shot_no=1,
            time_range="0-3s",
            scene="客厅",
            camera="固定机位",
            action="主人搬第 3 个箱子, 突然听到纸箱里传来窸窣声",
            voiceover="我以为我在搬家",
            subtitle="什么声音？",  # noqa: RUF001
            duration_s=5,
            emotion_peak=True,
            shot_type="establishing",
        ),
        Shot(
            shot_no=2,
            time_range="3-12s",
            scene="客厅",
            camera="跟拍",
            action="走近纸箱, 掀开一角, YouKei 大眼睛眨巴看着镜头",
            voiceover="一打开, 里面是个毛茸茸的家伙",
            subtitle="喵～",  # noqa: RUF001
            duration_s=9,
            emotion_peak=False,
            shot_type="reaction",
        ),
        Shot(
            shot_no=3,
            time_range="12-25s",
            scene="客厅",
            camera="侧面",
            action="YouKei 钻出纸箱, 在纸箱堆间穿梭, 尾巴扫过相机镜头上方",
            voiceover="她倒是不认生, 当自己家了",
            subtitle="当自己家了",
            duration_s=13,
            emotion_peak=True,
            shot_type="other",
        ),
        Shot(
            shot_no=4,
            time_range="25-40s",
            scene="客厅",
            camera="俯拍",
            action="主人继续搬箱子, YouKei 追着纸箱跑",
            voiceover="搬家变成了陪跑",
            subtitle="陪跑",
            duration_s=15,
            emotion_peak=False,
            shot_type="dialogue",
        ),
        Shot(
            shot_no=5,
            time_range="40-60s",
            scene="客厅",
            camera="特写",
            action="主人累倒在沙发上, YouKei 跳上主人胸口, 一起睡着",
            voiceover="累, 但值",
            subtitle="累, 但值",
            duration_s=20,
            emotion_peak=True,
            shot_type="finale",
        ),
    ]
    return EpisodeScript(
        ep=ep,
        title=titles.get(ep, f"EP{ep} 默认标题"),
        logline=loglines.get(ep, f"EP{ep} 默认剧情"),
        shots=shots,
        hook=HookSpec(
            type=None if is_ep12 else HookType.SUSPENSE,
            subtype="来者悬念",
            text=None if is_ep12 else "客厅尽头那个最大的纸箱, 突然动了一下",
        ),
        satisfaction_types=[SatisfactionType.EMOTION, SatisfactionType.REVEAL],
        next_episode_seed=None if is_ep12 else f"EP{ep + 1} 第一夜, YouKei 不敢上床",
        rhythm_notes="前 5s 必现冲突 (纸箱响动), 末 5s 温馨收束",
        self_check=SelfCheck(
            shot_count_ok=True,
            duration_in_range=True,
            emotion_peaks_count=3,
            hook_present=(not is_ep12),
            forbidden_words_check=True,
        ),
    )


# ===== P11: 拉取大纲 (辅助, 失败不阻塞) =====


def _run_outline_pull(season_id: int) -> None:
    """P11: 从 GitHub 拉大纲 (3 级 fallback)

    失败不阻塞主流程 (daily 业务不依赖 outline, Writer 用本地 schema 生成)。
    仅逻辑上拉一下, 验证 token 可用 + 充本地缓存供人类审阅。
    """
    try:
        data, source = fetch_season_with_fallback(season_id=season_id)
        logger.info(
            f"✅ Outline S{season_id:02d} loaded (source={source}, "
            f"episodes={len(data.get('episodes', []))}, "
            f"total={data.get('total_episodes', '?')})",
        )
    except Exception as e:
        logger.warning(f"⚠️ P11 outline pull 失败 (已降级到本地或不运行): {e}")


# ===== P12 + P13: publish + backup =====


def _run_publish_and_backup(
    *,
    md: str,
    season_id: int,
    episode_idx: int,
    title: str,
    word_count: int,
    duration_s: int,
) -> tuple[object | None, str, str | None]:
    """Publish + Backup 串联.

    Returns:
        (backup_result, post_url, err)
        - err 非 None 表示 publish 整个级联失败 (含 backup)
        - backup_result / post_url 都可能为 "不动某一下次" 状态
    """
    # P12: 推送 obsidian-journal
    publisher = make_default_publisher()
    if publisher is None:
        return None, "", "Publisher 凭据缺失 (OBSIDIAN_PUBLISH_URL / SECRET)"

    payload = EpisodePayload(
        season_id=season_id,
        episode_idx=episode_idx,
        title=title,
        content_md=md,
        word_count=word_count,
    )
    try:
        publish_resp = publisher.push_one(payload)
        post_url = get_post_url(publish_resp)
        logger.info(f"✅ Published: {payload.slug} -> {post_url}")
    except Exception as e:
        return None, "", f"Publish 失败 ({type(e).__name__}): {str(e)[:200]}"

    # P13: GitHub 备份 (失败不阻塞, 但返回 None)
    token = os.environ.get("GITHUB_BACKUP_TOKEN", "")
    if not token:
        logger.warning("[daily] GITHUB_BACKUP_TOKEN 未设置, 跳过 backup")
        return None, post_url, None

    try:
        backup = Backup(token=token)
        meta = EpisodeMeta.now(
            season_id=season_id,
            episode_idx=episode_idx,
            title=title,
            word_count=word_count,
            post_url=post_url,
        )
        result = backup.upload(md=md, meta=meta)
        return result, post_url, None
    except BackupError as e:
        logger.warning(f"[daily] Backup 失败 (不阻塞): {e}")
        # 返回 (None, post_url, None) 表示 publish OK + backup FAILED
        # 调用者根据 pub_url 存在与 backup_result 为 None 决定发 backup_warning
        return _BackupFailureMarker(), post_url, None


# sentinel marker class for "backup failed but publish succeeded"
class _BackupFailureMarker:
    """轻量标记类, 让 _run_publish_and_backup 返回值可判别 backup 状态"""

    def __init__(self):
        self.commit_sha = ""
        self.pushed_files: list[str] = []


def _count_words(md: str) -> int:
    """中文字数计数 (粗估, 按 '字符数 - 标点数')"""
    text = md
    count = 0
    for ch in text:
        # 中文 UTF-8 高位
        if "\u4e00" <= ch <= "\u9fff":
            count += 1
    return count
def main(
    dry_run: bool = False,
    force_episode: int | None = None,
    season_id: int = 1,
    output_dir: Path = Path("output"),
) -> int:
    """daily orchestrator 主入口

    Args:
        dry_run: True = 跳过 LLM, 用 fixture; 跳过 publish, 只写 md → output/
        force_episode: 老板指定要重生成的集号 (1-12), 跳过 state.json 自动推进
        season_id: 季号 (默认 1)
        output_dir: dry-run 输出目录

    Returns:
        exit code: 0 = 成功, 1 = 失败
    """
    start = datetime.now()
    logger.info(f"=== yk-script daily run start: {start.isoformat()} ===")
    logger.info(f"mode: {'DRY-RUN' if dry_run else 'PRODUCTION'}")

    state_store = StateStore()
    state = state_store.load()
    state_store.update(increment_runs=True)
    state["season_id"] = season_id  # 同步季节参数

    # 0. P11: 拉取大纲 (3 级 fallback, 失败不阻塞)
    _run_outline_pull(season_id)

    # 1. 决定本集
    target_ep = force_episode or state.get("next_ep", 1)
    if target_ep < 1 or target_ep > 12:
        _alert_failure(f"EP{target_ep}", ["target_ep 超出 [1, 12] 范围"])
        return 1
    logger.info(f"目标集: S{season_id:02d}-EP{target_ep:02d}")

    mm = MemoryManager()

    # 2. Writer → 3 候选
    candidates = _run_writer(target_ep, season_id, dry_run)
    if not candidates:
        _alert_failure(f"EP{target_ep}", ["Writer 全部失败"])
        return 1

    # 2.5 P1.3: 加载本集 episode_spec + season_context 供 Critic 用
    from src.outline_fetcher import fetch_season_with_fallback as _fetch_season
    ep_spec_for_critic: dict | None = None
    season_ctx_for_critic: dict | None = None
    try:
        _season, _src = _fetch_season(season_id)
        _ep = next((e for e in _season.get("episodes", []) if e.get("ep") == target_ep), None)
        if _ep is not None:
            ep_spec_for_critic = _ep
            # 复用 writer._build_season_context 的逻辑
            from src.writer import Writer as _W
            class _StubClient:
                pass
            season_ctx_for_critic = _W(_StubClient())._build_season_context(_season, _ep)
            logger.info(f"P1.3: Critic 注入 EP{target_ep} spec (hook={ep_spec_for_critic.get('hook_type')})")
    except Exception as _e:
        logger.warning(f"P1.3: 加载 season_context 给 Critic 失败 ({_e}), Critic 仅主观评分")

    # 3. Critic → 5 维评分 → 选最优
    best_script = _run_critic(candidates, dry_run, ep_spec_for_critic, season_ctx_for_critic)
    if best_script is None:
        _alert_failure(f"EP{target_ep}", ["Critic 评审全部失败"])
        return 1

    # 4. HardCheck → 19 红线 + 5 结构
    hc_result = _run_hard_check(best_script)
    if hc_result is None or not hc_result.should_publish:
        violations = hc_result.violations if hc_result else []
        errors = [f"{v.constraint_id}: {v.evidence}" for v in violations]
        _alert_failure(f"EP{target_ep} '{best_script.title}'", errors or ["HardCheck 失败"])
        return 1

    # 5. Memory → 跨集硬约束 + 写入
    memory_ok = _run_memory(mm, best_script)
    if not memory_ok:
        _alert_failure(
            f"EP{target_ep} '{best_script.title}'",
            ["Memory 跨集硬约束失败"],
        )
        return 1

    # 6. Render → Markdown
    md = render_episode(best_script)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"yk-s{season_id:02d}-ep{target_ep:02d}.md"
    output_path.write_text(md, encoding="utf-8")
    logger.info(f"✅ Markdown 写入: {output_path} ({len(md)} chars)")

    # 7. Publish / Backup / Wechat (v0.3 P12/13/14)
    if dry_run:
        logger.info(f"DRY-RUN: 跳过 publish/backup/wechat, 已写入 {output_path}")
        preview_path = output_dir / f"yk-s{season_id:02d}-ep{target_ep:02d}-preview.md"
        preview_path.write_text(render_preview(best_script), encoding="utf-8")
        logger.info(f"DRY-RUN: 预览写入 {preview_path}")
    else:
        # P12: 实推送 obsidian-journal
        # P13: 推送成功后实备份到 GitHub
        # P14: 根据上面阶段状态推微信
        publish_result, post_url, episode_err = _run_publish_and_backup(
            md=md,
            season_id=season_id,
            episode_idx=target_ep,
            title=best_script.title,
            word_count=_count_words(md),
            duration_s=best_script.total_duration_s,
        )

        # 推送级联 状态:
        #  1) publish 失败 -> wechat 失敗告警 -> daily return 1
        #  2) publish 成功 + backup 成功 -> wechat 成功 -> return 0
        #  3) publish 成功 + backup 失败 -> wechat 警告 -> return 0 (推送已成功)
        if episode_err is not None:
            _alert_failure(
                f"S{season_id:02d}-EP{target_ep:02d} '{best_script.title}'",
                [episode_err],
            )
            # P14: 推送失败 微信告警
            wechat_cfg = WechatNotifierConfig.from_env()
            wechat_notify_failure(
                wechat_cfg,
                season_id=season_id,
                episode_idx=target_ep,
                title=best_script.title,
                error_short=episode_err[:200],
            )
            return 1

        if publish_result and publish_result.commit_sha:
            # backup 成功
            logger.info(
                f"[daily] ✅ publish + backup 完成: post={post_url} commit={publish_result.commit_sha[:12]}",
            )
            wechat_cfg = WechatNotifierConfig.from_env()
            wechat_notify_success(
                wechat_cfg,
                season_id=season_id,
                episode_idx=target_ep,
                title=best_script.title,
                word_count=_count_words(md),
                duration_s=best_script.total_duration_s,
                post_url=post_url,
            )
        else:
            # 推送成功 + 备份失败 (publish_result 是 None + post_url 存在但 backup fail)
            logger.warning("[daily] 推送成功但备份失败")
            # post_url 可能为 "" 或 "" 如本地 publish 临时返回; wechat 发警告
            wechat_cfg = WechatNotifierConfig.from_env()
            # 发送 backup warning (post_url 可能不是正式 URL)
            wechat_notify_backup_warning(
                wechat_cfg,
                season_id=season_id,
                episode_idx=target_ep,
                title=best_script.title,
                backup_error="GitHub backup failed (see logs/yk-daily.log)",
            )

    # 8. 更新 state + memory
    mm.save()
    state_store.update(
        next_ep=target_ep + 1 if target_ep < 12 else 1,  # 12 集后回 EP1 (下一季)
        last_episode_title=best_script.title,
        increment_success=True,
    )

    duration = (datetime.now() - start).total_seconds()
    logger.info(
        f"=== yk-script daily run END: {duration:.1f}s, "
        f"ep='{best_script.title}', "
        f"shots={len(best_script.shots)}, dur={best_script.total_duration_s}s ===",
    )
    return 0


# ===== 阶段包装器 =====
def _run_writer(
    ep: int,
    season_id: int,
    dry_run: bool,
) -> list[EpisodeScript]:
    """Stage 2: Writer 生成候选"""
    if dry_run:
        script = make_dry_run_episode(ep)
        logger.info(f"[DRY-RUN] Writer 模拟输出 EP{ep}: {script.title}")
        return [script]

    try:
        writer = make_default_writer()
        result = writer.generate_episode_candidates(ep, season_id)
        logger.info(
            f"Writer: {len(result.successful)}/{len(result.candidates)} 候选成功, "
            f"tokens={result.total_tokens}",
        )
        return [c.script for c in result.successful if c.script is not None]
    except WriterAllFailedError as e:
        logger.error(f"Writer 全部失败: {e}")
        return []
    except Exception as e:
        logger.exception(f"Writer 异常: {e}")
        return []


def _run_critic(
    candidates: list[EpisodeScript],
    dry_run: bool,
    episode_spec: dict | None = None,  # P1.3
    season_context: dict | None = None,
) -> EpisodeScript | None:
    """Stage 3: Critic 评审选最优

    dry-run 模式: 跳过 LLM, 直接返回第一个候选 (视为 PASS)
    """
    if dry_run:
        logger.info(f"[DRY-RUN] Critic 跳过, 直接选第 1 候选: {candidates[0].title}")
        return candidates[0]

    try:
        critic = make_default_critic()
        best, verdicts = critic.select_best(candidates, episode_spec, season_context)
        if best is None:
            logger.error("Critic 全部评审失败")
            return None
        # 记录每集分数 (verdicts: dict[int, CriticVerdict], key=ep 编号)
        score_log = ", ".join(
            f"#{ep}={v.total_score}/50"
            for ep, v in sorted(verdicts.items(), key=lambda x: x[1].total_score, reverse=True)
        )
        logger.info(f"Critic: {len(verdicts)} 集评审完, scores: {score_log}")
        return best
    except Exception as e:
        logger.exception(f"Critic 异常: {e}")
        return None


def _run_hard_check(script: EpisodeScript) -> HardCheckResult | None:
    """Stage 4: L3 Hard Check"""
    try:
        checker = make_default_checker(script)
        result = checker.run()
        logger.info(
            f"HardCheck: verdict={result.verdict}, "
            f"violations={len(result.violations)}, warnings={len(result.warnings)}, "
            f"passed={result.passed_constraints}/{result.total_constraints}",
        )
        if not result.should_publish:
            for v in result.violations[:5]:  # 只 log 前 5 条
                logger.warning(f"  ❌ {v.constraint_id}: {v.evidence}")
        return result
    except Exception as e:
        logger.exception(f"HardCheck 异常: {e}")
        return None


def _run_memory(mm: MemoryManager, script: EpisodeScript) -> bool:
    """Stage 5: Memory 跨集硬约束 + 写入"""
    try:
        is_valid, errors, _warnings = mm.hard_check(script)
        if not is_valid:
            logger.error(f"Memory hard_check 失败: {errors}")
            return False
        # 写入本集记忆
        mm.add_episode(
            script,
            key_facts=[f"EP{script.ep} 关键事实"],  # MVP: 简化, 后续 P9.5 接 LLM 提取
            locations_used=list({shot.scene for shot in script.shots}),
        )
        logger.info(f"Memory: EP{script.ep} 已写入")
        return True
    except Exception as e:
        logger.exception(f"Memory 异常: {e}")
        return False


def _alert_failure(episode_label: str, errors: list[str]) -> None:
    """失败告警: 写 logs/alert.txt (后续 P13 微信 notifier 接管)"""
    logger.critical(f"❌ DAILY RUN FAILED: {episode_label} errors={errors}")
    alert_path = Path("logs/alert.txt")
    alert_path.parent.mkdir(exist_ok=True)
    with alert_path.open("a", encoding="utf-8") as f:
        ts = datetime.now().isoformat(timespec="seconds")
        f.write(f"{ts}\t{episode_label}\t{'; '.join(errors)}\n")


# ===== CLI 入口 =====
def cli() -> int:
    # P11+P13 fix: 手动跑时没 source .env, 这里自动 load (override=False 不影响 systemd env)
    # 显式 dotenv_path=".env" 避免 pytest 调试模式下 find_dotenv 误走 frame 路径
    # 测试场景: tmp_path 没 .env, load_dotenv 静默 noop, 不会污染 monkeypatch.delenv 后的 env
    load_dotenv(dotenv_path=".env", override=False)

    parser = argparse.ArgumentParser(description="yk-script daily orchestrator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="跳过 LLM 调用, 用 fixture; 跳过 publish, 只写 md → output/",
    )
    parser.add_argument(
        "--force-episode",
        type=int,
        default=None,
        help="指定要重生成的集号 (1-12), 跳过 state.json 自动推进",
    )
    parser.add_argument(
        "--season-id",
        type=int,
        default=1,
        help="季号 (默认 1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="输出目录 (默认 output/)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="详细日志",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    return main(
        dry_run=args.dry_run,
        force_episode=args.force_episode,
        season_id=args.season_id,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    sys.exit(cli())
