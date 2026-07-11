# obsidian-yk-script — 详细架构 (v0.2)

> 本文档配合 `PLAN.md` 一起看。PLAN.md 是 why/who/what,本文档是 how。

---

## 1. 数据流 (一图流)

```
┌─────────────────────────────────────────────────────────────────────┐
│  外部触发                                                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ systemd timer: yk-script.timer                                │   │
│  │   - OnCalendar=*-*-* 06:00:00                                 │   │
│  │   - Persistent=true                                           │   │
│  │   - Unit=yk-script.service                                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────────┘
                         │ 触发
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  src/daily.py — 主入口 (orchestrator)                                │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  def main():                                                  │   │
│  │      # ① 加载所有数据                                          │   │
│  │      state = load_state()                                     │   │
│  │      memory = load_memory()                                   │   │
│  │      season = load_season(state['season_no'])                 │   │
│  │      characters = load_characters()                           │   │
│  │      knowledge = load_references_for_episode(                 │   │
│  │          stage=season['stage']                                │   │
│  │      )                                                        │   │
│  │                                                              │   │
│  │      # ② 构建 Writer prompt                                    │   │
│  │      prompt = build_writer_prompt(                            │   │
│  │          characters, season, state, memory, knowledge         │   │
│  │      )                                                        │   │
│  │                                                              │   │
│  │      # ③ Agent 1: 生成 N=3 候选                                │   │
│  │      candidates = screen_writer.generate_n(                   │   │
│  │          prompt, n=3, temperature=0.9                         │   │
│  │      )  # 借鉴 COMIC Island                                    │   │
│  │                                                              │   │
│  │      # ④ Agent 2: 5 维评分 + Island 反馈循环                    │   │
│  │      best_script, score = critic.evaluate(                    │   │
│  │          candidates, max_rounds=2, min_score=38               │   │
│  │      )                                                        │   │
│  │                                                              │   │
│  │      # ⑤ Agent 3: 硬约束检测                                    │   │
│  │      validated, errors = memory_manager.hard_check(           │   │
│  │          best_script, memory                                  │   │
│  │      )                                                        │   │
│  │                                                              │   │
│  │      # ⑥ 失败兜底: 重写 1 次                                    │   │
│  │      if not validated and state['retry_count'] < 1:           │   │
│  │          state['retry_count'] += 1                            │   │
│  │          return main()  # 重来一次                             │   │
│  │                                                              │   │
│  │      # ⑦ 渲染 Markdown                                         │   │
│  │      md = markdown_renderer.render(validated)                 │   │
│  │                                                              │   │
│  │      # ⑧ 推送 obsidian-journal (HMAC)                         │   │
│  │      hmac_client.post(                                        │   │
│  │          slug=f"yk-s{season_no:02d}-ep{ep:02d}",              │   │
│  │          title=validated['title'],                            │   │
│  │          content=md,                                           │   │
│  │          category='life',                                     │   │
│  │          tags=','.join(validated['tags']),                    │   │
│  │          external_id=f"yk-s{season_no:02d}-ep{ep:02d}",       │   │
│  │          external_meta=validated['external_meta']             │   │
│  │      )                                                        │   │
│  │                                                              │   │
│  │      # ⑨ 更新 state 和 memory                                  │   │
│  │      state['episode_idx'] += 1                                │   │
│  │      state['last_run_at'] = now()                             │   │
│  │      state['last_summary'] = validated['summary']              │   │
│  │      save_state(state)                                        │   │
│  │      save_memory(memory_manager.extract_state(validated))     │   │
│  │                                                              │   │
│  │      # ⑩ 告警 (失败时)                                          │   │
│  │      if any_error:                                             │   │
│  │          wecom_alert.send(...)                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────────┘
                         │ 推送
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  obsidian-journal                                                    │
│  POST /api/external/posts (HMAC 鉴权)                                │
│  → posts 表新增一行                                                   │
│  → 公开页 /posts?tag=YouKei 自动可见                                  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent 设计详解

### 2.1 Agent 1 · Screenwriter (`src/screen_writer.py`)

**职责**: 把角色卡 + 季弧 + 上一集摘要 + memory + knowledge 转化为 N 个候选 EpisodeScript。

**输入**:
```python
@dataclass
class WriterInput:
    characters: dict          # youkei + protagonist + apartment
    season: dict              # season-NN.json 12 集弧
    episode_idx: int          # 1-12
    prev_summary: str         # 上一集 ending_summary
    prev_episode: dict        # 上一集完整数据 (用于 memory_updates)
    memory: dict              # 当前 memory 状态
    knowledge_chunks: list[str]  # 注入的 references 摘要
    hook_type_required: str   # 本集要求的钩子类型
    satisfaction_required: list[str]  # 本集要求的爽点类型
