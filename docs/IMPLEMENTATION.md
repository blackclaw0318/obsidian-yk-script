# obsidian-yk-script — 实施细节 v0.2 (2026-07-11)

> **配合**:`PLAN.md` (做什么) + `ARCHITECTURE.md` (数据流) ← 本文档是 **怎么写**
> **状态**: ⏸️ 等老板 P1-P4 拍板 → 立即开 P0

---

## 📌 这份文档解决 3 个问题

1. **老板/未来的我打开仓库第一眼就知道每个文件长什么样** — 不是空架子
2. **每个 Agent 的代码骨架/类签名/关键方法可对照着抄** — 不是"伪代码示意"
3. **实施顺序有测试门控** — 上一步测试不过不许走下一步

---

## 1. 完整仓库结构 (实施时按此生成)

```
obsidian-yk-script/
├── README.md
├── LICENSE                             # MIT (与 references 同协议)
├── .env.example                        # 凭据模板 (gitignored .env)
├── .gitignore                          # + .env / data/state / logs/
├── pyproject.toml                      # Python 3.12 + 依赖
├── requirements.txt                    # requests / PyYAML / python-dotenv / pytest
│
├── data/
│   ├── characters/                     # 📥 老板在 GitHub UI 手动编辑 (源 = 本仓)
│   │   ├── youkei.json                 # ✅ 已落地 (源 = 仓)
│   │   ├── protagonist.json            # ⏳ P1 落地 (化名"上坤"+只出手)
│   │   └── apartment.json              # ⏳ P1 落地 (6 室 + 5 外出备选)
│   ├── seasons/                        # 📥 大纲: 老板手动编辑 → GitHub 拉取
│   │   └── season-01.json              # ✅ 已落地 (12 集 + 节奏四段)
│   ├── knowledge/references/           # 🔒 fork 后冻结 (不用 GitHub 拉, 本地读)
│   │   ├── opening-rules.md
│   │   ├── rhythm-curve.md
│   │   ├── hook-design.md
│   │   ├── satisfaction-matrix.md
│   │   ├── villain-design.md
│   │   ├── genre-guide.md
│   │   ├── paywall-design.md
│   │   ├── compliance-checklist.md
│   │   ├── UPSTREAM-README.md          # 上游项目说明 (我们怎么 fork 的)
│   │   └── LICENSE-short-drama.txt     # MIT 原文
│   ├── cache/                          # 🆕 v0.3 GitHub 拉取缓存 (gitignored)
│   │   ├── season-01.json              # ← 从 GitHub 拉的大纲
│   │   ├── season-01.sha               # ← sha 检测变更
│   │   ├── youkei.json                 # ← 从 GitHub 拉的角色卡
│   │   └── protagonist.json            # ← 从 GitHub 拉的主角卡
│   └── state/                          # gitignored, 运行时生成
│       ├── state.json                  # {season_no, episode, last_run_at, ...}
│       └── memory.json                 # 角色状态机 + 道具 + 时间线
│
├── prompts/                            # ⏳ P4 落地 (注入 LLM 的 YAML)
│   ├── writer.yaml                     # Screenwriter prompt 模板
│   ├── critic_rubric.yaml              # 5 维评分细则
│   ├── hook_distribution.json          # 钩子 5 类阶段分布
│   ├── satisfaction_matrix.json        # 爽点 5 类配比 (萌宠适配)
│   └── memory_constraints.yaml         # Memory Manager 硬约束规则
│
├── src/
│   ├── __init__.py
│   ├── daily.py                        # ⏳ P8 主入口 orchestrator (集成 outline_fetcher + github_backup + wechat)
│   ├── screen_writer.py                # ⏳ P5 Agent 1: 写
│   ├── critic.py                       # ⏳ P6 Agent 2: 审
│   ├── memory_manager.py               # ⏳ P7 Agent 3: 管
│   ├── markdown_renderer.py            # ⏳ P8 JSON → MD
│   ├── hmac_client.py                  # ⏳ P8 复用 obsidian-journal
│   ├── state.py                        # ⏳ P8 状态读写 (state.json + memory.json)
│   ├── llm_client.py                   # ⏳ P5 minimax M2.7 wrapper (Anthropic 兼容)
│   ├── logger.py                       # ⏳ P8 日志 (滚动 10MB × 5)
│   ├── types.py                        # ⏳ P5 Pydantic 数据类 (EpisodeScript/Shot/Candidate)
│   ├── 🆕 backup_reader.py            # ⏳ P12 GitHub Contents API 只读 (拉 outline/characters)
│   ├── 🆕 outline_fetcher.py           # ⏳ P12 sha 检测 + 缓存 + fallback 本地
│   ├── 🆕 github_backup.py             # ⏳ P13 每日生成内容备份到 obsidian-novel-backups/yk-script/
│   └── 🆕 wechat_notifier.py           # ⏳ P14 复用 publisher 模式: pending.txt + cron run + 20s
│
├── scripts/
│   ├── publish-today.py                # ⏳ P8 手动触发 (复用 daily.main)
│   ├── skip-next.py                    # ⏳ P8 老板说"今天跳过"
│   ├── dry-run.py                      # ⏳ P10 不推送, 仅生成 + 本地预览
│   ├── regenerate.py                   # ⏳ P10 重写指定集
│   ├── seed-state.py                   # ⏳ P0 初始化 state.json + memory.json
│   ├── render-preview.py               # ⏳ P8 单独渲染 Markdown 调试
│   ├── pull-outline.py                 # 🆕 P12 手动强制拉 outline (调试用)
│   └── verify-backup.py                # 🆕 P13 验证今日 backup 已上传
│
├── systemd/
│   ├── yk-script.service               # ⏳ P9 Type=oneshot
│   └── yk-script.timer                 # ⏳ P9 OnCalendar=*-*-* 06:00:00
│
├── logs/                               # gitignored
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── conftest.py                     # fixtures: sample_episode / mock_llm / tmp_state / mock_github
    ├── unit/
    │   ├── test_screen_writer.py       # ⏳ P10 mock LLM, 验 3 候选生成 + prompt 注入
    │   ├── test_critic.py              # ⏳ P10 mock LLM, 验 5 维评分 + Island 循环
    │   ├── test_memory_manager.py      # ⏳ P10 验硬约束检测 + 状态机
    │   ├── test_markdown_renderer.py   # ⏳ P10 验 JSON → MD
    │   ├── test_state.py               # ⏳ P10 验 state.json / memory.json 读写
    │   ├── test_llm_client.py          # ⏳ P10 验 minimax 调用 + retry + stream
    │   ├── test_hmac_client.py         # ⏳ P10 验 HMAC 签名 + POST
    │   ├── 🆕 test_backup_reader.py    # ⏳ P12 requests-mock 验 GitHub API + retry
    │   ├── 🆕 test_outline_fetcher.py  # ⏳ P12 验 sha 检测 + 缓存 fallback
    │   ├── 🆕 test_github_backup.py    # ⏳ P13 验 PUT 文件 + base64 + sha 必传
    │   └── 🆕 test_wechat_notifier.py  # ⏳ P14 验 pending.txt + cron run + 20s sleep + unlink
    └── integration/
        ├── test_daily_e2e.py           # ⏳ P10 全链路 mock LLM, 验 daily.py 闭环
        ├── test_knowledge_loading.py   # ⏳ P10 验 8 references 按 stage 注入
        ├── test_state_persistence.py   # ⏳ P10 验多次跑后 state 推进正确
        ├── 🆕 test_outline_change_flow.py   # ⏳ P12 验老板改 GitHub → 第二天自动用新大纲
        ├── 🆕 test_backup_flow.py           # ⏳ P13 验生成 → backup → index.json 追加
        └── 🆕 test_wechat_notify_flow.py     # ⏳ P14 验成功/失败 → pending.txt → cron run (mock subprocess)
```

---

## 2. Prompt 模板实例 (P4 落地用)

### 2.1 `prompts/writer.yaml` — Screenwriter 完整模板

```yaml
# Screenwriter Prompt 模板 — 借鉴 COMIC Island + short-drama 知识库
version: "0.2.0"
model: "MiniMax-M3"
temperature: 0.9
max_tokens: 4000

system_prompt: |
  你是一位短视频编剧, 专门写"萌宠日常"题材单元剧。每集 30s-90s, 
  适配抖音/B站/小红书的快节奏消费场景。

  你的工作有 5 条铁律:
  1. **前 3 秒定生死** — 开场必须有钩子画面 (悬念/反差/萌点)
  2. **节奏四段** — 起势 15% / 攀升 30% / 风暴 35% / 决战 20% (按本集 stage)
  3. **情绪波峰必现** — 15% / 50% / 85% 三处必出情绪高峰
  4. **末 3s 留钩** — 反转/悬念/情绪钩, 让观众想看下一集
  5. **拍摄可行** — 60 平小两居, 普通手机能拍, 不依赖特效

  你的输出必须是严格 JSON, 字段见下方 "output_schema"。

# 用户 prompt 模板 — 用 jinja2 占位符, daily.py 渲染
user_prompt_template: |
  ## 📌 本集上下文

  - **季号**: S{{ season_no }}
  - **集号**: EP{{ episode_no:02d }} / 共 {{ total_episodes }} 集
  - **本集阶段**: {{ stage }} ({{ stage_position_pct }}% 处)
  - **核心冲突**: {{ episode.core_conflict }}
  - **场景**: {{ episode.scene }}
  - **本集钩子类型**: {{ episode.hook_type }} ({{ episode.hook_subtype }})
  - **本集爽点配比**: {{ episode.satisfaction_types | join(' + ') }}

  ---

  ## 🐱 角色档案 (来自 memory.json)

  ### 主角 · 上坤 (化名, 只出手+配音, 露脸后期)
  {{ protagonist_json | to_pretty_json }}

  ### 主角 · YouKei ({{ youkei.species }}, {{ youkei.age_months }}月龄)
  {{ youkei_json | to_pretty_json }}

  ### 公寓 ({{ apartment.total_rooms }} 室)
  {{ apartment_json | to_pretty_json }}

  ---

  ## 📚 编剧知识 (按本集 stage 注入, 来自 short-drama MIT 协议)

  {{ knowledge.opening_rules if stage == '起势段' else '' }}
  {{ knowledge.hook_design }}
  {{ knowledge.rhythm_curve }}
  {{ knowledge.satisfaction_matrix }}
  {{ knowledge.genre_guide }}

  ---

  ## 🔗 连续性约束 (Memory Manager 注入)

  ### 上一集摘要 (EP{{ episode_no - 1 }})
  > {{ prev_summary }}

  ### 上一集末钩子必须回收
  > 上集末 {{ prev_hook_text }}, 本集必须在某个 shot 中自然回收

  ### 当前状态 (不允许倒退)
  - 时间线: {{ memory.timeline.now }}
  - YouKei 状态: {{ memory.youkei_state }}
  - 上坤状态: {{ memory.protagonist_state }}
  - 已用道具: {{ memory.used_props }}

  ---

  ## 📋 本集要求

  - **shot 数**: 3-8 个
  - **总时长**: 30s-90s
  - **JSON 输出**: 严格按 output_schema
  - **情绪波峰位置**: shot 中 emotion_intensity ≥ 4 的 shot, 其 `shot_position` 必须接近 15%/50%/85% 之一
  - **末钩回收**: 最后一个 shot 必须包含 `is_hook: true` + `hook_text`

# 严格 JSON Schema (Pydantic 强校验)
output_schema:
  season: int
  episode: int
  title: str
  duration_estimate: str       # "75s"
  logline: str                 # 一句话剧情
  stage: str                   # 起势段/攀升段/风暴段/决战段
  stage_position_pct: int
  hook_type: str
  hook_subtype: str
  hook_text: str
  satisfaction_types: list[str]
  satisfaction_intensity: str  # ★/★★/★★★/★★★★/★★★★★
  scene:
    location: str
    lighting: str
    props: list[str]
    weather: str
    time_of_day: str
  script: list[Shot]           # 3-8 个
  key_moments: list[str]
  post_production_notes: list[str]
  memory_updates: dict         # 渲染后由 Memory Manager 校验
  next_episode_seed: str
  continuity_check: dict
```

