"""
critic.py — Layer 2 Critic (评审团)

职责:
- 接收 Writer L1 输出的 EpisodeScript
- 加载 critic_rubric.yaml (5 视角 50 分)
- 一次性让 LLM 评审 5 个视角 (节省 API 调用)
- 聚合分数 → 总分 → verdict → should_rewrite

调用方:
- src/daily.py (cron entry, P5 Writer → P6 Critic → P7 Hard Check)
- 失败 verdict=FAIL → 触发 L1 重写 1 次 (P3 max_retries=1)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from src.llm_client import LLMClient, LLMResponse
from src.prompt_renderer import render_prompt_template
from src.types import (
    CriticVerdict,
    EpisodeScript,
    LLMError,
    Verdict,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CHARACTERS_DIR = ROOT / "data" / "characters"


@dataclass
class CriticResult:
    """Critic 评审完整结果"""

    script: EpisodeScript
    verdict: CriticVerdict | None = None
    raw_response: str | None = None
    error: str | None = None
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class Critic:
    """Layer 2 Critic (评审团)"""

    # 5 视角权重 (与 critic_rubric.yaml aggregation 一致)
    WEIGHTS: ClassVar[dict[str, int]] = {
        "humor": 15,
        "cuteness": 15,
        "continuity": 10,
        "rhythm": 5,
        "red_line": 5,
    }

    PASS_THRESHOLD = 38  # >=38 PASS
    EXCELLENT_THRESHOLD = 45  # >=45 EXCELLENT

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        temperature: float = 0.3,  # 评审需要客观, 温度低
        max_tokens: int = 4000,
    ):
        self.client = llm_client
        self.temperature = temperature
        self.max_tokens = max_tokens

    def critique_episode(self, script: EpisodeScript) -> CriticResult:
        """评审单个 EpisodeScript

        Args:
            script: Writer L1 输出的剧本

        Returns:
            CriticResult: 含 verdict / 失败时 error 字段
        """
        characters = self._load_characters()

        # 1. 渲染 system prompt (含 5 视角详细评分标准)
        rubric = self._load_rubric()
        system_prompt = self._build_system_prompt(rubric, characters)

        # 2. 渲染 user prompt (含本集剧本)
        user_prompt = self._build_user_prompt(script)

        # 3. 调用 LLM
        try:
            response: LLMResponse = self.client.messages_create(
                system=system_prompt,
                user=user_prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,  # Critic 非流式
            )
            verdict = self._parse_response(response.text)
            return CriticResult(
                script=script,
                verdict=verdict,
                raw_response=response.text,
                duration_ms=response.duration_ms,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
        except Exception as e:
            logger.error(f"Critic EP{script.ep} 评审失败: {e}")
            return CriticResult(
                script=script,
                verdict=None,
                raw_response=None,
                error=str(e),
            )

    def select_best(
        self,
        candidates: list[EpisodeScript],
    ) -> tuple[EpisodeScript | None, dict[int, CriticVerdict]]:
        """从 N 个候选中选最优 (verdict 最高 → EXCELLENT 优先)

        Args:
            candidates: Writer 输出的候选列表

        Returns:
            (best_script, verdict_map):
              - best_script 可能为 None (评审全失败)
              - verdict_map: key=ep 编号 (int), value=CriticVerdict
                (P9 fix: EpisodeScript 不可哈希, 不用脚本当 key)
        """
        verdict_map: dict[int, tuple[EpisodeScript, CriticVerdict]] = {}
        for cand in candidates:
            result = self.critique_episode(cand)
            if result.verdict is not None:
                # P9 fix: EpisodeScript 是 Pydantic BaseModel, 不可哈希, 用 ep 编号当 key
                verdict_map[cand.ep] = (cand, result.verdict)

        if not verdict_map:
            return None, {}

        # 排序: total_score 降序, EXCELLENT 优先
        def sort_key(item: tuple[int, tuple[EpisodeScript, CriticVerdict]]) -> tuple[int, int]:
            _, (_, verdict) = item
            return (
                -verdict.total_score,
                -1 if verdict.verdict == Verdict.EXCELLENT else 0,
            )

        sorted_items = sorted(verdict_map.items(), key=sort_key)
        best_script = sorted_items[0][1][0]  # P9 fix: tuple[int, (script, verdict)]
        # P9 fix (Phase 2): EpisodeScript 不可哈希, 用 ep 当 key 而非对象
        final_map: dict[int, CriticVerdict] = {ep: v for ep, (_, v) in verdict_map.items()}
        return best_script, final_map

    # ===== 内部方法 =====
    def _build_system_prompt(
        self,
        rubric: dict[str, Any],
        characters: dict[str, Any],
    ) -> str:
        """构建 Critic system prompt (5 视角详细评分标准 + 红线)"""
        base_system = render_prompt_template(
            "critic_rubric.yaml",
            {
                "character_protagonist": characters["protagonist"],
                "character_apartment": characters["apartment"],
                "character_youkei": characters["youkei"],
            },
            field="system_prompt",
        )

        # 附加: 5 视角权重 + 阈值 + 输出 JSON schema
        schema_desc = """