```

**输出**:
```python
@dataclass
class EpisodeScript:
    season: int
    episode: int
    title: str
    duration_estimate_s: int
    logline: str
    stage: str                # 起势 / 攀升 / 风暴 / 决战
    hook_type: str            # 5 类钩子之一
    hook_subtype: str         # 子模式 (结果/身份/局势...)
    satisfaction_types: list[str]  # 5 类爽点
    satisfaction_intensity: str    # ★ 等级
    scene: dict               # 场景元信息
    script: list[dict]        # 3-8 个 shot
    key_moments: list[str]
    post_production_notes: list[str]
    memory_updates: dict      # 本集对 memory 的更新
    next_episode_seed: str
    continuity_check: dict
```

**Prompt 注入策略** (借鉴 short-drama SKILL.md 的"按 stage 加载"):
- EP1: 重点加载 `opening-rules.md` (前 30s 黄金法则)
- EP2-12: 加载 `rhythm-curve.md` + `hook-design.md` + `satisfaction-matrix.md`
- 全部 EP: 加载 `genre-guide.md` (萌宠日常题材)

**借鉴 COMIC Island 思想**:
- 同 prompt 跑 N=3 次, temperature=0.9 (适度随机)
- 不同 seed → 不同思路 (e.g., seed=1 偏搞笑, seed=2 偏温馨, seed=3 偏冲突)

**Token 估算**: ~3500 input (含 5 份 references 摘要) + ~2000 output × 3 = 9500 total

---

### 2.2 Agent 2 · Critic (`src/critic.py`)

**职责**: 对 N 个候选打分,选出最佳,反馈循环 2 轮。

**5 维度评分** (借鉴 short-drama 评分体系,改为 1-10 分制):

| 维度 | 权重 | 评价标准 |
|---|---|---|
| **节奏** (rhythm) | 10 分 | 开场是否够快 / 中段是否递进 / 末钩是否到位 |
| **爽点** (satisfaction) | 10 分 | 萌点密度 / 情绪高潮 / 类型多样 |
| **台词** (dialog) | 10 分 | 角色区分度 / 口语化 / 画外音使用 |
| **格式** (format) | 10 分 | 场景头 / 景别标注 / 配乐提示 / 标记 |
| **连贯性** (continuity) | 10 分 | 与角色档案一致 / 与前后集衔接 / 伏笔回收 |

**总分**: 50 分
**评级**:
- 45-50: 卓越 (直接推送)
- 38-44: 优良 (微调后可用, 默认阈值 ≥38)
- 30-37: 合格 (需修改)
- 25-29: 需改进
- <25: 需重写

**Island 反馈循环** (借鉴 COMIC):

```
对 N=3 候选各评 5 维 → 总分
   ↓
选出最高分候选 W, 最低分候选 L
   ↓
提取 L 的具体问题 (e.g., "L 节奏 4/10, 因为开场太慢")
   ↓
将 L 的反馈注入 prompt, 重写 L
   ↓
新 L' vs W → 选最高分
   ↓