**关键变量替换规则**:
| 变量 | 来源 | 缺失时行为 |
|---|---|---|
| `season_no / episode_no` | `state.json` | 抛错, 拒跑 |
| `stage / core_conflict / hook_type` | `season-01.json[episodes]` | 抛错, 拒跑 |
| `protagonist_json / youkei_json / apartment_json` | `data/characters/*.json` | 抛错, 拒跑 |
| `knowledge.*` | `data/knowledge/references/*.md` | 起势段可缺 opening-rules, 其他必填 |
| `prev_summary / prev_hook_text` | `memory.json` (上一集写入) | EP01 允许空, 写 "本季首集" |
| `memory.timeline / youkei_state / used_props` | `memory.json` | EP01 允许全空 |

---

### 2.2 `prompts/critic_rubric.yaml` — 5 维评分细则

```yaml
version: "0.2.0"
model: "MiniMax-M3"
temperature: 0.3           # 评审要稳定, 不要随机
max_tokens: 1500

system_prompt: |
  你是资深短视频内容评审, 风格参照 B站/抖音百万粉 UP 主审美。

  对 1 个候选剧本打 5 个维度分 (各 0-10 分, 总分 0-50)。
  最后给出可执行反馈 (一段话, 不超过 200 字), 用于作者重写。

rubric:
  rhythm:
    weight: 1.0
    description: "节奏是否符合 起势/攀升/风暴/决战 四段曲线 + 单集微结构"
    criteria:
      "9-10": "前 3s 即冲突, 情绪波峰精准落在 15%/50%/85%"
      "7-8":  "节奏基本合理, 个别 shot 位置偏 1-2%"
      "5-6":  "节奏平铺直叙, 无明显波峰波谷"
      "0-4":  "节奏拖沓, 90s 装不进 1 个完整故事"
  satisfaction:
    weight: 1.0
    description: "萌点/情感/搞笑密度 + 爽点类型多样性"
    criteria:
      "9-10": "3+ 个爽点, 类型多样 (情感+悬念+打脸), 萌点密度高"
      "7-8":  "2 个爽点, 类型符合本集 stage"
      "5-6":  "1 个爽点, 单调"
      "0-4":  "无爽点, 平淡如水"
  dialog:
    weight: 0.8
    description: "台词区分度 (上坤画外音 vs YouKei 喵语字幕) + 口语化 + 节奏"
    criteria:
      "9-10": "每句台词有角色特色, 节奏断句自然"
      "7-8":  "基本区分, 个别台词书面化"
      "5-6":  "台词雷同, 像同一个人"
      "0-4":  "无台词或台词假"
  format:
    weight: 0.6
    description: "JSON 格式严格符合 schema + 字段完整 + shot 标注规范"
    criteria:
      "9-10": "所有字段填全, shot 标注精确 (景别/位置/时长)"
      "7-8":  "字段齐全, 个别标注模糊"
      "5-6":  "关键字段缺失, 影响拍摄"
      "0-4":  "JSON 解析失败 或 大量字段缺失"
  continuity:
    weight: 1.2             # 连续性最重要, 加权
    description: "与角色档案一致 + 与前后集衔接 + 伏笔回收"
    criteria:
      "9-10": "末钩明确, 与上集钩子自然衔接, 道具/时间线无冲突"
      "7-8":  "基本衔接, 个别道具时间线模糊"
      "5-6":  "与上集脱节, 末钩弱"
      "0-4":  "时间线/道具硬冲突, 无法拍摄"

threshold:
  total_min: 38            # ≥38/50 才算通过
  per_dimension_min: 5     # 任一维度 < 5 直接判 fail

# Island 反馈循环参数
island_loop:
  max_rounds: 2            # 最多重写 2 轮
  improvement_threshold: 3 # 每轮总分必须提升 ≥3 分才继续
```

---

### 2.3 `prompts/hook_distribution.json` — 钩子 5 类阶段分布

```json
{
  "version": "0.2.0",
  "stages": {
    "起势段": {
      "悬念钩": 0.50,
      "情绪钩": 0.50,
      "反转钩": 0.0,
      "信息钩": 0.0,
      "危机钩": 0.0
    },
    "攀升段": {
      "悬念钩": 0.25,
      "反转钩": 0.25,
      "情绪钩": 0.25,
      "信息钩": 0.25,
      "危机钩": 0.0
    },
    "风暴段": {
      "悬念钩": 0.0,
      "反转钩": 0.50,
      "信息钩": 0.25,
      "危机钩": 0.25,
      "情绪钩": 0.0
    },
    "决战段": {
      "悬念钩": 0.0,
      "反转钩": 0.0,
      "情绪钩": 0.0,
      "信息钩": 0.0,
      "危机钩": 1.0
    }
  },
  "season_01_actual": "见 data/seasons/season-01.json hook_type_distribution_config"
}
```

---

### 2.4 `prompts/memory_constraints.yaml` — 硬约束规则

```yaml
version: "0.2.0"

# 这份配置给 Agent 3 (Memory Manager) 做硬约束检测用, 不注入 LLM
constraints:
  timeline:
    - rule: "absolute_time_never_goes_back"
      description: "时间线绝不倒退"
      check: "new_episode.timeline.now >= last_episode.timeline.now"
      on_fail: "reject + log error"
      
  prop_states:
    - rule: "consumed_prop_cannot_be_consumed_again"
      description: "已吃完/已用完的道具不能再次消耗"
      check: "for prop in new_episode.props_consumed: prop not in memory.consumed_props"
      on_fail: "reject + log error + suggest alternative prop"
    - rule: "prop_location_consistent"
      description: "道具位置不能瞬移 (除非剧情明确说明)"
      check: "prop.last_location == prop.previous_location OR scene explicitly moves it"
      on_fail: "warn (warning, not reject)"

  character_states:
    - rule: "youkei_age_never_decreases"
      description: "YouKei 月龄只增不减"
      check: "new_episode.youkei_age_months >= memory.youkei_age_months"
      on_fail: "reject + log error"
    - rule: "youkei_mood_within_range"
      description: "YouKei 情绪只能在允许值内"
      allowed: ["happy", "curious", "sleepy", "annoyed", "scared", "hungry", "tired_compliant"]
      on_fail: "warn"
    - rule: "protagonist_never_dead"
      description: "上坤绝不'死' (这是日常向不是剧情向)"
      check: "memory.protagonist.alive == True"
      on_fail: "reject"

  hook_chain:
    - rule: "prev_hook_must_be_recovered"
      description: "上集末钩子必须在本集某 shot 中被回收"
      check: "for hook in prev_episode.shots[?is_hook]: hook.text mentioned in new_episode.shots[].action|dialog"
      on_fail: "warn + suggest explicit recovery in writer retry"
    - rule: "next_hook_must_set"
      description: "本集必须有末钩 (除 EP12 末集外)"
      check: "episode_no != 12 → new_episode.shots[-1].is_hook == True"
      on_fail: "reject"

  season_arc:
    - rule: "episode_within_season"
      description: "集号必须在季范围内"
      check: "1 <= episode_no <= season.total_episodes"
      on_fail: "reject"
    - rule: "stage_position_monotonic"
      description: "stage_position_pct 必须单调递增"
      check: "new_episode.stage_position_pct > last_episode.stage_position_pct (or season restart)"
      on_fail: "warn"
```

---

## 3. Agent 代码骨架 (P5/P6/P7 落地用)

### 3.1 `src/types.py` — Pydantic 数据类 (P5 必先)

```python
"""Pydantic schemas — 严格数据契约, 所有 Agent 进出都用这套"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

HookType = Literal["悬念钩", "反转钩", "情绪钩", "信息钩", "危机钩"]
SatisfactionType = Literal["情感爆发", "悬念揭秘", "打脸复仇", "逆袭翻盘", "身份碾压"]
Stage = Literal["起势段", "攀升段", "风暴段", "决战段"]


class Shot(BaseModel):
    shot: int = Field(ge=1)
    duration_s: int = Field(ge=1, le=30)
    shot_type: str  # 特写/中景/全景/远景
    shot_position: str  # "前 30s 钩子段" / "中段冲突升级" / "末 3s 钩子"
    subject: str
    action: str
    dialog: Optional[str]
    sfx: Optional[str]
    mood: str
    emotion_intensity: int = Field(ge=0, le=5)
    is_climax: bool = False
    is_hook: bool = False
    hook_subtype: Optional[str] = None
    hook_text: Optional[str] = None


class Scene(BaseModel):
    location: str
    lighting: str
    props: list[str]
    weather: str
    time_of_day: str


class ContinuityCheck(BaseModel):
    characters_present: list[str]
    location_previous_ep: str
    time_gap: str
    mood: str


class MemoryUpdate(BaseModel):
    youkei_state_after: dict
    prop_used: list[str]
    prop_consumed: list[str] = []    # 已吃完/用完
    timeline: str  # ISO 8601
    hook_chain: str


class CriticScore(BaseModel):
    rhythm: int = Field(ge=0, le=10)
    satisfaction: int = Field(ge=0, le=10)
    dialog: int = Field(ge=0, le=10)
    format: int = Field(ge=0, le=10)
    continuity: int = Field(ge=0, le=10)
    total: int = Field(ge=0, le=50)
    feedback: str

    @field_validator("total")
    @classmethod
    def compute_total(cls, v, info):
        return (info.data["rhythm"] + info.data["satisfaction"] +
                info.data["dialog"] + info.data["format"] +
                info.data["continuity"])


class EpisodeScript(BaseModel):
    season: int
    episode: int
    title: str
    duration_estimate: str
    logline: str
    stage: Stage
    stage_position_pct: int = Field(ge=0, le=100)
    hook_type: Optional[HookType]
    hook_subtype: Optional[str]
    hook_text: Optional[str]
    satisfaction_types: list[SatisfactionType]
    satisfaction_intensity: Literal["★", "★★", "★★★", "★★★★", "★★★★★"]
    scene: Scene
    script: list[Shot] = Field(min_length=3, max_length=8)
    key_moments: list[str]
    post_production_notes: list[str]
    memory_updates: MemoryUpdate
    next_episode_seed: str
    continuity_check: ContinuityCheck
    critic_score: Optional[CriticScore] = None
```

