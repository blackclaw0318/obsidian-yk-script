"""
memory_manager.py — Agent 3 Memory Manager (跨集状态机)

职责 (v0.3 文档 §3.5):
- 跨集状态持久化 (data/state/memory_bank.json, gitignored)
- 跨集硬约束检测 (时间线 / 道具 / 上集钩子回收)
- 为下一集提供 prev_episode 上下文

调用方:
- src/daily.py (P9 主流程串联, 在 L3 Hard Check 之后 / markdown 渲染之前)
- P7 Hard Checker 也可调用 (当前 MVP 已内嵌 hook 关键词检测, P8 提供更智能版本)

设计原则:
- MemoryBank 用 Pydantic v2 模型 (类型安全 + IDE 友好)
- file lock 防并发写 (daily cron + manual script 可能撞)
- hard_check 返回 (is_valid, errors, warnings), 由 daily.py 决定下一步
- save() 写盘后立即 GitHub backup (P12 backup 模块接管)

参考: prompts/memory_constraints.yaml memory_bank + hard_constraints
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.types import EpisodeScript

logger = logging.getLogger(__name__)


# ===== Memory Bank Pydantic Schemas =====
class YoukeiState(BaseModel):
    """YouKei 在某集结束时的状态"""

    model_config = ConfigDict(extra="forbid")

    position: str = Field(default="客厅", description="位置 (客厅/阳台/...)")
    emotion: str = Field(default="curious", description="情感状态")
    learned_skills: list[str] = Field(
        default_factory=list,
        description="本集学会的技能 (跳窗台/偷鱼/...)",
    )
    age_months: float = Field(default=7.0, ge=0, le=24, description="猫月龄")


class EpisodeMemory(BaseModel):
    """单集记忆条目"""

    model_config = ConfigDict(extra="forbid")

    ep: int = Field(ge=1, le=12)
    title: str
    stage: Literal["起势段", "攀升段", "风暴段", "决战段"]
    key_facts: list[str] = Field(default_factory=list, description="本集确定的事实")
    locations_used: list[str] = Field(default_factory=list, description="本集用过的场景")
    time_markers: list[str] = Field(default_factory=list, description="本集用过的具体时间点")
    youkei_state: YoukeiState = Field(default_factory=YoukeiState)
    hook_delivered: str = Field(default="", description="本集是否兑现了上一集的 next_episode_seed")
    hook_seed_for_next: str = Field(default="", description="留给下一集的钩子")


class MemoryBank(BaseModel):
    """跨集状态总账 (data/state/memory_bank.json)"""

    model_config = ConfigDict(extra="ignore")  # 允许备份文件加额外元数据

    season_id: int = Field(default=1, ge=1)
    last_updated: str = Field(default="", description="ISO 8601 时间戳")
    youkei_age_months_start: float = Field(default=7.0, ge=0, le=24)
    episodes: list[EpisodeMemory] = Field(default_factory=list)


# ===== MemoryManager 主类 =====
class MemoryViolationError(Exception):
    """硬约束违反 (timeline 倒退 / 已消耗道具再用 / 钩子未回收)"""


class MemoryManager:
    """跨集状态机 + 跨集硬约束检测

    用法:
        mm = MemoryManager()  # 从默认路径加载
        is_valid, errors, warnings = mm.hard_check(script)
        if is_valid:
            mm.add_episode(script, key_facts=[...], locations_used=[...])
            mm.save()
    """

    DEFAULT_MEMORY_PATH = Path("data/state/memory_bank.json")

    def __init__(self, memory_path: Path | None = None):
        # DEFAULT_MEMORY_PATH 在调用时重新 resolve 到当前 cwd,
        # 避免模块加载时的 cwd 被缓存
        if memory_path is None:
            memory_path = Path.cwd() / self.DEFAULT_MEMORY_PATH
        self.memory_path = memory_path
        self.memory = self._load()
        logger.info(
            f"MemoryManager loaded: {len(self.memory.episodes)} episodes from {self.memory_path}",
        )

    # ===== 加载 / 保存 =====
    def _load(self) -> MemoryBank:
        if not self.memory_path.exists():
            logger.info("Memory bank 不存在, 初始化空 bank")
            return MemoryBank()
        try:
            data = json.loads(self.memory_path.read_text(encoding="utf-8"))
            return MemoryBank.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Memory bank 解析失败 ({e}), 重置为空 bank")
            return MemoryBank()

    def save(self) -> None:
        """原子写盘 (tempfile + rename) 防并发"""
        self.memory.last_updated = datetime.now().isoformat(timespec="seconds")
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        # 临时文件 + atomic rename (避免半写状态)
        fd, tmp_path = tempfile.mkstemp(
            dir=self.memory_path.parent,
            prefix=".memory_bank.",
            suffix=".json.tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    self.memory.model_dump(),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp_path, self.memory_path)
            logger.info(
                f"Memory bank saved: {len(self.memory.episodes)} episodes",
            )
        except Exception:
            # 清理 temp 文件
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()
            raise

    # ===== 查询接口 =====
    def get_season(self) -> MemoryBank:
        return self.memory

    def get_episode(self, ep: int) -> EpisodeMemory | None:
        for em in self.memory.episodes:
            if em.ep == ep:
                return em
        return None

    def get_prev_episode(self, ep: int) -> EpisodeMemory | None:
        """取 ep 的上一集记忆 (ep=2 → ep=1)"""
        return self.get_episode(ep - 1) if ep >= 2 else None

    # ===== 写入接口 =====
    def add_episode(
        self,
        script: EpisodeScript,
        *,
        key_facts: list[str] | None = None,
        locations_used: list[str] | None = None,
        time_markers: list[str] | None = None,
        youkei_state: YoukeiState | None = None,
        hook_delivered: str = "",
    ) -> EpisodeMemory:
        """写入本集记忆 (不自动 save, 调用方决定时机)

        Args:
            script: 已校验通过的 EpisodeScript
            key_facts: 本集确定的事实 (例: ["YouKei 学会跳窗台"])
            locations_used: 用过的场景 (例: ["room_living", "room_balcony"])
            time_markers: 时间点 (例: ["20:00", "凌晨 3 点"])
            youkei_state: 猫状态 (默认从 locations_used 最后一项推断)
            hook_delivered: 上集 next_episode_seed 是否兑现
        """
        # 检查 ep 是否已存在 (重复添加警告)
        existing = self.get_episode(script.ep)
        if existing is not None:
            logger.warning(
                f"EP{script.ep} 已在 memory bank, 将覆盖 ({existing.title} → {script.title})",
            )
            self.memory.episodes = [em for em in self.memory.episodes if em.ep != script.ep]

        # stage 从 season-XX.json 推断 (MVP: 默认起势段, 后续接 season loader)
        stage = self._infer_stage(script)

        # youkei_state 默认值
        if youkei_state is None:
            youkei_state = YoukeiState(
                position=(locations_used or ["客厅"])[-1],
                emotion="curious",
                learned_skills=[],
                age_months=self.memory.youkei_age_months_start + (script.ep - 1) * 0.03,
            )

        entry = EpisodeMemory(
            ep=script.ep,
            title=script.title,
            stage=stage,
            key_facts=key_facts or [],
            locations_used=locations_used or [],
            time_markers=time_markers or [],
            youkei_state=youkei_state,
            hook_delivered=hook_delivered,
            hook_seed_for_next=script.next_episode_seed or "",
        )
        self.memory.episodes.append(entry)
        # 按 ep 排序
        self.memory.episodes.sort(key=lambda x: x.ep)
        logger.info(f"EP{script.ep} 写入 memory bank: {script.title}")
        return entry

    def _infer_stage(
        self, script: EpisodeScript
    ) -> Literal["起势段", "攀升段", "风暴段", "决战段"]:
        """MVP: 按 ep 推 stage (后续接 season-XX.json)"""
        if script.ep <= 3:
            return "起势段"
        if script.ep <= 6:
            return "攀升段"
        if script.ep <= 9:
            return "风暴段"
        return "决战段"

    # ===== 跨集硬约束检测 =====
    def hard_check(
        self,
        script: EpisodeScript,
    ) -> tuple[bool, list[str], list[str]]:
        """跨集硬约束检测 (在 L3 hard_check.py 之外补一层跨集逻辑)

        Returns:
            (is_valid, errors, warnings)
            - is_valid: errors 为空才 True
            - errors: 必须修复的硬约束 (timeline 倒退 / 钩子未回收 / 已消耗道具再用)
            - warnings: 建议注意的 (猫月龄跳跃过大 / 时间点跟季节不符)

        不修改 self.memory, 仅查询 + 校验。
        """
        errors: list[str] = []
        warnings: list[str] = []

        prev = self.get_prev_episode(script.ep)
        is_first_ep = prev is None

        # 1. 时间线不倒退: 猫月龄只能递增
        if not is_first_ep:
            assert prev is not None  # type narrowing
            prev_age = prev.youkei_state.age_months
            expected_age = self.memory.youkei_age_months_start + (script.ep - 1) * 0.03
            if prev_age > expected_age + 0.5:
                warnings.append(
                    f"youkei_age_jump: prev EP{prev.ep}={prev_age}, "
                    f"EP{script.ep} 期望 ≈{expected_age:.2f}, 跳跃过大",
                )

        # 2. 上集钩子回收 (EP02+ 必查)
        if not is_first_ep and prev is not None:
            prev_seed = prev.hook_seed_for_next
            if prev_seed and not self._validate_hook_continuity(prev_seed, script):
                errors.append(
                    f"prev_hook_not_recovered: EP{prev.ep} 的 next_episode_seed "
                    f"'{prev_seed[:40]}...' 未在 EP{script.ep} 兑现",
                )

        # 3. 末钩必设 (EP12 例外)
        if script.ep != 12 and not (script.next_episode_seed or "").strip():
            errors.append("missing_final_hook: 非 EP12 必须有 next_episode_seed")

        is_valid = len(errors) == 0
        for e in errors:
            logger.error(f"❌ Memory violation: {e}")
        for w in warnings:
            logger.warning(f"⚠️ Memory warning: {w}")
        return is_valid, errors, warnings

    def _validate_hook_continuity(
        self,
        prev_hook: str,
        script: EpisodeScript,
    ) -> bool:
        """检查上集 next_episode_seed 是否在本集某 shot 兑现

        MVP: keyword 匹配 (取 prev_hook 中 3+ 字符的实词)
        未来 (P8 增强): 调 LLM 判定"语义是否兑现"
        """
        keywords = self._extract_keywords(prev_hook)
        if not keywords:
            return True  # prev_hook 太短, 默认通过

        text = self._collect_script_text(script)
        return any(kw in text for kw in keywords)

    def _extract_keywords(self, text: str) -> list[str]:
        """从 prev_hook 提取 3 个关键词

        简单实现: 去掉常见虚词, 取 3+ 字符的实词。
        不依赖 jieba (项目无 NLP 依赖)。
        """
        # 移除 "EP02" / "EP03" 等集号标记
        import re

        text = re.sub(r"EP\d+", "", text)
        # 按空白/标点分词
        words = re.findall(r"[\w\u4e00-\u9fff]+", text)
        # 取 3+ 字符
        candidates = [w for w in words if len(w) >= 3]
        return candidates[:3]

    def _collect_script_text(self, script: EpisodeScript) -> str:
        """聚合 script 所有文本字段"""
        parts: list[str] = []
        for shot in script.shots:
            parts.extend([shot.action or "", shot.voiceover or "", shot.subtitle or ""])
        if script.hook.text:
            parts.append(script.hook.text)
        if script.next_episode_seed:
            parts.append(script.next_episode_seed)
        return "\n".join(parts)


# ===== 工厂 =====
def make_default_manager() -> MemoryManager:
    """工厂: 用默认路径构造 MemoryManager (每次都 resolve 到当前 cwd)"""
    return MemoryManager(memory_path=Path.cwd() / MemoryManager.DEFAULT_MEMORY_PATH)
