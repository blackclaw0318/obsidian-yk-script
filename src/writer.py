"""
writer.py — Layer 1 Writer (Screenwriter)

职责:
- 加载 season-XX.json + 角色卡 + writer.yaml 模板
- 渲染 Jinja2 prompt (system + user)
- 调用 LLM 生成 N=3 个候选 EpisodeScript (P3 决策)
- 解析 JSON + Pydantic 校验
- 自检 (8+6+5 红线 + 节奏 + hook)

调用方:
- src/daily.py (cron entry)
- src/hard_check.py (L3 之前先过 L1)

降级:
- N=3 中 1-2 个失败 → 仍接受成功的
- 全部失败 → 抛出 WriterAllFailedError
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.llm_client import LLMClient, LLMResponse
from src.prompt_renderer import render_prompt_template
from src.types import (
    EpisodeScript,
    EpisodeSpec,
    LLMError,
    make_episode_script_from_json,
    make_episode_spec_from_json,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CHARACTERS_DIR = ROOT / "data" / "characters"
SEASONS_DIR = ROOT / "data" / "seasons"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge" / "references"


class WriterAllFailedError(LLMError):
    """N 个候选全部生成失败"""

    pass


@dataclass
class CandidateResult:
    """单次候选生成结果"""

    index: int  # 1-based
    script: EpisodeScript | None
    raw_response: str | None
    error: str | None = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None


@dataclass
class WriterResult:
    """Writer 整体结果"""

    ep: int
    candidates: list[CandidateResult] = field(default_factory=list)
    successful: list[CandidateResult] = field(default_factory=list)
    failed: list[CandidateResult] = field(default_factory=list)

    @property
    def best(self) -> EpisodeScript | None:
        """取第一个成功的 (后面 P7+ Critic 接管选最优)"""
        if self.successful:
            return self.successful[0].script
        return None

    @property
    def total_duration_ms(self) -> int:
        return sum(c.duration_ms for c in self.candidates)

    @property
    def total_tokens(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.candidates)


class Writer:
    """Layer 1 Screenwriter"""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        n_candidates: int = 3,  # P3 老板决策
        temperature: float = 0.85,
        max_tokens: int = 8000,
    ):
        self.client = llm_client
        self.n_candidates = n_candidates
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate_episode_candidates(
        self,
        ep: int,
        season_id: int = 1,
        retry_keywords: list[str] | None = None,  # P1.7-D: 上一轮缺的关键词, 本轮必须嵌
        retry_round: int = 1,  # P1.7-D: 重试轮次 (1=首次, 2/3=重试), 用于 prompt 中提示
    ) -> WriterResult:
        """生成 N 个候选 EpisodeScript

        Args:
            ep: 集号 (1-12)
            season_id: 季号 (默认 1)
            retry_keywords: P1.7-D 注入 (上一轮 hard_check 拦截的缺关键词)
            retry_round: P1.7-D 重试轮次 (1=首次, 2=重试1, 3=重试2)

        Returns:
            WriterResult: 含 candidates / successful / failed

        Raises:
            WriterAllFailedError: N 个候选全部失败
        """
        # 1. 加载数据
        season_data = self._load_season(season_id)
        ep_data = next(
            (e for e in season_data["episodes"] if e["ep"] == ep),
            None,
        )
        if ep_data is None:
            raise ValueError(f"season-{season_id:02d}.json 不含 EP{ep}")

        ep_spec = make_episode_spec_from_json(ep_data)
        characters = self._load_characters()
        references = self._load_relevant_references(ep_spec)

        # 1.5 构造完整 season_context (P1.2: 注入 stage/quality/钩子关键词 等)
        season_context = self._build_season_context(season_data, ep_data)

        # 2. 渲染 user prompt (system prompt 是固定的, 渲染一次即可)
        user_prompt = render_prompt_template(
            "writer.yaml",
            {
                "episode_spec": ep_data,
                "character_protagonist": characters["protagonist"],
                "character_youkei": characters["youkei"],
                "character_apartment": characters["apartment"],
                "season_context": season_context,
                "pct": round(ep / season_data["total_episodes"] * 100),
                "references_excerpt": references,
                "retry_keywords": retry_keywords or [],  # P1.7-D
                "retry_round": retry_round,  # P1.7-D
            },
            field="user_prompt_template",
        )
        system_prompt = render_prompt_template(
            "writer.yaml",
            {
                "character_protagonist": characters["protagonist"],
                "character_youkei": characters["youkei"],
                "character_apartment": characters["apartment"],
                "episode_spec": ep_data,  # P9 fix: writer.yaml system_prompt 模板 line 80-151 引用了 episode_spec (干跑隐藏 bug)
                "season_context": season_context,  # P1.2: system_prompt 现在引用 stage/quality_targets
                "pct": round(ep / season_data["total_episodes"] * 100),
                "retry_keywords": retry_keywords or [],  # P1.7-D
                "retry_round": retry_round,  # P1.7-D
            },
            field="system_prompt",
        )

        # 3. 生成 N 个候选 (温度微调避免重复)
        result = WriterResult(ep=ep)
        for i in range(1, self.n_candidates + 1):
            # 每个候选温度微调 0.05, 创造多样性
            temp = self.temperature + (i - 1) * 0.03
            temp = min(temp, 0.95)
            cand = self._generate_single(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                index=i,
                temperature=temp,
            )
            result.candidates.append(cand)
            if cand.script is not None:
                result.successful.append(cand)
            else:
                result.failed.append(cand)

        if not result.successful:
            errors = "; ".join(c.error for c in result.failed if c.error)
            raise WriterAllFailedError(
                f"EP{ep} {self.n_candidates} 个候选全部失败: {errors}",
            )

        logger.info(
            f"EP{ep} 生成 {len(result.successful)}/{self.n_candidates} 个候选, "
            f"tokens={result.total_tokens}, duration={result.total_duration_ms}ms",
        )
        return result

    def _generate_single(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        index: int,
        temperature: float,
    ) -> CandidateResult:
        """生成单次候选"""
        try:
            response: LLMResponse = self.client.messages_create(
                system=system_prompt,
                user=user_prompt,
                temperature=temperature,
                max_tokens=self.max_tokens,
                stream=False,  # P9 fix: 暂用非流式, 待 v0.4 加 SSE 解析 (SSE 需要拼接 message_delta, 不应响几十行手动拼接)
            )
            script = self._parse_response(response.text)
            return CandidateResult(
                index=index,
                script=script,
                raw_response=response.text,
                duration_ms=response.duration_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                stop_reason=response.stop_reason,
            )
        except Exception as e:
            logger.warning(f"候选 #{index} 失败: {e}")
            return CandidateResult(
                index=index,
                script=None,
                raw_response=None,
                error=str(e),
            )

    def _parse_response(self, text: str) -> EpisodeScript:
        """解析 LLM 响应 JSON → EpisodeScript

        LLM 偶尔会包裹 ```json ... ``` 代码块, 需要剥离
        """
        cleaned = text.strip()
        # 剥离 markdown 代码块
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # 去掉首尾 ``` 和语言标签
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMError(f"LLM 响应非 JSON: {e}", response_body=text[:500]) from e

        try:
            return make_episode_script_from_json(data)
        except Exception as e:
            raise LLMError(f"EpisodeScript schema 校验失败: {e}", response_body=text[:500]) from e

    def _build_season_context(
        self,
        season_data: dict[str, Any],
        ep_data: dict[str, Any],
    ) -> dict[str, Any]:
        """P1.2: 从 season_data + satisfaction_matrix.json + hook_distribution.json 构造完整上下文

        字段:
        - season_id, title, theme, total_episodes
        - stage_description: 从 stage_distribution[ep.stage].description
        - stage_intensity: 从 stage_distribution[ep.stage].rhythm_intensity
        - stage_adaptations: 从 satisfaction_matrix.json validation_rules.stage_adaptations[ep.stage]
        - hook_verifier_keywords: 从 hook_distribution.json hook_types[ep.hook_type].verifier_keywords
        - satisfaction_verifier_keywords: 从 satisfaction_matrix.json satisfaction_types[情感爆发].verifier_keywords (P1.7-B)
        - quality_targets: 从 season_data.quality_targets
        - hook_strength_min: 从 quality_targets.hook_strength_min
        """
        stage = ep_data.get("stage", "")
        stage_dist = season_data.get("stage_distribution", {}).get(stage, {})
        hook_type = ep_data.get("hook_type", "")
        sat_types = ep_data.get("satisfaction_types", [])

        # 加载 satisfaction_matrix.json + hook_distribution.json (P1.2 新增, P1.7-B 扩展)
        stage_adaptations = ""
        hook_keywords: list[str] = []
        satisfaction_keywords: list[str] = []
        try:
            sm_path = ROOT / "prompts" / "satisfaction_matrix.json"
            sm = json.loads(sm_path.read_text(encoding="utf-8"))
            stage_adaptations = sm["validation_rules"]["stage_adaptations"].get(stage, {}).get("配比", "")
            # P1.7-B: 情感爆发类必有 verifier_keywords, 提前加载进 context 让 LLM 看到
            for sat in sat_types:
                kws = sm.get("satisfaction_types", {}).get(sat, {}).get("verifier_keywords", [])
                satisfaction_keywords.extend(kws)
            # 去重保序
            seen: set[str] = set()
            satisfaction_keywords = [k for k in satisfaction_keywords if not (k in seen or seen.add(k))]
        except Exception:
            pass
        try:
            hd_path = ROOT / "prompts" / "hook_distribution.json"
            hd = json.loads(hd_path.read_text(encoding="utf-8"))
            hook_keywords = hd["hook_types"].get(hook_type, {}).get("verifier_keywords", [])
        except Exception:
            pass

        quality = season_data.get("quality_targets", {})

        return {
            "season_id": season_data.get("season_no", 1),
            "title": season_data.get("title", ""),
            "theme": season_data.get("theme", ""),
            "total_episodes": season_data.get("total_episodes", 12),
            "stage_distribution": season_data.get("stage_distribution", {}),
            "stage_description": stage_dist.get("description", ""),
            "stage_intensity": stage_dist.get("rhythm_intensity", ""),
            "stage_adaptations": stage_adaptations,
            "hook_verifier_keywords": hook_keywords,
            "satisfaction_verifier_keywords": satisfaction_keywords,  # P1.7-B 新增
            "quality_targets": quality,
            "hook_strength_min": quality.get("hook_strength_min", "中等"),
        }

    def _load_season(self, season_id: int) -> dict[str, Any]:
        """加载 season-XX.json"""
        path = SEASONS_DIR / f"season-{season_id:02d}.json"
        if not path.exists():
            raise FileNotFoundError(f"季文件不存在: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_characters(self) -> dict[str, Any]:
        """加载 3 张角色卡"""
        chars = {}
        for name in ("protagonist", "youkei", "apartment"):
            path = CHARACTERS_DIR / f"{name}.json"
            chars[name] = json.loads(path.read_text(encoding="utf-8"))
        return chars

    def _load_relevant_references(self, ep_spec: EpisodeSpec) -> str:
        """根据 EP 类型加载相关编剧知识 (精简 excerpt)

        规则:
        - EP01-02 (起势): opening-rules + hook-design
        - EP03-10 (攀升/风暴): hook-design + rhythm-curve + satisfaction-matrix
        - EP11-12 (决战): hook-design (EP12 无) + satisfaction-matrix
        """
        refs: dict[str, list[str]] = {
            "起势段": ["opening-rules.md", "hook-design.md"],
            "攀升段": ["hook-design.md", "rhythm-curve.md", "satisfaction-matrix.md"],
            "风暴段": ["hook-design.md", "rhythm-curve.md", "satisfaction-matrix.md", "villain-design.md"],
            "决战段": ["hook-design.md", "satisfaction-matrix.md", "genre-guide.md"],
        }
        files = refs.get(ep_spec.stage.value, ["hook-design.md"])
        excerpts: list[str] = []
        for fname in files:
            path = KNOWLEDGE_DIR / fname
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8")
            # 截取前 500 字 (避免 token 爆)
            excerpts.append(f"### {fname}\n{content[:500]}")
        return "\n\n".join(excerpts)


# ===== 工厂 =====
def make_default_writer() -> Writer:
    """工厂: 从环境变量构造默认 Writer"""
    from src.llm_client import make_default_client
    return Writer(make_default_client())