---

### 3.2 `src/llm_client.py` — minimax M3 wrapper (P5, 复用 obsidian-novel-publisher 的写法)

```python
"""LLM client — Anthropic 兼容 + stream + 切 M2.7 写小说专用

关键决策 (来自 obsidian-novel-publisher v0.40 治本修复):
- 用 /anthropic 端点拿 stop_reason
- 切 M2.7 (60 TPS, 写作模型) 而非 M3 (Coding 优化)
- stream=True 避免 180s thinking 卡死
"""
import os
import json
import logging
import requests
from typing import Iterator

logger = logging.getLogger("yk-script.llm")


class LLMError(Exception):
    pass


class MinimaxClient:
    BASE_URL = "https://api.minimaxi.com/anthropic"  # ← 不是 /v1
    DEFAULT_MODEL = "MiniMax-M2.7"                  # ← 写作用 M2.7

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ["MINIMAXI_API_KEY"]
        self.model = model or self.DEFAULT_MODEL
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        })

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.9,
        max_tokens: int = 4000,
        stream: bool = True,
        max_retries: int = 3,
    ) -> str:
        """单次生成 — stream 拼接 + stop_reason 校验 + exp backoff retry"""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }

        for attempt in range(max_retries):
            try:
                if stream:
                    return self._stream_generate(payload)
                else:
                    return self._block_generate(payload)
            except (requests.RequestException, LLMError) as e:
                wait = 2 ** attempt
                logger.warning(f"LLM retry {attempt+1}/{max_retries} after {wait}s: {e}")
                time.sleep(wait)
        raise LLMError(f"LLM failed after {max_retries} retries")

    def _stream_generate(self, payload: dict) -> str:
        """Anthropic SSE stream 解析 + thinking 块过滤"""
        full_text = ""
        stop_reason = None
        with self.session.post(
            f"{self.BASE_URL}/v1/messages",
            json=payload,
            stream=True,
            timeout=180,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith(b"data: "):
                    continue
                data = json.loads(line[6:])
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        full_text += delta["text"]
                elif data.get("type") == "message_delta":
                    stop_reason = data.get("delta", {}).get("stop_reason")

        if stop_reason not in ("end_turn",):
            raise LLMError(f"Unexpected stop_reason: {stop_reason}, text len={len(full_text)}")
        return full_text

    def _block_generate(self, payload: dict) -> str:
        """非流式兜底 (测试用)"""
        payload["stream"] = False
        resp = self.session.post(
            f"{self.BASE_URL}/v1/messages",
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        stop_reason = data.get("stop_reason")
        if stop_reason != "end_turn":
            raise LLMError(f"Unexpected stop_reason: {stop_reason}")
        return data["content"][0]["text"]
```

---

### 3.3 `src/screen_writer.py` — Agent 1 骨架 (P5)

```python
"""Agent 1 · Screenwriter — 借鉴 COMIC Island, 生成 N=3 候选剧本"""
from __future__ import annotations
import json
import logging
import yaml
from pathlib import Path
from jinja2 import Template

from .llm_client import MinimaxClient, LLMError
from .types import EpisodeScript

logger = logging.getLogger("yk-script.writer")

KNOWLEDGE_DIR = Path("data/knowledge/references")


class ScreenWriter:
    def __init__(self, llm: MinimaxClient, prompt_path: Path = Path("prompts/writer.yaml")):
        self.llm = llm
        self.prompt_cfg = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))

    def generate_n_candidates(
        self,
        season_no: int,
        episode_no: int,
        episode_def: dict,         # 来自 season-N.json
        characters: dict,          # {protagonist, youkei, apartment}
        memory: dict,              # 上一集状态
        prev_summary: str,
        prev_hook_text: str | None,
        knowledge: dict[str, str], # {opening_rules, hook_design, ...}
        n: int = 3,
    ) -> list[EpisodeScript]:
        """生成 N 个独立候选, 借鉴 COMIC Island
        
        每个候选独立 prompt (different seed via temperature 0.9 + shuffle_shot_order)
        """
        candidates = []
        for i in range(n):
            try:
                user_prompt = self._render_user_prompt(
                    season_no, episode_no, episode_def,
                    characters, memory, prev_summary, prev_hook_text, knowledge,
                    candidate_seed=i,  # 让每个候选略有差异
                )
                system_prompt = self.prompt_cfg["system_prompt"]
                raw = self.llm.generate(
                    system=system_prompt,
                    user=user_prompt,
                    temperature=self.prompt_cfg.get("temperature", 0.9),
                    max_tokens=self.prompt_cfg.get("max_tokens", 4000),
                )
                script = self._parse_strict(raw, episode_no)
                candidates.append(script)
                logger.info(f"Candidate {i+1}/{n} generated: {script.title}")
            except (LLMError, json.JSONDecodeError, ValueError) as e:
                logger.error(f"Candidate {i+1} failed: {e}")
                # 不抛错, 让 Critic 用剩下的候选打分
        if not candidates:
            raise RuntimeError(f"All {n} candidates failed for EP{episode_no}")
        return candidates

    def _render_user_prompt(
        self, season_no, episode_no, episode_def, characters, memory,
        prev_summary, prev_hook_text, knowledge, candidate_seed,
    ) -> str:
        """用 Jinja2 渲染 user_prompt_template"""
        template = Template(self.prompt_cfg["user_prompt_template"])
        return template.render(
            season_no=season_no,
            episode_no=episode_no,
            total_episodes=12,
            stage=episode_def["stage"],
            stage_position_pct=episode_def["stage_position_pct"],
            episode=episode_def,
            protagonist_json=json.dumps(characters["protagonist"], ensure_ascii=False, indent=2),
            youkei=characters["youkei"],
            youkei_json=json.dumps(characters["youkei"], ensure_ascii=False, indent=2),
            apartment_json=json.dumps(characters["apartment"], ensure_ascii=False, indent=2),
            knowledge=knowledge,
            memory=memory,
            prev_summary=prev_summary or "(本季首集)",
            prev_hook_text=prev_hook_text or "(本季首集, 无上集钩子)",
            candidate_seed=candidate_seed,
        )

    def _parse_strict(self, raw: str, episode_no: int) -> EpisodeScript:
        """严格 JSON 解析 + Pydantic 校验 + 字段修复"""
        # 1. 提取 JSON (LLM 可能输出 ```json ... ``` 包裹)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        # 2. 解析
        data = json.loads(raw)
        # 3. Pydantic 校验 — 失败抛 ValidationError
        script = EpisodeScript.model_validate(data)
        if script.episode != episode_no:
            raise ValueError(f"Episode mismatch: expected {episode_no}, got {script.episode}")
        return script
```

---

### 3.4 `src/critic.py` — Agent 2 骨架 (P6)

```python
"""Agent 2 · Critic — 5 维评分 + Island 反馈循环 + 借鉴 COMIC"""
from __future__ import annotations
import json
import logging
import yaml
from .llm_client import MinimaxClient, LLMError
from .types import EpisodeScript, CriticScore
from .screen_writer import ScreenWriter

logger = logging.getLogger("yk-script.critic")


class Critic:
    def __init__(
        self,
        llm: MinimaxClient,
        writer: ScreenWriter,
        rubric_path: str = "prompts/critic_rubric.yaml",
    ):
        self.llm = llm
        self.writer = writer
        self.cfg = yaml.safe_load(open(rubric_path, encoding="utf-8").read())
        self.threshold = self.cfg["threshold"]["total_min"]
        self.per_dim_min = self.cfg["threshold"]["per_dimension_min"]

    def evaluate(
        self,
        candidates: list[EpisodeScript],
        max_rounds: int = 2,
        improvement_threshold: int = 3,
    ) -> tuple[EpisodeScript, CriticScore]:
        """借鉴 COMIC Island:
        1. 对所有候选打分
        2. 选最高分; 若 < threshold, 用赢家反馈让 Writer 重写一轮
        3. 最多 max_rounds 轮
        
        Returns: (best_script, best_score)
        """
        current = candidates
        best = None
        best_score = None

        for round_idx in range(max_rounds + 1):
            scored = [self._score_one(c) for c in current]
            best = max(scored, key=lambda x: x[1].total)
            best_script, best_score = best

            logger.info(
                f"Round {round_idx}: best='{best_script.title}' "
                f"total={best_score.total}/50 "
                f"feedback='{best_score.feedback[:80]}...'"
            )

            if best_score.total >= self.threshold and not self._any_dim_fail(best_score):
                logger.info(f"✅ Threshold {self.threshold} met, accepted")
                best_script.critic_score = best_score
                return best_script, best_score

            if round_idx >= max_rounds:
                logger.warning(
                    f"❌ Max rounds {max_rounds} reached, "
                    f"best total={best_score.total} < threshold={self.threshold}, "
                    f"sending failure alert"
                )
                best_script.critic_score = best_score
                return best_script, best_score  # 兜底: 用最高分, 标记 alert

            # Island 反馈: 让 Writer 用赢家反馈重写 N=3 个候选
            logger.info(f"Round {round_idx+1}: triggering rewrite with feedback")
            # (需要把 candidates 替换为新的; 简化版: 复用 generate_n_candidates, 
            #  但传入 feedback。这里简化, 重写时把 feedback 注入 user prompt)
            # TODO P6: 实现 feedback injection
            current = self.writer.generate_n_candidates_with_feedback(
                best_script, best_score.feedback, n=3
            )

    def _score_one(self, script: EpisodeScript) -> tuple[EpisodeScript, CriticScore]:
        """调 LLM 评审 1 个候选"""
        system = self.cfg["system_prompt"]
        user = self._build_user_prompt(script)
        raw = self.llm.generate(
            system=system, user=user,
            temperature=self.cfg.get("temperature", 0.3),
            max_tokens=self.cfg.get("max_tokens", 1500),
        )
        score = self._parse_score(raw)
        return script, score

    def _build_user_prompt(self, script: EpisodeScript) -> str:
        return f"""请评审以下候选剧本 (返回严格 JSON):

```json
{json.dumps(script.model_dump(), ensure_ascii=False, indent=2)}
```

返回格式:
```json
{{
  "rhythm": 0-10,
  "satisfaction": 0-10,
  "dialog": 0-10,
  "format": 0-10,
  "continuity": 0-10,
  "total": 0-50,
  "feedback": "200 字内可执行反馈, 用于作者重写"
}}
```"""

    def _parse_score(self, raw: str) -> CriticScore:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        data = json.loads(raw)
        return CriticScore.model_validate(data)

    def _any_dim_fail(self, score: CriticScore) -> bool:
        dims = [score.rhythm, score.satisfaction, score.dialog, score.format, score.continuity]
        return any(d < self.per_dim_min for d in dims)
```