最多 2 轮 (否则报警)
```

**Token 估算**: 3 × 500 (评) + 1 × 1000 (反馈) = 2500 total

---

### 2.3 Agent 3 · Memory Manager (`src/memory_manager.py`)

**职责**: 维护剧情连续性,硬约束检测。

**数据结构** (`data/state/memory.json`):
```json
{
  "season_no": 1,
  "episode_idx": 5,
  "character_states": {
    "youkei": {
      "current_location": "客厅",
      "current_mood": "relaxed",
      "wearable_items": [],
      "wet": false,
      "fed_last_time": "2026-MM-DD 18:00"
    },
    "shangkun": {
      "current_location": "客厅",
      "current_mood": "happy",
      "wearing": "家居服"
    }
  },
  "prop_states": {
    "fish_in_fridge": true,
    "bath_towel_clean": true,
    "cat_bag_location": "玄关",
    "camera_charged": true
  },
  "timeline": {
    "last_event_time": "2026-MM-DD 19:00",
    "last_event_location": "客厅",
    "absolute_day": 5
  },
  "hook_chain": [
    {"ep": 1, "hook_text": "窗外有鸟飞过", "must_resolve_in_ep": 3},
    {"ep": 4, "hook_text": "鱼不见了", "must_resolve_in_ep": 4}
  ],
  "fired_hooks": [
    {"ep": 1, "hook_text": "窗外有鸟飞过", "resolved_in_ep": 3}
  ],
  "unresolved_hooks": [],
  "continuity_errors_caught": 12,
  "rewrites_triggered": 1
}
```

**硬约束检测规则** (`prompts/memory_constraints.yaml`):

| 规则 | 说明 | 失败处理 |
|---|---|---|
| **时间线单方向** | 绝对时间只前进, 不允许倒退 | 触发 Writer 重写 |
| **道具一致性** | 已用完/已收起的道具不能再次出现 (除非有补充动作) | 触发 Writer 重写 |
| **角色位置合理性** | 角色不能瞬移 (除非有移动说明) | 触发 Writer 重写 |
| **上集钩子回收** | 上集钩子文本必须在本集出现并回收 | 触发 Writer 重写 |
| **角色能力不变** | 7 月龄猫不能做超能力动作 (开门可/开微波炉不可) | 触发 Writer 重写 |
| **情绪连续性** | 上集大哭, 这集不能立即若无其事 | 警告 (不阻断, 给 Critic 扣分) |

**Token 估算**: ~200 input + ~200 output = 400 total

---

## 3. 状态机 (`src/state.py`)

**state.json** 结构:
```json
{
  "current_step": "idle|running|failed",
  "season_no": 1,
  "episode_idx": 1,
  "last_run_at": "2026-MM-DD HH:MM:SS",
  "last_summary": "...",
  "last_error": null,
  "retry_count": 0,
  "total_runs": 0,
  "total_success": 0,
  "total_failure": 0
}
```

**状态转移**:
```
idle → running (cron 触发) → success → idle (更新 state)
                              ↓
                              failure → retry (1 次)
                                       ↓
                                       failed (告警)
```

---

## 4. 数据持久化策略

| 数据 | 路径 | 持久化时机 | gitignore |
|---|---|---|---|
| 角色卡 | `data/characters/*.json` | 仓库初始化 | ❌ 提交 |
| 季弧 | `data/seasons/season-NN.json` | 仓库初始化 | ❌ 提交 |
| 知识库 | `data/knowledge/references/*.md` | 仓库初始化 (fork) | ❌ 提交 |
| Prompt 模板 | `prompts/*.yaml/json` | 仓库初始化 | ❌ 提交 |
| 运行时状态 | `data/state/state.json` | 每次运行后 | ✅ gitignored |
| Memory 状态机 | `data/state/memory.json` | 每次运行后 | ✅ gitignored |
| 推送历史 | `logs/publish.log` | 每次运行后 | ✅ gitignored |
| 日志 | `logs/yk-script.log` | 持续 | ✅ gitignored |

---

## 5. 错误处理与告警

| 错误类型 | 处理 | 告警 |
|---|---|---|
| LLM API 401/403 | 立即终止, 提示老板换 key | ✅ 微信告警 |
| LLM API 429 限流 | 退避重试 3 次 (指数退避) | ⚠️ 警告 (重试成功不告警) |
| LLM 输出 JSON 解析失败 | 重试 Writer 1 次 | ⚠️ 警告 |
| Critic 总分 < 38 且 2 轮迭代后仍 < 38 | 推送但标记 `quality_warning=true` | ✅ 微信告警 |
| Memory 硬约束失败且重写后仍失败 | 推送但标记 `continuity_error=true` | ✅ 微信告警 |
| obsidian-journal HMAC 推送失败 | 重试 3 次 (指数退避) | ✅ 微信告警 (重试全部失败时) |

---

## 6. systemd 集成

**yk-script.service**:
```ini
[Unit]
Description=YouKei Daily Script Generator
After=network-online.target

[Service]
Type=oneshot
User=ykscript
WorkingDirectory=/opt/yk-script
Environment="PATH=/opt/yk-script/.venv/bin"
ExecStart=/opt/yk-script/.venv/bin/python -m src.daily
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**yk-script.timer**:
```ini
[Unit]
Description=YouKei Daily Script Generator Timer
Requires=yk-script.service

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true
Timezone=Asia/Shanghai

[Install]
WantedBy=timers.target
```

**启用**:
```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo cp systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yk-script.timer
```

---

*文档版本*: v0.2 (2026-07-11)
*配套*: PLAN.md, KNOWLEDGE_BASE.md, RUNBOOK.md