## 输出 JSON Schema (严格)
```json
{
  "episode_id": <int 1-12>,
  "perspectives": [
    {"id": "humor", "score": <0-5>, "reason": "<≤100 字>", "improvement": "<≤50 字>"},
    {"id": "cuteness", "score": <0-5>, "reason": "...", "improvement": "..."},
    {"id": "continuity", "score": <0-5>, "reason": "...", "improvement": "..."},
    {"id": "rhythm", "score": <0-5>, "reason": "...", "improvement": "..."},
    {"id": "red_line", "score": <0-5>, "reason": "...", "improvement": "..."}
  ],
  "total_score": <sum(score * weight / 5)>,
  "verdict": "EXCELLENT" | "PASS" | "FAIL",
  "feedback": "<≤200 字综合反馈>",
  "should_rewrite": <true if verdict=FAIL>
}
```

## 聚合公式
total_score = humor*3 + cuteness*3 + continuity*2 + rhythm*1 + red_line*1
(权重 15/15/10/5/5, 每项 0-5 分, 满分 50)
"""
        return base_system + schema_desc

    def _build_user_prompt(self, script: EpisodeScript) -> str:
        """构建 Critic user prompt (本集剧本)"""
        script_json = script.model_dump_json(indent=2, exclude_none=True)
        return f"""## 待评审剧本 EP{script.ep} 《{script.title}》

```json
{script_json}
```

请按 system prompt 中 5 个视角的评分标准逐一打分, 输出严格 JSON。
- humor: 冲突密度 + 反转设计 + 笑点自然度 + 节奏曲线
- cuteness: YouKei 戏份 + 招牌动作 + 反差萌 + 拟声词萌感
- continuity: 上集钩子回收 + 时间线连贯 + 角色位置 + 本集钩子交付
- rhythm: shot 数 + 时长 + 情绪波峰位置
- red_line: 19 条红线 (8+6+5), 任一违反 → score=0

输出 JSON, 不要解释。"""

    def _parse_response(self, text: str) -> CriticVerdict:
        """解析 LLM 响应 JSON → CriticVerdict"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMError(f"Critic 响应非 JSON: {e}", response_body=text[:500]) from e

        try:
            return CriticVerdict.model_validate(data)
        except Exception as e:
            raise LLMError(f"CriticVerdict schema 校验失败: {e}", response_body=text[:500]) from e

    def _load_rubric(self) -> dict[str, Any]:
        """加载 critic_rubric.yaml"""
        from src.prompt_renderer import _load_template_file

        return _load_template_file("critic_rubric.yaml")

    def _load_characters(self) -> dict[str, Any]:
        """加载 3 张角色卡"""
        chars = {}
        for name in ("protagonist", "youkei", "apartment"):
            path = CHARACTERS_DIR / f"{name}.json"
            chars[name] = json.loads(path.read_text(encoding="utf-8"))
        return chars


# ===== 工厂 =====
def make_default_critic() -> Critic:
    """工厂: 从环境变量构造默认 Critic"""
    from src.llm_client import make_default_client

    return Critic(make_default_client())