---

### 3.5 `src/memory_manager.py` — Agent 3 骨架 (P7)

```python
"""Agent 3 · Memory Manager — 借鉴 ShakeDrama memory_manager.py + 硬约束"""
from __future__ import annotations
import json
import logging
import yaml
from datetime import datetime, timedelta
from pathlib import Path

from .types import EpisodeScript

logger = logging.getLogger("yk-script.memory")


class MemoryViolation(Exception):
    """硬约束违反, 应拒绝该剧本"""
    pass


class MemoryWarning:
    """软警告, 不拒绝但记录"""
    pass


class MemoryManager:
    def __init__(
        self,
        memory_path: Path = Path("data/state/memory.json"),
        constraints_path: Path = Path("prompts/memory_constraints.yaml"),
    ):
        self.memory_path = memory_path
        self.memory = self._load()
        self.constraints = yaml.safe_load(constraints_path.read_text(encoding="utf-8"))

    def _load(self) -> dict:
        if not self.memory_path.exists():
            return self._init_memory()
        return json.loads(self.memory_path.read_text(encoding="utf-8"))

    def _init_memory(self) -> dict:
        return {
            "youkei_age_months": 7,
            "youkei_state": {"location": "客厅", "mood": "curious", "wet": False},
            "protagonist_state": {"alive": True, "location": "客厅"},
            "timeline": {"now": "2026-MM-DD 09:00", "last_episode_id": None},
            "consumed_props": [],   # 已吃完/用完的道具
            "used_props_this_ep": [],
            "hook_chain": [],       # [{"ep": 5, "text": "..."}]
            "episode_summaries": [],  # [{"ep": 1, "summary": "..."}]
        }

    def hard_check(
        self, script: EpisodeScript, prev_episode: dict | None
    ) -> tuple[bool, list[str]]:
        """硬约束检测 — 失败抛 MemoryViolation (return False)
        
        Returns: (is_valid, list_of_errors)
        """
        errors = []
        warnings = []

        # 1. 时间线绝不倒退
        if prev_episode:
            last_timeline = prev_episode["memory_updates"]["timeline"]
            new_timeline = script.memory_updates.timeline
            if new_timeline < last_timeline:
                errors.append(
                    f"timeline_regression: prev={last_timeline}, new={new_timeline}"
                )

        # 2. YouKei 月龄只增不减
        if script.memory_updates.youkei_state_after.get("age_months", 7) < self.memory["youkei_age_months"]:
            errors.append("youkei_age_decreased")

        # 3. 已消耗道具不能再用
        for prop in script.memory_updates.prop_consumed:
            if prop in self.memory["consumed_props"]:
                errors.append(f"consumed_prop_reused: {prop}")

        # 4. 上集末钩子必须回收 (软警告, 不 reject)
        if prev_episode and prev_episode.get("hook_text"):
            recovered = self._check_hook_recovery(
                prev_episode["hook_text"], script
            )
            if not recovered:
                warnings.append(f"prev_hook_not_recovered: '{prev_episode['hook_text'][:50]}...'")

        # 5. 末钩必设 (除 EP12)
        if script.episode != 12 and not script.script[-1].is_hook:
            errors.append("missing_final_hook")

        # 6. 主角不能死
        if not script.continuity_check.characters_present or "上坤" not in script.continuity_check.characters_present:
            errors.append("protagonist_missing")

        is_valid = len(errors) == 0

        for e in errors:
            logger.error(f"❌ Memory violation: {e}")
        for w in warnings:
            logger.warning(f"⚠️ Memory warning: {w}")

        return is_valid, errors

    def _check_hook_recovery(self, prev_hook: str, script: EpisodeScript) -> bool:
        """检查上集末钩子是否在本集某 shot 中被回收"""
        # 简化: 在 shot.action / dialog 中搜索关键词
        keywords = self._extract_keywords(prev_hook)
        for shot in script.script:
            text = f"{shot.action} {shot.dialog or ''}"
            if any(kw in text for kw in keywords):
                return True
        return False

    def _extract_keywords(self, text: str) -> list[str]:
        """从钩子文本提取 2-3 个关键词 (简化版: 名词)"""
        # TODO: 用 jieba, 当前简化: 取 "YouKei/主人/鱼/..." 等专有名词
        return ["YouKei", "上坤", "鱼", "沙发", "阳台"]

    def extract_state(self, script: EpisodeScript) -> dict:
        """从已校验的剧本中提取新状态"""
        return {
            "youkei_age_months": script.memory_updates.youkei_state_after.get("age_months", self.memory["youkei_age_months"]),
            "youkei_state": script.memory_updates.youkei_state_after,
            "protagonist_state": {"alive": True, "location": script.scene.location},
            "timeline": {
                "now": script.memory_updates.timeline,
                "last_episode_id": f"S{script.season:02d}-EP{script.episode:02d}",
            },
            "consumed_props": list(set(
                self.memory["consumed_props"] + script.memory_updates.prop_consumed
            )),
            "used_props_this_ep": script.memory_updates.prop_used,
            "hook_chain": self.memory["hook_chain"] + [
                {"ep": script.episode, "text": script.hook_text or ""}
            ],
            "episode_summaries": self.memory["episode_summaries"] + [
                {"ep": script.episode, "summary": script.logline}
            ],
        }

    def save(self) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text(
            json.dumps(self.memory, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"Memory saved: {self.memory_path}")
```

---

### 3.6 `src/daily.py` — 主入口 (P8)

```python
"""主入口 — cron 06:00 触发, 全链路编排"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from .llm_client import MinimaxClient
from .screen_writer import ScreenWriter
from .critic import Critic
from .memory_manager import MemoryManager
from .markdown_renderer import render_episode
from .hmac_client import publish_to_obsidian
from .state import StateStore
from .logger import setup_logger
from .outline_fetcher import OutlineFetcher        # 🆕 P12
from .backup_reader import BackupReader           # 🆕 P12
from .github_backup import GithubBackup, GithubBackupConfig  # 🆕 P13
from .wechat_notifier import (                    # 🆕 P14
    WechatNotifierConfig, notify_success, notify_failure,
)

logger = setup_logger("yk-script")


def main(dry_run: bool = False, force_episode: int | None = None) -> int:
    """全链路编排, 返回 exit code (0=成功, 1=失败)"""
    start = datetime.now()
    logger.info(f"=== yk-script daily run start: {start.isoformat()} ===")

    # ① 加载所有数据
    state_store = StateStore("data/state/state.json")
    state = state_store.load()

    # ①a 🆕 从 GitHub 拉取最新 season 大纲 (老板手动编辑后能用上)
    #     失败 → fallback 本地 data/seasons/season-XX.json
    outline_fetcher = OutlineFetcher(
        repo="blackclaw0318/obsidian-yk-script",
        token=os.environ["GITHUB_BACKUP_TOKEN"],
        cache_dir=Path("data/cache"),
    )
    season = outline_fetcher.fetch_season(state["season_no"])
    logger.info(
        f"outline fetched: season={state['season_no']}, "
        f"sha={outline_fetcher.last_sha[:8] if outline_fetcher.last_sha else 'cache'}..."
    )

    characters = _load_characters_from_github_or_local(
        state["season_no"], outline_fetcher
    )
    memory_mgr = MemoryManager("data/state/memory.json")
    knowledge = _load_knowledge_for_stage(
        season["episodes"][state["episode_idx"]]["stage"]
    )

    # ② 决定本集
    ep_idx = force_episode if force_episode else state["episode_idx"]
    episode_def = season["episodes"][ep_idx]
    prev_summary, prev_hook_text = _get_prev_episode_info(
        memory_mgr, ep_idx
    )

    # ③ Agent 1: 生成 N=3 候选
    llm = MinimaxClient()
    writer = ScreenWriter(llm)
    candidates = writer.generate_n_candidates(
        season_no=state["season_no"],
        episode_no=episode_def["ep"],
        episode_def=episode_def,
        characters=characters,
        memory=memory_mgr.memory,
        prev_summary=prev_summary,
        prev_hook_text=prev_hook_text,
        knowledge=knowledge,
        n=3,
    )

    # ④ Agent 2: 5 维评分 + Island 反馈循环
    critic = Critic(llm, writer)
    best_script, best_score = critic.evaluate(candidates, max_rounds=2)

    # ⑤ Agent 3: 硬约束检测
    is_valid, errors = memory_mgr.hard_check(best_script, prev_episode=memory_mgr.memory.get("last_episode"))
    if not is_valid:
        logger.error(f"Hard check failed: {errors}")
        # 触发 Agent 1 重写 1 次
        logger.info("Retrying writer once after hard check fail...")
        candidates = writer.generate_n_candidates(
            season_no=state["season_no"],
            episode_no=episode_def["ep"],
            episode_def=episode_def,
            characters=characters,
            memory=memory_mgr.memory,
            prev_summary=prev_summary + "\n\n⚠️ PREVIOUS ATTEMPT FAILED:\n" + "\n".join(errors),
            prev_hook_text=prev_hook_text,
            knowledge=knowledge,
            n=3,
        )
        best_script, best_score = critic.evaluate(candidates, max_rounds=1)
        is_valid, errors = memory_mgr.hard_check(best_script, prev_episode=memory_mgr.memory.get("last_episode"))
        if not is_valid:
            logger.error(f"Retry also failed: {errors}, sending alert")
            _alert_failure(episode_def, errors)
            return 1

    # ⑥ 渲染 Markdown
    md = render_episode(best_script)

    # ⑦ 推送 (or dry-run 跳过)
    post_url = None
    if dry_run:
        logger.info(f"DRY-RUN: would publish {best_script.title}")
        Path("output").mkdir(exist_ok=True)
        Path(f"output/{best_script.title}.md").write_text(md, encoding="utf-8")
    else:
        result = publish_to_obsidian(
    if dry_run:
        logger.info(f"DRY-RUN: would publish {best_script.title}")
        Path("output").mkdir(exist_ok=True)
        Path(f"output/{best_script.title}.md").write_text(md, encoding="utf-8")
    else:
        result = publish_to_obsidian(
            slug=f"yk-s{state['season_no']:02d}-ep{episode_def['ep']:02d}",
            title=f"EP{episode_def['ep']:02d} · {best_script.title}",
            excerpt=best_script.logline,
            content_md=md,
            category="life",
            tags=["YouKei", "缅因猫", "日常", f"季{state['season_no']}-EP{episode_def['ep']:02d}", "生活vlog"],
            external_meta=best_script.model_dump(),
        )
        if not result["success"]:
            logger.error(f"Publish failed: {result['error']}")
            _alert_failure(episode_def, [result["error"]])
            return 1
        post_url = result.get("post_url")

    # ⑧ 🆕 备份到 GitHub (失败不阻塞, 只记警告)
    try:
        backup_cfg = GithubBackupConfig.from_env()
        backup = GithubBackup(backup_cfg)
        backup.backup_episode(
            season_no=state["season_no"],
            episode_no=episode_def["ep"],
            script=best_script,
            markdown=md,
            post_url=post_url or "",
            llm_usage={"model": "MiniMax-M2.7", "duration_ms": int(duration * 1000)},
        )
        logger.info(f"✅ GitHub backup done for S{state['season_no']:02d}-EP{episode_def['ep']:02d}")
    except Exception as e:
        # 备份失败 → log warning + 微信告警, 不 throw
        logger.warning(f"⚠️ GitHub backup failed (non-fatal): {e}")
        try:
            wechat_cfg = WechatNotifierConfig.from_env()
            notify_failure(
                wechat_cfg,
                season_no=state["season_no"],
                episode_no=episode_def["ep"],
                title=best_script.title,
                error_short=f"GitHub 备份失败 (主推送已成功): {type(e).__name__}",
            )
        except Exception:
            pass

    # ⑨ 🆕 微信通知 (成功)
    try:
        wechat_cfg = WechatNotifierConfig.from_env()
        notify_success(
            wechat_cfg,
            season_no=state["season_no"],
            episode_no=episode_def["ep"],
            title=best_script.title,
            score=best_score.total,
            hook_type=best_script.hook_type or "—",
            post_url=post_url or "",
        )
    except Exception as e:
        logger.warning(f"WeChat notify failed (non-fatal): {e}")

    # ⑧ 更新 memory + state
    memory_mgr.memory = memory_mgr.extract_state(best_script)
    memory_mgr.memory["last_episode"] = best_script.model_dump()
    memory_mgr.save()

    state_store.update(
        next_episode_idx=ep_idx + 1,
        last_run_at=datetime.now().isoformat(),
        last_episode_title=best_script.title,
    )

    duration = (datetime.now() - start).total_seconds()
    logger.info(
        f"=== yk-script daily run END: {duration:.1f}s, "
        f"ep='{best_script.title}', score={best_score.total}/50 ==="
    )
    return 0


def _load_characters_from_github_or_local(season_no: int, fetcher: OutlineFetcher) -> dict:
    """角色卡优先从 GitHub 拉 (boss 可手动编辑), 失败 fallback 本地"""
    chars = {}
    for name in ["protagonist", "youkei", "apartment"]:
        try:
            data = fetcher.fetch_character(season_no, name)
            chars[name] = data
        except Exception as e:
            logger.warning(f"fetch {name}.json from GitHub failed ({e}), fallback local")
            chars[name] = json.loads(
                Path(f"data/characters/{name}.json").read_text(encoding="utf-8")
            )
    return chars


def _load_knowledge_for_stage(stage: str) -> dict[str, str]:
    """按 stage 只加载相关 5 份 references (其他不浪费 token)"""
    refs_dir = Path("data/knowledge/references")
    loaded = {
        "hook_design": (refs_dir / "hook-design.md").read_text(encoding="utf-8"),
        "rhythm_curve": (refs_dir / "rhythm-curve.md").read_text(encoding="utf-8"),
        "satisfaction_matrix": (refs_dir / "satisfaction-matrix.md").read_text(encoding="utf-8"),
        "genre_guide": (refs_dir / "genre-guide.md").read_text(encoding="utf-8"),
    }
    if stage == "起势段":
        loaded["opening_rules"] = (refs_dir / "opening-rules.md").read_text(encoding="utf-8")
    elif stage in ("风暴段", "决战段"):
        loaded["compliance_checklist"] = (refs_dir / "compliance-checklist.md").read_text(encoding="utf-8")
    return loaded


def _get_prev_episode_info(memory_mgr: MemoryManager, ep_idx: int) -> tuple[str, str | None]:
    summaries = memory_mgr.memory.get("episode_summaries", [])
    hooks = memory_mgr.memory.get("hook_chain", [])
    if ep_idx == 0:
        return "", None
    prev_summary = next((s["summary"] for s in summaries if s["ep"] == ep_idx), "")
    prev_hook = next((h["text"] for h in hooks if h["ep"] == ep_idx), None)
    return prev_summary, prev_hook


def _alert_failure(episode_def: dict, errors: list[str]) -> None:
    """告警: 写日志 + 推微信 (复用 obsidian-novel-publisher 微信 notifier 模式)"""
    logger.critical(f"DAILY RUN FAILED: {episode_def.get('title')} errors={errors}")
    # TODO P11: 复用 publisher 的 wechat_notifier 模式
    # 临时: 写 logs/alert.txt, 由 cron 兜底发送
    alert_path = Path("logs/alert.txt")
    alert_path.parent.mkdir(exist_ok=True)
    with alert_path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()}\t{episode_def.get('title')}\t{errors}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-episode", type=int, default=None)
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run, force_episode=args.force_episode))
```

---

### 3.7 🆕 `src/backup_reader.py` — GitHub Contents API 只读客户端 (P12)

```python
"""GitHub Contents API 只读客户端 — 拉 season 大纲 + 角色卡

设计原则 (对标 obsidian-novel-publisher/src/backup_reader.py):
- 走 Contents API GET /repos/{owner}/{repo}/contents/{path}
- 不 clone 仓 (轻量, 老板在 GitHub UI 手编 → publisher 拉最新)
- 4xx 不重试, 5xx / 网络错重试 3 次 (1s/2s/4s 指数退避)
- 返 (content, sha) — sha 给 caller 做变更检测

凭据: GITHUB_BACKUP_TOKEN (Fine-grained PAT, 至少 Contents: Read on obsidian-yk-script)
"""
from __future__ import annotations
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
_RETRY_BACKOFF_S = (1, 2, 4)


class BackupReaderError(Exception):
    pass


class BackupReader:
    def __init__(
        self,
        repo: str,
        token: str,
        branch: str = "main",
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        api_base: str = GITHUB_API_BASE,
    ):
        if "/" not in repo:
            raise ValueError(f"repo 必须是 'owner/name' 格式: {repo!r}")
        if not token or not token.strip():
            raise ValueError("token 不能为空")
        self.owner, self.name = repo.split("/", 1)
        self.token = token
        self.branch = branch
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.api_base = api_base.rstrip("/")

    def fetch_file(self, path: str) -> dict[str, Any]:
        """拉单个文件 — 返 {content, sha, size, path}

        Raises:
            BackupReaderError: 4xx 参数错 / 重试耗尽
        """
        url = f"{self.api_base}/repos/{self.owner}/{self.name}/contents/{path}"
        params = {"ref": self.branch}
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(
                    url, params=params, headers=headers,
                    timeout=self.timeout_s,
                )
                if 400 <= resp.status_code < 500:
                    # 4xx 不重试 (401 token 错 / 404 文件不存在)
                    raise BackupReaderError(
                        f"GitHub 4xx {resp.status_code}: {resp.text[:200]}"
                    )
                resp.raise_for_status()
                data = resp.json()
                content_bytes = base64.b64decode(data["content"])
                return {
                    "content": content_bytes.decode("utf-8"),
                    "sha": data["sha"],
                    "size": data["size"],
                    "path": data["path"],
                }
            except requests.RequestException as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    wait = _RETRY_BACKOFF_S[attempt]
                    logger.warning(
                        f"[backup_reader] fetch {path} 失败, "
                        f"{wait}s 后重试 ({attempt+1}/{self.max_retries}): {e}"
                    )
                    time.sleep(wait)
        raise BackupReaderError(
            f"fetch {path} 重试 {self.max_retries} 次耗尽: {last_err}"
        )

    def fetch_json(self, path: str) -> dict[str, Any]:
        """拉 + 解析 JSON"""
        result = self.fetch_file(path)
        return json.loads(result["content"])
```

---

### 3.8 🆕 `src/outline_fetcher.py` — 大纲拉取 + sha 缓存 + fallback (P12)

```python
"""大纲拉取器 — 老板手编 GitHub → publisher 拉 → sha 检测变更

关键设计:
- 每次 daily 启动先拉 GitHub → 拿 (content, sha)
- 对比 data/cache/season-XX.sha 旧 sha:
  - 变了 → 用新的, log '老板改了新大纲'
  - 没变 → 用缓存加速 (不用再解析)
- GitHub 拉失败 → fallback 本地 data/seasons/season-XX.json
  - 本地再无 → 抛错 (启动失败, 不准跑)

缓存路径:
  data/cache/season-XX.json  ← 内容
  data/cache/season-XX.sha   ← sha (单行字符串)
  data/cache/<char>.json     ← 角色卡
"""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .backup_reader import BackupReader, BackupReaderError

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/cache")


@dataclass
class FetchResult:
    content: dict | str
    sha: str
    is_changed: bool   # 相对上次缓存, sha 变了 = True
    cache_path: Path
    error: str | None = None  # GitHub 拉取失败时记录 (但仍用缓存/本地)


class OutlineFetcher:
    def __init__(self, repo: str, token: str, cache_dir: Path = DEFAULT_CACHE_DIR):
        self.reader = BackupReader(repo=repo, token=token)
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_sha: str | None = None

    def _cache_paths(self, remote_path: str) -> tuple[Path, Path]:
        """从 'data/seasons/season-01.json' → ('cache/season-01.json', 'cache/season-01.sha')"""
        # 路径扁平化: data/seasons/season-01.json → season-01.json
        #              data/characters/youkei.json → youkei.json
        basename = Path(remote_path).name
        return self.cache_dir / basename, self.cache_dir / f"{basename}.sha"

    def _read_cached_sha(self, sha_path: Path) -> str | None:
        if not sha_path.exists():
            return None
        return sha_path.read_text(encoding="utf-8").strip() or None

    def _write_cache(
        self, content_path: Path, sha_path: Path, content: str, sha: str
    ) -> None:
        """atomic write — 先写 .tmp, 再 rename"""
        tmp = content_path.with_suffix(content_path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(content_path)  # atomic
        sha_path.write_text(sha, encoding="utf-8")

    def fetch_season(self, season_no: int) -> dict:
        """拉 season 大纲 (GitHub → cache → 本地 fallback)"""
        return self._fetch_dict(
            remote_path=f"data/seasons/season-{season_no:02d}.json",
            fallback_local=f"data/seasons/season-{season_no:02d}.json",
        )

    def fetch_character(self, season_no: int, char_name: str) -> dict:
        """拉角色卡 (GitHub → cache → 本地 fallback)"""
        return self._fetch_dict(
            remote_path=f"data/characters/{char_name}.json",
            fallback_local=f"data/characters/{char_name}.json",
        )

    def _fetch_dict(self, remote_path: str, fallback_local: str) -> dict:
        content_path, sha_path = self._cache_paths(remote_path)
        old_sha = self._read_cached_sha(sha_path)

        # 1. 尝试 GitHub
        try:
            result = self.reader.fetch_file(remote_path)
            new_sha = result["sha"]
            self.last_sha = new_sha

            if new_sha != old_sha:
                # 老板改了新大纲
                self._write_cache(content_path, sha_path, result["content"], new_sha)
                logger.info(
                    f"📥 outline changed: {remote_path} "
                    f"sha={old_sha[:8] if old_sha else 'None'} → {new_sha[:8]}"
                )
                is_changed = True
            else:
                logger.debug(f"outline unchanged: {remote_path} sha={new_sha[:8]}")
                is_changed = False

            return json.loads(result["content"])

        except BackupReaderError as e:
            logger.warning(
                f"⚠️ GitHub fetch {remote_path} failed: {e}, "
                f"trying cache + local fallback"
            )
            # 2. Fallback: cache
            if content_path.exists():
                logger.info(f"using cached: {content_path}")
                self.last_sha = old_sha
                return json.loads(content_path.read_text(encoding="utf-8"))
            # 3. Fallback: 本地
            local_path = Path(fallback_local)
            if local_path.exists():
                logger.info(f"using local: {local_path}")
                return json.loads(local_path.read_text(encoding="utf-8"))
            # 4. 全失败
            raise RuntimeError(
                f"Cannot load {remote_path}: GitHub 404 + cache 缺失 + 本地缺失"
            )
```

---

### 3.9 🆕 `src/github_backup.py` — 每日生成内容备份 (P13)

```python
"""每日生成内容备份到 obsidian-novel-backups 仓 yk-script/ 子路径

设计 (对标 obsidian-novel-publisher/src/github_backup.py):
- 复用 publisher 的 obsidian-novel-backups 私仓 (不新建仓库)
- 写入路径:
    truth/scripts/s01/ep05.md         ← 渲染后的 Markdown
    truth/scripts/s01/ep05.json       ← EpisodeScript JSON (含 critic score)
    truth/scripts/index.json          ← 季索引 (追加, 不覆盖)
    CHANGELOG.md                      ← 每日汇总 (追加)

凭据: GITHUB_BACKUP_TOKEN (Fine-grained PAT, Contents: Read+Write on obsidian-novel-backups)
"""
from __future__ import annotations
import base64
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .backup_reader import BackupReader
from .types import EpisodeScript

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_S = 30
DEFAULT_MAX_RETRIES = 3
_RETRY_BACKOFF_S = (1, 2, 4)


@dataclass(frozen=True)
class GithubBackupConfig:
    enabled: bool
    repo: str          # "blackclaw0318/obsidian-novel-backups"
    token: str
    branch: str = "main"

    @classmethod
    def from_env(cls) -> GithubBackupConfig:
        import os
        return cls(
            enabled=os.environ.get("GITHUB_BACKUP_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            repo=os.environ.get("GITHUB_BACKUP_REPO", "blackclaw0318/obsidian-novel-backups"),
            token=os.environ.get("GITHUB_BACKUP_TOKEN", ""),
        )


class GithubBackupError(Exception):
    pass


class GithubBackup:
    """每日生成内容 → 备份到 obsidian-novel-backups/yk-script/"""

    def __init__(self, cfg: GithubBackupConfig):
        self.cfg = cfg
        if "/" not in cfg.repo:
            raise ValueError(f"repo 必须是 'owner/name': {cfg.repo!r}")
        self.owner, self.name = cfg.repo.split("/", 1)
        # 复用 reader 拿 sha (GET /contents)
        self._reader = BackupReader(repo=cfg.repo, token=cfg.token, branch=cfg.branch)

    def backup_episode(
        self,
        *,
        season_no: int,
        episode_no: int,
        script: EpisodeScript,
        markdown: str,
        post_url: str,
        llm_usage: dict,
    ) -> dict:
        """备份单集内容 (md + json + index 追加 + changelog)

        Returns: {success: bool, paths: [...], error: str|None}
        """
        if not self.cfg.enabled:
            logger.info("GitHub backup disabled (GITHUB_BACKUP_ENABLED=false)")
            return {"success": False, "paths": [], "error": "disabled"}

        season_str = f"s{season_no:02d}"
        ep_str = f"ep{episode_no:02d}"
        base = f"yk-script/truth/scripts/{season_str}"

        paths_written = []

        # 1. Markdown
        md_path = f"{base}/{ep_str}.md"
        self._put_file(md_path, markdown, f"feat(yk-script): S{season_no:02d}-EP{episode_no:02d} {script.title} (markdown)")
        paths_written.append(md_path)

        # 2. JSON (EpisodeScript dump + critic + meta)
        json_path = f"{base}/{ep_str}.json"
        meta = {
            **script.model_dump(),
            "post_url": post_url,
            "llm_usage": llm_usage,
            "backup_at": datetime.now(timezone.utc).isoformat(),
        }
        self._put_file(
            json_path,
            json.dumps(meta, ensure_ascii=False, indent=2),
            f"feat(yk-script): S{season_no:02d}-EP{episode_no:02d} {script.title} (json meta)",
        )
        paths_written.append(json_path)

        # 3. Index (追加, 不覆盖)
        index_path = f"{base}/index.json"
        try:
            existing = self._reader.fetch_file(index_path)
            index = json.loads(existing["content"])
        except Exception:
            index = {"season_no": season_no, "episodes": []}

        # 防重复
        if not any(ep.get("episode_no") == episode_no for ep in index["episodes"]):
            index["episodes"].append({
                "episode_no": episode_no,
                "title": script.title,
                "logline": script.logline,
                "critic_score": script.critic_score.total if script.critic_score else None,
                "hook_type": script.hook_type,
                "post_url": post_url,
                "markdown_path": md_path,
                "json_path": json_path,
                "created_at": meta["backup_at"],
            })
            self._put_file(
                index_path,
                json.dumps(index, ensure_ascii=False, indent=2),
                f"chore(yk-script): S{season_no:02d} index 追加 EP{episode_no:02d}",
            )
            paths_written.append(index_path)

        # 4. CHANGELOG (追加)
        changelog_path = "yk-script/CHANGELOG.md"
        try:
            existing = self._reader.fetch_file(changelog_path)
            old_content = existing["content"]
        except Exception:
            old_content = "# yk-script 变更日志\n\n"

        new_line = (
            f"## {meta['backup_at'][:10]} · S{season_no:02d}-EP{episode_no:02d} {script.title}\n"
            f"- 评分: {script.critic_score.total if script.critic_score else '?'}/50\n"
            f"- 钩子: {script.hook_type or '—'}\n"
            f"- 博客: {post_url or '(未推送)'}\n\n"
        )
        self._put_file(
            changelog_path,
            old_content + new_line,
            f"docs(yk-script): CHANGELOG 追加 EP{episode_no:02d}",
        )
        paths_written.append(changelog_path)

        logger.info(f"✅ GitHub backup done: {paths_written}")
        return {"success": True, "paths": paths_written, "error": None}

    def _put_file(self, path: str, content: str, commit_message: str) -> None:
        """PUT /contents/{path} — 覆盖文件需先 GET 拿 sha

        Raises: GithubBackupError (重试耗尽 / 4xx)
        """
        url = f"{GITHUB_API_BASE}/repos/{self.owner}/{self.name}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {self.cfg.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        # 1. GET 拿 sha (覆盖必须)
        sha = None
        try:
            existing = self._reader.fetch_file(path)
            sha = existing["sha"]
        except Exception:
            sha = None  # 新文件

        payload = {
            "message": commit_message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": self.cfg.branch,
        }
        if sha:
            payload["sha"] = sha

        # 2. PUT (重试)
        last_err = None
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                resp = requests.put(
                    url, json=payload, headers=headers,
                    timeout=DEFAULT_TIMEOUT_S,
                )
                if 400 <= resp.status_code < 500:
                    raise GithubBackupError(
                        f"PUT {path} 4xx {resp.status_code}: {resp.text[:200]}"
                    )
                resp.raise_for_status()
                logger.info(f"PUT {path} OK ({resp.status_code})")
                return
            except requests.RequestException as e:
                last_err = e
                if attempt < DEFAULT_MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF_S[attempt]
                    logger.warning(
                        f"PUT {path} 失败 {attempt+1}/{DEFAULT_MAX_RETRIES}, "
                        f"{wait}s 后重试: {e}"
                    )
                    time.sleep(wait)
        raise GithubBackupError(
            f"PUT {path} 重试 {DEFAULT_MAX_RETRIES} 次耗尽: {last_err}"
        )
```

---

### 3.10 🆕 `src/wechat_notifier.py` — 每日成功/失败微信推送 (P14)

```python
"""微信通知 — 复用 obsidian-novel-publisher 完全相同模式

设计原则 (对标 publisher/src/wechat_notifier.py):
- 极简: 3-4 行 ≤40 字/行, 老板一眼能审
- 隔离: try/except 全包, 微信失败不影响 daily 主流程
- 幂等: pending.txt + openclaw cron run + 20s 后删
- 可关: WEIXIN_NOTIFY_ENABLED=false 完全跳过

推送路径:
  daily.py → wechat-pending.txt → openclaw cron run <jobId>
    → OpenClaw gateway → isolated agentTurn → announce delivery fallback
    → openclaw-weixin plugin → 老板微信 (老板私聊)
"""
from __future__ import annotations
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WechatNotifierConfig:
    enabled: bool
    cron_job_id: str  # OpenClaw cron job id (yk-script 专属, 待 P14 创建)
    pending_file: Path
    cron_run_timeout_s: float

    @classmethod
    def from_env(cls) -> WechatNotifierConfig:
        return cls(
            enabled=os.environ.get("WEIXIN_NOTIFY_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            cron_job_id=os.environ.get(
                "YK_WEIXIN_CRON_JOB_ID", ""  # 空 = 未配置, 跳过推送
            ),
            pending_file=Path(
                os.environ.get(
                    "YK_WEIXIN_PENDING_FILE",
                    str(Path(__file__).parent.parent / "logs" / "yk-wechat-pending.txt"),
                )
            ),
            cron_run_timeout_s=float(os.environ.get("WEIXIN_CRON_RUN_TIMEOUT_S", "15")),
        )


def _format_success(
    *, season_no: int, episode_no: int, title: str, score: int,
    hook_type: str, post_url: str,
) -> str:
    line1 = f"✅ 剧本生成成功 · S{season_no:02d}-EP{episode_no:02d}"
    line2 = title
    line3 = f"评分 {score}/50 · 钩子 {hook_type}"
    line4 = post_url if post_url else "(dry-run, 未推送)"
    return "\n".join([line1, line2, line3, line4])


def _format_failure(
    *, season_no: int, episode_no: int, title: str, error_short: str,
) -> str:
    line1 = f"❌ 剧本生成失败 · S{season_no:02d}-EP{episode_no:02d}"
    line2 = title or "(无标题)"
    line3 = f"原因: {error_short[:60]}"
    line4 = "查看: tail logs/yk-script.log"
    return "\n".join([line1, line2, line3, line4])


def notify_success(cfg: WechatNotifierConfig, **kwargs) -> bool:
    if not cfg.enabled or not cfg.cron_job_id:
        logger.debug("[notify] wechat disabled or job_id empty, skip")
        return False
    msg = _format_success(**kwargs)
    return _send(cfg, msg)


def notify_failure(cfg: WechatNotifierConfig, **kwargs) -> bool:
    if not cfg.enabled or not cfg.cron_job_id:
        logger.debug("[notify] wechat disabled or job_id empty, skip")
        return False
    msg = _format_failure(**kwargs)
    return _send(cfg, msg)


def _send(cfg: WechatNotifierConfig, msg: str) -> bool:
    """与 publisher 完全一致: 写文件 + cron run + sleep 20s + unlink"""
    try:
        cfg.pending_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.pending_file.write_text(msg, encoding="utf-8")
        logger.info(f"[notify] pending.txt 已写: {cfg.pending_file}")

        try:
            subprocess.run(
                ["openclaw", "cron", "run", cfg.cron_job_id],
                capture_output=True, text=True,
                timeout=cfg.cron_run_timeout_s, check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"[notify] cron run CLI 超时 {cfg.cron_run_timeout_s}s")

        time.sleep(20)  # 让 agent 读完文件 + 处理 + runner fallback 推送

        try:
            cfg.pending_file.unlink(missing_ok=True)
            logger.info("[notify] pending.txt 已删")
        except Exception as e:
            logger.warning(f"[notify] 删 pending.txt 失败 (无害): {e}")

        return True

    except Exception as e:
        logger.warning(f"[notify] 推送失败 (无害): {type(e).__name__}: {e}")
        return False
```

---

## 4. 测试矩阵 (P10 落地用)

| 测试文件 | 验证内容 | mock 策略 | 期望时长 |
|---|---|---|---|
| `test_screen_writer.py` | 3 候选生成 + prompt 模板渲染 + JSON 解析 + Pydantic 校验 | mock LLM 返回固定 JSON | 5s |
| `test_critic.py` | 5 维评分解析 + Island 循环 (低分触发重写) + 阈值通过/拒绝 | mock LLM 返回不同分数 | 8s |
| `test_memory_manager.py` | 硬约束检测 (6 条规则全验) + 状态机提取 + save/load | 真实 memory.json 路径 + tmpdir | 3s |
| `test_markdown_renderer.py` | EpisodeScript JSON → Markdown 渲染 (含 shot/action/dialog) | 静态 fixture | 1s |
| `test_state.py` | state.json 读写 + next_episode_idx 推进 + last_run_at 更新 | tmpdir | 1s |
| `test_llm_client.py` | minimax 调用 + stream 解析 + retry + stop_reason 校验 | requests-mock | 3s |
| `test_hmac_client.py` | HMAC-SHA256 签名 + POST + 错误处理 | requests-mock + 验签 | 2s |
| `test_daily_e2e.py` | **全链路 dry-run**: state 推进 + memory 提取 + Markdown 写到 output/ | mock LLM + tmpdir | 10s |
| `test_knowledge_loading.py` | 按 stage 加载 5 份 references + 关键词过滤 | 静态 | 1s |
| `test_state_persistence.py` | 跑 3 次 daily.py (EP01-03), state 应推进 0→3, memory 累积 | mock LLM + tmpdir | 15s |
| 🆕 `test_backup_reader.py` | GitHub API GET + base64 解码 + 4xx/5xx 重试 | `requests-mock` 模拟 200/404/500 | 3s |
| 🆕 `test_outline_fetcher.py` | sha 变更检测 + cache fallback + 本地 fallback | tmpdir + mock reader | 5s |
| 🆕 `test_github_backup.py` | PUT 文件 + sha 必传 + index.json 追加 + CHANGELOG 追加 | `requests-mock` 模拟 PUT | 5s |
| 🆕 `test_wechat_notifier.py` | pending.txt 写 + cron run + sleep + unlink + disabled 跳过 | mock subprocess + tmpdir | 3s |
| 🆕 `test_outline_change_flow.py` | 老板改 GitHub → sha 变 → cache 刷新 → daily 用新大纲 | 模拟 reader 返新 sha | 5s |
| 🆕 `test_backup_flow.py` | 生成 → backup → index.json 追加 → CHANGELOG 追加 | 全链路 mock | 8s |
| 🆕 `test_wechat_notify_flow.py` | 成功/失败 → pending.txt 内容正确 → cron run 调 | mock subprocess.run | 3s |

**总测试数目标**: ≥45 个, 全部 PASS, 覆盖 ≥85% 行

**关键测试用例**:
- `test_daily_e2e_dry_run`: 跑 EP01 全链路, 验 output/EP01.md 存在 + state.json next_idx=1
- `test_memory_timeline_regression`: 故意让新集 timeline 早于上一集 → 验 hard_check 拒绝
- `test_critic_island_loop_max_rounds`: mock 一直返 35 分 → 验 2 轮后兜底 + alert
- `test_writer_prompt_template_render`: 验 jinja2 渲染 + 所有变量替换

---

## 5. 实施顺序 + 测试门控 (gated commits)

| 步 | 内容 | commit | 测试门控 | 时 |
|---|---|---|---|---|
| **0** | README + LICENSE + .env.example + .gitignore + pyproject.toml | `feat(scaffold)` | 无 | 0.1d |
| **1** | requirements.txt + tests/ 骨架 + conftest.py + pytest 配置 | `feat(tests)` | `pytest --collect-only` OK | 0.2d |
| **2** | protagonist.json + apartment.json (3 文件) | `feat(characters)` | JSON schema 校验 | 0.3d |
| **3** | fork short-drama 8 references + UPSTREAM-README + LICENSE | `feat(knowledge)` | 文件数 = 10, 行数 = 2646 | 0.3d |
| **4** | prompts/writer.yaml + critic_rubric.yaml + hook_distribution.json + satisfaction_matrix.json + memory_constraints.yaml | `feat(prompts)` | YAML/JSON 解析 + jinja2 渲染测试 | 0.5d |
| **5** | src/types.py + src/llm_client.py + src/screen_writer.py | `feat(writer)` | `pytest tests/unit/test_screen_writer.py test_llm_client.py` ≥10 PASS | 0.6d |
| **6** | src/critic.py | `feat(critic)` | `pytest tests/unit/test_critic.py` ≥8 PASS | 0.7d |
| **7** | src/memory_manager.py | `feat(memory)` | `pytest tests/unit/test_memory_manager.py` ≥12 PASS (含 6 条硬约束) | 0.5d |
| **8** | src/state.py + src/markdown_renderer.py + src/hmac_client.py + src/logger.py + src/daily.py (不含 outline_fetcher/github_backup/wechat) | `feat(orchestrator)` | `pytest tests/unit/test_state.py test_markdown_renderer.py test_hmac_client.py` ≥15 PASS | 0.8d |
| **9** | systemd/yk-script.service + yk-script.timer + logrotate | `feat(systemd)` | `systemd-analyze verify` OK | 0.3d |
| **10** | 集成测试 (3 个 integration/) | `feat(integration)` | `pytest tests/integration/` ≥12 PASS | 0.5d |
| **11** | scripts/ (publish-today/skip-next/dry-run/regenerate/seed-state) | `feat(scripts)` | 每个脚本 --help 正常 | 0.2d |
| **🆕 12** | src/backup_reader.py + src/outline_fetcher.py + pull-outline.py | `feat(outline-fetcher)` | `pytest test_backup_reader.py test_outline_fetcher.py` ≥8 PASS + `test_outline_change_flow.py` PASS | 0.5d |
| **🆕 13** | src/github_backup.py + verify-backup.py | `feat(github-backup)` | `pytest test_github_backup.py test_backup_flow.py` ≥8 PASS | 0.4d |
| **🆕 14** | src/wechat_notifier.py + 微信 cron job 创建 + 更新 daily.py 集成 | `feat(wechat-notify)` | `pytest test_wechat_notifier.py test_wechat_notify_flow.py` ≥5 PASS | 0.3d |
| **15** | docs/RUNBOOK.md + CHANGELOG.md + dry-run 验证 EP01 | `docs+verify` | EP01 Markdown 渲染正确 + output/EP01.md 可读 | 0.2d |

**总工时**: **5.6d** (vs 5.2d, 加 P12-P14 3 步增加 0.4d — 但质量提升巨大)
**门控规则**: 上一步测试不过不许 git commit 下一步 (pre-commit hook)

---

## 6. 工程风险与缓解 (代码层面)

| # | 风险 | 触发条件 | 缓解 | 优先级 |
|---|---|---|---|---|
| **R1** | **JSON 解析失败** | LLM 返回 ```json ... ``` 包裹 / 多余文字 / 截断 | `_parse_strict()` 三步: 1) strip ``` 包裹 2) json.loads 3) Pydantic 校验, 失败 → reject candidate | 🟡 |
| **R2** | **stop_reason 不是 end_turn** | 模型被审查 / max_tokens 截断 | llm_client._stream_generate 抛 LLMError, Writer 跳过该候选 (但不抛错整体) | 🟡 |
| **R3** | **3 候选全失败** | 网络全挂 / API key 失效 | Writer 抛 RuntimeError → daily.main 捕 → 推微信告警 + return 1 | 🟢 |
| **R4** | **Memory 状态破坏** | 上一集 run 中途崩溃, memory.json 半写 | 写前用 `tempfile.NamedTemporaryFile` + `os.replace` 原子写, 崩溃恢复时读旧版 | 🟢 |
| **R5** | **Island 循环死循环** | Critic 反馈不够 actionable, 重写分数不变 | 限制 max_rounds=2, improvement_threshold=3, 不达标直接 alert 不无限循环 | 🟡 |
| **R6** | **Time drift** (06:00 跑了 25 分钟) | LLM 慢 + N=3 候选 + Island 循环 | daily.main 启动时设 deadline = start + 15min, 超时强制 return + alert | 🟡 |
| **R7** | **Token 成本爆炸** | 知识库全注入 (93KB) 每次调用 | 按 stage 只加载相关 5 份 (约 25KB), 单次调用 input ≤ 6K tokens | 🟢 |
| **R8** | **重复 episode** | state.next_episode_idx 没推进 | `state.update()` 强制 +1, 幂等: 同一 ep 重跑会跳过 | 🟢 |
| **R9** | **跨日 race** | 06:00 跑了一半, 老板 06:30 手动 --force-episode | state 加 lockfile (`data/state/.lock`), flock 互斥 | 🟡 |
| **R10** | **HMAC 签名错** | OBSIDIAN_PUBLISH_SECRET 不一致 / 时钟漂移 | hmac_client 加 5xx 重试 + 老板在 obsidian-journal 控制台校验 secret 一致 | 🟢 |
| **R11** | **Obsidian 接口 schema 变了** | 上游 obsidian-journal 升级 | hmac_client 抛 422 → daily.main 兜底 alert, 暂存 output/ 待人工推送 | 🟢 |
| **R12** | **Q1-Q3 之后又变** (角色形象再改) | 老板突然改主意 | 角色卡独立, 改 protagonist.json + youkei.json + 重跑 EP01 即可, state 不影响 | 🟢 |
| **🆕 R13** | **GitHub API 401/403** | GITHUB_BACKUP_TOKEN 过期 / scope 不够 | `_put_file` 4xx 不重试 → 记 log + 微信告警 (主推送已成功, 仅备份失败) | 🟡 |
| **🆕 R14** | **GitHub API 5xx 限流** | 5000 req/h 超限 (理论不会, 1 集 4 PUT) | 重试 3 次 指数退避 (1s/2s/4s), 仍失败 → log warning + 微信告警 | 🟡 |
| **🆕 R15** | **Outline sha 误检测** | GitHub 返回 sha 但与 cache 同, 多写一次 | `_write_cache` atomic, 内容相同也安全; 检测靠严格 `!=` 比较 | 🟢 |
| **🆕 R16** | **Outline 拉取失败但 cache 有旧版** | GitHub 临时挂 / 老板改 draft 中 | fallback cache → fallback 本地 → 启动失败 (3 级 fallback) | 🟢 |
| **🆕 R17** | **Outline 老板改坏了** (JSON 解析失败) | 老板编辑时漏写逗号 / 引号 | OutlineFetcher 抛 RuntimeError → daily.main 启动失败 → 推微信告警 (老板看日志修) | 🟡 |
| **🆕 R18** | **WeChat cron job 未创建** | P14 部署但 cron job 还没建 | `notify_*` 检查 `cron_job_id` 空字符串 → 静默跳过 + log warning | 🟢 |
| **🆕 R19** | **WeChat 推送 race** (publisher 已用同 cron job) | yk-script 和 publisher 撞同一个 cron job | **必须新创建独立 cron job** `notify-yk-script-wechat`, jobId 不同 (老板在 OpenClaw 控制台创建) | 🟡 |
| **🆕 R20** | **WeChat 推送后 pending.txt 被 schedule 兜底** | 20s sleep 不够 / agent 还没读 | publisher 已验证 sleep 20s 足够, 沿用 | 🟢 |
| **🆕 R21** | **Backup 失败阻塞主推送** | 网络挂了 GitHub API 都不可达 | github_backup 失败 → log warning + 微信告警 (标 "主推送已成功"), **不 throw** | 🟢 |
| **🆕 R22** | **老板改 outline 但 season-01.sha 不更新** (web UI 编辑后没 commit) | 老板手编后未点保存 | GitHub Contents API 读的是 main 分支最新 commit, 老板不 commit = 看不到, **流程上老板必须 commit** (RUNBOOK 写明) | 🟡 |

---

## 7. 关键工程决策 (实施前老板必读)

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| **D1** | Python 版本 | **3.12** | 与 obsidian-novel-publisher 一致, 可复用 llm_client |
| **D2** | LLM 模型 | **M2.7** | 写作优化 (60 TPS), 不选 M3 (Coding 优化) |
| **D3** | LLM 协议 | **Anthropic 兼容** + stream | 拿得到 stop_reason + 避免 180s thinking 卡死 |
| **D4** | JSON 校验 | **Pydantic v2** | 严格 + 自动生成 schema + IDE 友好 |
| **D5** | 模板引擎 | **jinja2** | 标准库, 上游 publisher 已用 |
| **D6** | 状态文件 | **JSON + 原子写** | 简单, 用 tempfile + os.replace 避免半写 |
| **D7** | 日志 | **logging + RotatingFileHandler** | 10MB × 5 = 50MB 上限, 不撑爆磁盘 |
| **D8** | 测试框架 | **pytest + pytest-mock + requests-mock** | 与 publisher 一致 |
| **D9** | 部署 | **systemd timer 06:00** | 与 publisher 一致, 本机直跑 |
| **D10** | 推送 | **HMAC POST → obsidian-journal /api/external/posts** | 复用现有 API |
| **🆕 D11** | 大纲数据源 | **`obsidian-yk-script` 仓 `data/seasons/*.json` (GitHub 拉)** | 老板可在 GitHub web UI 直接编辑, OutlineFetcher 每次跑前拉 + sha 检测 |
| **🆕 D12** | 备份仓 | **复用 `obsidian-novel-backups` 私仓 `yk-script/` 子路径** | 不新建仓库, 同 PAT, 路径隔离; 写入: md + json + index.json + CHANGELOG |
| **🆕 D13** | 微信推送 | **复用 publisher 同模式, 新建独立 cron job `notify-yk-script-wechat`** | 与 publisher jobId 区分, 防 race; 推送内容为 4 行 (S/E/P + 评分+钩子 + URL) |
| **🆕 D14** | 失败不阻塞 | **主推送成功 + 备份失败 → 推微信告警但标 "备份失败"** | 保证博客上线不被备份报错阻塞 |

---

## 8. 启动检查清单 (老板拍 P1-P4 后, 我开 P0)

```bash
# 0. 老板拍 P1-P4 (见 PLAN.md § 老板决策清单)
# 1. 老板准备 (一次性, 30min)
#    a) 确认 GITHUB_BACKUP_TOKEN 有 obsidian-yk-script (read) + obsidian-novel-backups (read+write) 权限
#       复用 publisher 的 PAT, 仅需补充 obsidian-yk-script read scope
#    b) 在 OpenClaw 控制台创建 cron job `notify-yk-script-wechat`:
#       - sessionTarget: isolated
#       - payload.kind: agentTurn
#       - payload.message: 读取 $YK_WEIXIN_PENDING_FILE 转推微信
#       - delivery.mode: announce → channel=openclaw-weixin → to=老板 o9cq805h...
#       - schedule: 手动触发 (publisher 同模式)
#    c) .env 填: GITHUB_BACKUP_TOKEN + MINIMAXI_API_KEY + OBSIDIAN_PUBLISH_SECRET + YK_WEIXIN_CRON_JOB_ID
#    d) 老板可在 https://github.com/blackclaw0318/obsidian-yk-script/edit/main/data/seasons/season-01.json 直接编辑大纲

# 2. 我创建分支
cd projects/obsidian-yk-script
git checkout -b feat/v0.2-implementation

# 3. 按 §5 表的 15 步顺序执行 (P0-P14)
# 4. 每步 commit + push 前跑 pytest, 全部通过才 push
# 5. 全部完成后 dry-run 跑 EP01:
python scripts/dry-run.py --force-episode 0
ls output/*.md  # 验 EP01 渲染

# 6. 验证 outline 拉取 + backup
python scripts/pull-outline.py  # 验 GitHub sha 检测 OK
python scripts/verify-backup.py  # 验 GitHub PUT OK

# 7. 部署
sudo cp systemd/yk-script.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yk-script.timer

# 8. 手动跑一次验证 (老板应该收到微信推送)
sudo systemctl start yk-script.service
journalctl -u yk-script.service -f

# 9. 验证推送 + 备份
curl https://www.shangkun.uk/posts?tag=YouKei   # 验博客
curl -H "Authorization: Bearer $GITHUB_BACKUP_TOKEN" \
  https://api.github.com/repos/blackclaw0318/obsidian-novel-backups/contents/yk-script/truth/scripts/s01  # 验备份仓

# 10. 验证微信
# 老板微信应收到:
#   ✅ 剧本生成成功 · S01-EP01 搬家日
#   评分 42/50 · 钩子 悬念钩
#   https://www.shangkun.uk/posts/yk-s01-ep01
```

**老板决策清单 (P1-P4, 见 PLAN.md § 老板决策清单) 拍板后, 我立即按此表开 P0 → 5.6d 上线 → 明天 06:00 自动产出第一集草稿 + 老板微信收到推送。**

---

*文档版本*: v0.3 (2026-07-11 21:43 GMT+8)
*作者*: 黑 (Hei)
*变更摘要*: v0.3 增量 (老板 21:43 三项新需求):
- 🆕 §3.7 backup_reader + §3.8 outline_fetcher — GitHub 拉取最新大纲 + sha 缓存
- 🆕 §3.9 github_backup — 每日生成内容备份到 obsidian-novel-backups/yk-script/
- 🆕 §3.10 wechat_notifier — 复用 publisher 同模式 + 新独立 cron job
- 📈 步骤 12→15 步, 工时 5.2d→5.6d, 测试 ≥75→≥93
- 📈 D11-D14 决策 + R13-R22 风险 (10 项新风险)
- 📈 scripts/ 加 pull-outline.py + verify-backup.py