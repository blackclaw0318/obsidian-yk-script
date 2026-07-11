# obsidian-yk-script — 方案稿 v0.3 (2026-07-11 21:43)

> **项目代号**: obsidian-yk-script
> **目标**: 每天 06:00 自动生成"老板 + 缅因猫 YouKei"单元剧短视频脚本 (30s-1:30), POST 到 obsidian-journal 生活分类
> **状态**: ⏸️ 等老板 P1-P8 拍板开 P0
> **基于**: v0.1 + 2026-07-11 调研 (short-drama + ShakeDrama + COMIC) + **v0.3 老板三增项** (GitHub 备份 + GitHub 拉大纲 + 微信推送)
> **版本**: v0.2 → **v0.3** (增量在老板 21:43 拍)
>
> **配套文档**:
> - 📋 [PLAN.md](PLAN.md) — **本文档**: why/what/季弧/角色/决策
> - 🛠 [IMPLEMENTATION.md](IMPLEMENTATION.md) — **how**: prompt 模板 + Agent 代码 + 测试矩阵 + **15 步 gated commits** + 22 项风险 + 14 项决策

---

## 🎯 一句话定位

**每天早上自动写好一集《上坤 × YouKei》单元剧剧本,老板下班回家照着拍。**

12 集一季,前后连贯,可独立观看;主场景上海 60 平小两居,少量外出。

---

## 🆕 v0.1 → v0.2 核心变更 (基于 2026-07-11 调研)

| 维度 | v0.1 (旧) | **v0.2 (新)** | 来源 |
|---|---|---|---|
| 编剧知识库 | ❌ 无 | ✅ **直接 fork short-drama 8 份 references/(MIT)** | [0xsline/short-drama](https://github.com/0xsline/short-drama) (802⭐) |
| 多 Agent 拆分 | ❌ 单脚本 | ✅ **Screenwriter / Critic / Memory Manager 三 Agent** | [XiangTodayEatsWhat/ShakeDrama](https://github.com/XiangTodayEatsWhat/ShakeDrama) + COMIC |
| 编剧评审 | ❌ 无 | ✅ **5 维评分 (节奏/爽点/台词/格式/连贯性) + Island 反馈循环** | short-drama quality + COMIC Island |
| 连续性保障 | ❌ 无 | ✅ **Memory Manager 硬约束 (时间线/道具/上集钩子)** | ShakeDrama memory_manager.py |
| 节奏设计 | ⚠️ 经验估算 | ✅ **节奏四段 (起势 15% / 攀升 30% / 风暴 35% / 决战 20%)** | short-drama rhythm-curve.md |
| 钩子设计 | ⚠️ 单调 | ✅ **5 类钩子分布 (悬念/反转/情绪/信息/危机)** | short-drama hook-design.md |
| 爽点设计 | ❌ 无 | ✅ **5 类爽点配比 (情感爆发/悬念揭秘为主,适配萌宠)** | short-drama satisfaction-matrix.md |
| 单集微结构 | ⚠️ 简单三段 | ✅ **前 30s 钩子段 + 中段冲突升级 + 后 30s 钩子释放** | short-drama rhythm-curve.md |

### 调研参考清单

| 来源 | 协议 | 借鉴点 | 借鉴方式 |
|---|---|---|---|
| **[0xsline/short-drama](https://github.com/0xsline/short-drama)** (802⭐) | MIT | 8 份 references (知识库) + 5 维评分 + 节奏四段 + 钩子 5 类 | ✅ **直接 fork** |
| **[XiangTodayEatsWhat/ShakeDrama](https://github.com/XiangTodayEatsWhat/ShakeDrama)** (2⭐) | Apache 2.0 | Multi-agent 拆分 (screenwriter/editor/memory/showrunner) + 分阶段 workflow | ⚠️ **借鉴思想**,不 fork 代码 |
| **COMIC 论文** (华盛顿大学, [arXiv:2603.11048](https://arxiv.org/abs/2603.11048v1)) | 学术 | Island-based 写作循环 + YouTube-Aligned Critics | ⚠️ **借鉴思想**,无开源代码 |
| **2025 Top100 短剧数据公式** | 行业数据 | 3 秒定生死 + 42 秒密度 + 15/50/85% 情绪波峰 | ✅ **注入 prompt** |
| **Save the Cat 15 beats** | 经典框架 | 编剧圣经,60 年验证 | ✅ **压缩 5 beats 注入 prompt** |

---

## 🏗️ 架构图 (v0.2 三 Agent + 知识库驱动)

```
┌─────────────────────────────────────────────────────────────────────┐
│  本机 systemd timer: 06:00 daily                                    │
└────────────────────────┬────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  src/daily.py — 主入口                                               │
│                                                                      │
│  1. state = load_state("data/state/state.json")                     │
│  2. memory = load("data/state/memory.json")                         │
│  3. season = load("data/seasons/season-{N}.json")                   │
│  4. characters = load("data/characters/*.json")                     │
│  5. knowledge = [load_references(f"data/knowledge/references/{f}")  │
│       for f in ["opening-rules", "rhythm-curve", "hook-design",     │
│                  "satisfaction-matrix", "genre-guide"]]             │
│  6. prompt = build_writer_prompt(                                   │
│       season_no, episode_idx, prev_summary, characters,             │
│       knowledge, memory.constraints, hook_distribution,             │
│       satisfaction_matrix                                           │
│     )                                                               │
│  7. candidates = screen_writer.generate_n_candidates(              │
│       prompt, n=3  # COMIC Island 思想                              │
│     )                                                               │
│  8. best_script = critic.evaluate_and_select(                      │
│       candidates,  # 5 维度评分,反馈循环                              │
│       min_score=38, max_rounds=2                                    │
│     )                                                               │
│  9. validated = memory_manager.hard_check(best_script, memory)      │
│  10. if not validated: retry writer 1 次                              │
│  11. md = markdown_renderer.render(validated)                        │
│  12. push_to_obsidian(md, meta)  # HMAC POST                         │
│  13. update_state(next_idx, summary, validated.next_episode_seed)   │
│  14. update_memory(memory_manager.extract_state(validated))         │
│  15. alert_on_failure()                                              │
└────────────────────────┬────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  obsidian-journal posts 表                                           │
│   category='life', tags='YouKei,季1-EP05,生活vlog'                  │
│   公开页 /posts?tag=YouKei 列表自动展示                              │
└────────────────────────┬────────────────────────────────────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
┌────────────────────┐ ┌──────────────────────┐ ┌────────────────────┐
│ 🆕 v0.3 GitHub备份  │ │ 🆕 v0.3 微信推送      │ │ state + memory 更新 │
│ obsidian-novel-     │ │ pending.txt +         │ │ (原子写)            │
│ backups/yk-script/  │ │ cron run → 微信       │ │                    │
│ truth/scripts/      │ │                       │ │                    │
│ s01/ep05.md         │ │ 4 行:                  │ │                    │
│ s01/ep05.json       │ │ ✅ 标题                │ │                    │
│ s01/index.json      │ │ 评分+钩子              │ │                    │
│ CHANGELOG.md        │ │ URL                   │ │                    │
└────────────────────┘ └──────────────────────┘ └────────────────────┘

📥 输入源: 大纲从 GitHub 拉 (boss 可在 web UI 编辑)

┌─────────────────────────────────────────────────────────────────────┐
│  GitHub Contents API (startup 拉取)                                 │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ blackclaw0318/obsidian-yk-script 仓 (public)                │   │
│  │   ├─ data/seasons/season-01.json   ← 老板手编主入口          │   │
│  │   ├─ data/characters/youkei.json   ← 角色卡(可选改)         │   │
│  │   ├─ data/characters/protagonist.json                        │   │
│  │   └─ data/characters/apartment.json                          │   │
│  │                                                              │   │
│  │  拉取流程: GET /contents/...  → 拿 (content, sha)             │   │
│  │         → 比对 data/cache/season-01.sha 旧 sha               │   │
│  │         → 变了 → log "老板改了新大纲" + 原子写 cache           │   │
│  │         → 没变 → 用 cache 加速                                │   │
│  │         → 拉取失败 → 3 级 fallback (cache → 本地 → 启动失败) │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  Agent 设计 (借鉴 ShakeDrama multi-agent + COMIC Island)             │
│                                                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Agent 1 · Screenwriter (写)                                   │  │
│  │   输入: 角色卡 + 季弧 + 上一集摘要 + memory + knowledge       │  │
│  │   工具: minimax M3 (MiniMax-M3)                              │  │
│  │   输出: N=3 个候选 EpisodeScript JSON                         │  │
│  │   Prompt 注入:                                                 │  │
│  │     - opening-rules.md (前 30s 黄金法则 + 6 种开场模板)       │  │
│  │     - rhythm-curve.md (节奏四段 + 单集微结构)                 │  │
│  │     - hook-design.md (5 类钩子 + 阶段分布)                    │  │
│  │     - satisfaction-matrix.md (5 类爽点 + 萌宠适配)            │  │
│  │     - genre-guide.md (萌宠日常题材参考)                        │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Agent 2 · Critic (审) — 借鉴 short-drama 5 维 + COMIC Island  │  │
│  │   维度 (各 10 分,共 50 分):                                    │  │
│  │     ① 节奏 — 开场是否够快 / 中段是否递进 / 末钩是否到位       │  │
│  │     ② 爽点 — 萌点密度 / 情绪高潮 / 类型多样                   │  │
│  │     ③ 台词 — 角色区分度 / 口语化 / 画外音使用                  │  │
│  │     ④ 格式 — 场景头 / 景别标注 / 配乐提示 / 标记                │  │
│  │     ⑤ 连贯性 — 与角色档案一致 / 与前后集衔接 / 伏笔回收       │  │
│  │   流程:                                                        │  │
│  │     对 N=3 候选分别打分 → 输家用赢家反馈重写 → 2 轮            │  │
│  │   阈值: 总分 ≥ 38/50 才通过                                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ↓                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │ Agent 3 · Memory Manager (管) — 借鉴 ShakeDrama memory_manager│  │
│  │   持久化状态: data/state/memory.json                          │  │
│  │     - character_states (角色当前位置/姿势/情绪/持有道具)        │  │
│  │     - prop_states (道具位置: 鱼/零食/球/家具)                  │  │
│  │     - timeline (绝对时间线, 不允许倒退)                         │  │
│  │     - hook_chain (上集钩子 → 本集必须回收)                     │  │
│  │   硬约束检测:                                                   │  │
│  │     - 时间线冲突 (上集晚 8 点, 这集不能是下午 3 点)            │  │
│  │     - 道具穿帮 (鱼已吃完, 不能再次吃)                         │  │
│  │     - 上集钩子回收 (上集说"窗外有鸟", 本集必须出现鸟)          │  │
│  │   失败 → 触发 Agent 1 重写 (1 次机会)                          │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📁 仓库结构 (v0.2 完整版)

```
obsidian-yk-script/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── PLAN.md                  # 本文档 (v0.2)
│   ├── ARCHITECTURE.md          # 详细架构 + 数据流
│   ├── KNOWLEDGE_BASE.md        # 8 份 references 摘要与用法
│   ├── CHARACTERS.md            # 角色卡摘要 (YouKei + 上坤)
│   ├── RUNBOOK.md               # 运维 (部署/暂停/恢复)
│   └── CHANGELOG.md             # 变更日志
├── data/
│   ├── characters/              # ✅ v0.2 落地 (Q1-Q3 信息已应用)
│   │   ├── youkei.json          # YouKei 角色卡 (红虎斑+浅绿+日语 YouKei)
│   │   ├── protagonist.json     # 上坤 角色卡 (化名, 只出手+配音)
│   │   └── apartment.json       # 公寓 6 室 + 5 外出备选
│   ├── seasons/
│   │   └── season-01.json       # ✅ v0.2 落地 (节奏四段 + 钩子 5 分布)
│   ├── knowledge/               # 🆕 v0.2 新增 (fork from short-drama)
│   │   └── references/          # MIT 协议直接 fork
│   │       ├── opening-rules.md
│   │       ├── rhythm-curve.md
│   │       ├── hook-design.md
│   │       ├── satisfaction-matrix.md
│   │       ├── villain-design.md
│   │       ├── genre-guide.md
│   │       ├── paywall-design.md
│   │       └── compliance-checklist.md
│   ├── state/                   # 运行时状态 (gitignored)
│   │   ├── state.json           # 进度 (season/episode/last_run)
│   │   └── memory.json          # 角色状态机 + 道具状态 + 时间线
│   ├── cache/                   # 🆕 v0.3 GitHub 拉取缓存 (gitignored)
│   │   ├── season-01.json       # ← 从 GitHub 拉的大纲
│   │   ├── season-01.sha        # ← sha 检测变更
│   │   ├── youkei.json          # ← 从 GitHub 拉的角色卡
│   │   └── protagonist.json     # ← 从 GitHub 拉的主角卡
├── prompts/                     # 🆕 v0.2 新增 (注入 LLM 的 prompt 模板)
│   ├── writer.yaml              # Screenwriter prompt 模板
│   ├── critic_rubric.yaml       # Critic 5 维评分标准
│   ├── hook_distribution.json   # 钩子 5 类阶段分布
│   ├── satisfaction_matrix.json # 爽点 5 类配比 (萌宠适配)
│   └── memory_constraints.yaml  # Memory Manager 硬约束规则
├── src/
│   ├── daily.py                 # 主入口 (集成 outline_fetcher + github_backup + wechat)
│   ├── screen_writer.py         # 🆕 Agent 1: 写
│   ├── critic.py                # 🆕 Agent 2: 审
│   ├── memory_manager.py        # 🆕 Agent 3: 管
│   ├── markdown_renderer.py     # JSON → MD
│   ├── hmac_client.py           # 复用 obsidian-journal
│   ├── state.py                 # 状态机
│   ├── backup_reader.py         # 🆕 v0.3 GitHub Contents API 只读 (拉 outline/characters)
│   ├── outline_fetcher.py       # 🆕 v0.3 sha 检测 + 缓存 + fallback 本地
│   ├── github_backup.py         # 🆕 v0.3 每日生成内容备份到 obsidian-novel-backups/yk-script/
│   └── wechat_notifier.py       # 🆕 v0.3 复用 publisher 模式: pending.txt + cron run + 20s
├── scripts/
│   ├── publish-today.py         # 手动触发 (复用 daily.py)
│   ├── skip-next.py             # 老板说"今天跳过"
│   ├── dry-run.py               # 不推送, 仅生成 + 本地预览
│   ├── regenerate.py            # 重写指定集 (状态不变)
│   ├── pull-outline.py          # 🆕 v0.3 手动强制拉 outline (调试用)
│   └── verify-backup.py         # 🆕 v0.3 验证今日 backup 已上传
├── systemd/
│   ├── yk-script.service
│   └── yk-script.timer          # 06:00 daily
├── logs/                        # gitignored
└── tests/
    ├── unit/
    │   ├── test_screen_writer.py
    │   ├── test_critic.py
    │   ├── test_memory_manager.py
    │   ├── test_markdown_renderer.py
    │   └── test_state.py
    └── integration/
        ├── test_daily_e2e.py
        └── test_knowledge_loading.py
```

---

## 📚 知识库驱动 (v0.2 核心创新)

### Fork 自 short-drama 的 8 份 references (MIT 协议)

| # | 文档 | 大小 | 用途 | 加载时机 |
|---|---|---|---|---|
| 1 | `opening-rules.md` | 6.7KB | 6 种开场模板 + 前 30s 黄金法则 | Writer (EP1 重点) |
| 2 | `rhythm-curve.md` | 9.3KB | 节奏四段 + 单集微结构 + 加速/减速手段 | Writer + Critic |
| 3 | `hook-design.md` | 11.1KB | 5 类钩子 (悬念/反转/情绪/信息/危机) + 阶段分布 | Writer + Critic |
| 4 | `satisfaction-matrix.md` | 12.2KB | 5 大爽点 (身份碾压/打脸/逆袭/情感/悬念) + 配比策略 | Writer |
| 5 | `villain-design.md` | 12.1KB | 4 层反派递进体系 | Writer (简化适配) |
| 6 | `genre-guide.md` | 9.6KB | 13 种题材 + 出海题材映射 | Writer (萌宠日常适配) |
| 7 | `paywall-design.md` | 7KB | 付费卡点设计 (我们免费, 仅借鉴"卡点集 = 最强钩子") | Writer (可选) |
| 8 | `compliance-checklist.md` | 10.7KB | 红线 + 高风险 + 正能量校验 | Critic (合规审查) |

**总计**: 9 文件 / 2646 行 / 93KB (源自 short-drama README)

### 萌宠题材适配 (我们的特化)

short-drama 默认面向"霸道总裁/战神归来/甜宠"等强戏剧题材。我们要做"萌宠日常",所以:

| short-drama 维度 | 我们怎么用 |
|---|---|
| 4 层反派体系 | 简化: **猫的本能** = 第一层 (小反派), **现实问题** (没食物/打雷/生病) = 第二层 |
| 5 类爽点 | 改配比: **情感爆发 (萌点) 60%** + 悬念揭秘 25% + 打脸 (猫的本能胜利) 10% + 逆袭 5% |
| 6 种开场模板 | 用"**身份反转型**"(YouKei 看似普通实则是家里老大) + "**高甜钩子型**"(蹭脸瞬间) |
| 节奏四段 | 直接套用,但**篇幅更短 (起势 2 集 / 攀升 4 集 / 风暴 4 集 / 决战 2 集)** |

详见 `docs/KNOWLEDGE_BASE.md`。

---

## 🎬 单集脚本结构 (v0.2 LLM 输出格式)

```json
{
  "season": 1,
  "episode": 5,
  "title": "🛁 洗澡大作战",
  "duration_estimate": "75s",
  "logline": "YouKei 的第一次洗澡, 从惊慌失措到全身湿漉漉",
  "stage": "攀升段",
  "stage_position_pct": 35,
  "rhythm_curve": "中段高潮, 中强钩子",
  "hook_type": "悬念钩",
  "hook_subtype": "结果悬念",
  "satisfaction_types": ["情感爆发", "悬念揭秘"],
  "satisfaction_intensity": "★★★",
  "scene": {
    "location": "卫生间",
    "lighting": "顶灯 + 暖色",
    "props": ["浴缸 / 宠物专用洗发水 / 毛巾 / 吹风机"],
    "weather": "—",
    "time_of_day": "20:00 (晚间)"
  },
  "script": [
    {
      "shot": 1,
      "duration_s": 5,
      "shot_type": "特写",
      "shot_position": "前 30s 钩子段",
      "subject": "浴缸 + 温水 + 宠物洗发水",
      "action": "主人试水温, YouKei 在门口探头发呆",
      "dialog": "主人画外音: 'YouKei, 来洗澡了'",
      "sfx": "水声",
      "mood": "平静铺垫 → 紧张暗示",
      "emotion_intensity": 2
    },
    {
      "shot": 2,
      "duration_s": 8,
      "shot_type": "中景",
      "shot_position": "中段冲突升级",
      "subject": "YouKei 全程",
      "action": "把 YouKei 放进浴缸, 它瞬间弹起 4 只爪子抓盆边",
      "dialog": "主人画外音: '别... 别抓...'",
      "sfx": "哗啦水声 + YouKei 喵叫",
      "mood": "紧张冲突",
      "emotion_intensity": 4
    },
    {
      "shot": 3,
      "duration_s": 7,
      "shot_type": "特写",
      "shot_position": "中段高潮",
      "subject": "YouKei 全身泡沫脸",
      "action": "主人给 YouKei 抹洗发水, 全身泡沫",
      "dialog": "主人画外音: '别动, 这是精华...'",
      "sfx": "喵叫 (抗拒)",
      "mood": "搞笑萌点",
      "emotion_intensity": 5,
      "is_climax": true,
      "climax_label": "15% / 50% / 85% 中的 50%"
    },
    {
      "shot": 4,
      "duration_s": 10,
      "shot_type": "全景",
      "shot_position": "后 30s 钩子段",
      "subject": "毛巾裹成猫卷",
      "action": "主人用大毛巾把 YouKei 裹起来, YouKei 露出半张脸",
      "dialog": "主人画外音: '乖, 这是棉花糖版 YouKei'",
      "sfx": "吹风机轰鸣",
      "mood": "温馨释放",
      "emotion_intensity": 4
    },
    {
      "shot": 5,
      "duration_s": 5,
      "shot_type": "特写",
      "shot_position": "末 3s 钩子",
      "subject": "YouKei 的湿眼睛",
      "action": "YouKei 抖毛, 水花四溅到主人脸上",
      "dialog": "—",
      "sfx": "噗嗤",
      "mood": "反转搞笑",
      "emotion_intensity": 5,
      "is_hook": true,
      "hook_subtype": "结果悬念",
      "hook_text": "主人抹脸时, 突然发现 YouKei 已经跳到书房键盘上 — 那是 EP06 加班夜的预告"
    }
  ],
  "key_moments": [
    "0:15 - YouKei 第一次泼水到主人脸上 (萌点)",
    "0:40 - 全身泡沫的 YouKei 像棉花糖 (高潮)",
    "1:05 - 用毛巾裹成猫卷 (释放)"
  ],
  "post_production_notes": [
    "BGM: 紧张喜剧配乐 (2 拍)",
    "字幕: YouKei '喵语' 字幕化",
    "慢动作: 泼水瞬间 0.5x"
  ],
  "memory_updates": {
    "youkei_state_after": {
      "wet": true,
      "towel_wrapped": true,
      "mood": "tired_compliant",
      "location": "卫生间 → 客厅"
    },
    "prop_used": ["浴缸", "宠物洗发水", "毛巾", "吹风机"],
    "timeline": "2026-MM-DD 20:00",
    "hook_chain": "EP05 末 → EP06: 'YouKei 已经跳到书房键盘上'"
  },
  "next_episode_seed": "EP06 加班夜, YouKei 陪我熬夜",
  "continuity_check": {
    "characters_present": ["上坤", "YouKei"],
    "location_previous_ep": "厨房",
    "time_gap": "当天晚 8 点 (EP05 是当天晚 8 点)",
    "mood": "紧张→搞笑→温馨"
  },
  "critic_score": {
    "rhythm": 9,
    "satisfaction": 8,
    "dialog": 8,
    "format": 9,
    "continuity": 9,
    "total": 43,
    "feedback": "萌点密度高, 钩子自然, 连续性好"
  }
}
```

---

## 🔧 技术栈

| 项 | 选 | 备注 |
|---|---|---|
| 语言 | **Python 3.12** | 与 obsidian-novel-publisher 同步, 复用 LLM 客户端 |
| 调度 | **systemd timer** | 06:00 daily |
| LLM | **minimax M3** (MiniMax-M3) | 与 novel-publisher 共享 .env API key |
| HTTP | `requests` + `hmac` | 复用 obsidian-journal hmac_client |
| 状态 | JSON | `data/state/state.json` + `data/state/memory.json` |
| 日志 | `logs/yk-script.log` (滚动 10MB × 5) | |
| 凭据 | `.env` (gitignored) | MINIMAXI_API_KEY / OBSIDIAN_PUBLISH_SECRET / YK_PUBLISHER_ID |

**依赖** (`requirements.txt`):
```
requests>=2.31
PyYAML>=6.0
python-dotenv>=1.0
```

---

## 📡 推送 obsidian-journal (复用现有 API)

**复用项目 A 的 `app/api/external/posts/route.ts`** (HMAC 鉴权)。

```json
{
  "slug": "yk-s01-ep05",
  "title": "EP05 · 🛁 洗澡大作战",
  "excerpt": "YouKei 的第一次洗澡, 从惊慌失措到全身湿漉漉",
  "content": "<上文的 Markdown 渲染>",
  "category": "life",
  "tags": "YouKei,缅因猫,日常,季1-EP05,生活vlog",
  "external_id": "yk-s01-ep05",
  "external_meta": {
    "season": 1,
    "episode": 5,
    "stage": "攀升段",
    "hook_type": "悬念钩",
    "satisfaction_types": ["情感爆发", "悬念揭秘"],
    "duration_estimate_s": 75,
    "scene_location": "卫生间",
    "next_episode_seed": "EP06 加班夜"
  }
}
```

---

## 🎯 第 1 季故事弧 (v0.2 注入节奏四段 + 钩子 5 分布)

> 主线: **"上坤 × YouKei 入住 60 平新家 30 天"**
> 主题: 适应、共处、萌点、生活小摩擦、温馨收尾
> 节奏: **起势 2 集 (17%) / 攀升 4 集 (33%) / 风暴 4 集 (33%) / 决战 2 集 (17%)**

### 起势段 (EP01-02, 17%) — 节奏建立 + 钩子铺设

| EP | 标题 | 场景 | 核心 | 钩子 | 爽点 |
|---|---|---|---|---|---|
| **01** | 📦 搬家日 | 客厅纸箱堆 | YouKei 钻进最大箱子不出来了 | **悬念钩** (来者) | 情感爆发 (萌点) |
| **02** | 🛏️ 第一夜 | 主卧 | 半夜 3 点 YouKei 第一次跳上床踩肚子 | **情绪钩** (甜蜜中断) | 情感爆发 (萌点) |

### 攀升段 (EP03-06, 33%) — 冲突升级 + 萌点累积

| EP | 标题 | 场景 | 核心 | 钩子 | 爽点 |
|---|---|---|---|---|---|
| **03** | 🐦 阳台征服 | 阳台 | YouKei 第一次看窗外飞过的鸟, 激动撞到玻璃 | **信息钩** (线索揭露) | 悬念揭秘 |
| **04** | 🐟 厨房事变 | 厨房+客厅 | YouKei 把我没吃完的鱼叼到沙发下藏起来 | **反转钩** (动机反转) | 打脸 (猫的本能胜利) |
| **05** | 🛁 洗澡大作战 | 卫生间 | YouKei 第一次洗澡, 全程爆走 + 抓伤 | **悬念钩** (结果) | 情感爆发 + 悬念揭秘 |
| **06** | 💻 电脑前的观众 | 书房 | 我加班 YouKei 趴键盘, 误发奇怪邮件 | **情绪钩** (心碎中断) | 情感爆发 (萌点) |

### 风暴段 (EP07-10, 33%) — 高潮密集 + 冲突最大化

| EP | 标题 | 场景 | 核心 | 钩子 | 爽点 |
|---|---|---|---|---|---|
| **07** | 🪟 窗台哲学家 | 客厅窗台 | YouKei 看楼下遛狗的人, 困惑脸 | **信息钩** (证据) | 悬念揭秘 |
| **08** | 👥 朋友来访 | 客厅+玄关 | 朋友对猫毛过敏打喷嚏, YouKei 反而蹭他 | **反转钩** (身份反转) | 打脸 + 情感爆发 |
| **09** | 🚪 第一次外出 | 楼道+电梯 | 把 YouKei 装猫包出门, 它全程叫 | **危机钩** (突袭) | 逆袭翻盘 |
| **10** | 📸 摄影日 | 全屋 | 给 YouKei 拍照纪念, 它一直动 + 表情包 | **反转钩** (局势反转) | 情感爆发 + 悬念揭秘 |

### 决战段 (EP11-12, 17%) — 收束 + 季末温馨

| EP | 标题 | 场景 | 核心 | 钩子 | 爽点 |
|---|---|---|---|---|---|
| **11** | 🤒 生病记 | 主卧 | YouKei 第一次打喷嚏, 我吓到查百度 | **危机钩** (暴露) | 情感爆发 (久别重逢/担心) |
| **12** | 🎄 季末冬至 | 客厅+阳台 | 冬至包饺子, YouKei 偷面团, 季末温馨 | (末集无钩子) | 情感爆发 (大甜) |

**季 2 钩子** (本季末预告): "新年第一天, YouKei 跳上窗台看烟火, 第一次听到鞭炮声, 它会怎么反应?"

### 钩子 5 类型分布 (按 stage)

| 阶段 | 悬念钩 | 反转钩 | 情绪钩 | 信息钩 | 危机钩 |
|---|---|---|---|---|---|
| 起势 | 1 | — | 1 | — | — |
| 攀升 | 1 | 1 | 1 | 1 | — |
| 风暴 | — | 2 | — | 1 | 1 |
| 决战 | — | — | — | — | 1 (EP11) |
| **合计** | **2** | **3** | **2** | **2** | **2** |
| **占比** | **18%** | **27%** | **18%** | **18%** | **18%** |

### 爽点 5 类型配比 (萌宠适配)

| 爽点类型 | 占比 | 我们怎么用 |
|---|---|---|
| 情感爆发 | **60%** | 主线, 萌点+温馨+搞笑瞬间 |
| 悬念揭秘 | **20%** | 副线, 猫的本能行为揭秘 |
| 打脸复仇 | **10%** | 猫的本能"赢"过主人 (小鱼干争夺) |
| 逆袭翻盘 | **5%** | 罕见, 仅风暴段用 |
| 身份碾压 | **5%** | 极罕见, 仅作调剂 (YouKei 其实是家里老大) |

---

## 📋 老板决策清单 (P1-P4, 启动前必须拍)

> **v0.1 的 Q1-Q3 已拍板,本版本更新为 P1-P4 拍板项**

### 已拍 (Q1-Q3, v0.2 直接落地)

| # | 项 | 老板拍板 | 我之前推荐 |
|---|---|---|---|
| Q1 | 老板形象 | **化名"上坤", 只出手+配音, 露脸后期** | 化名+只出手 ✅ |
| Q2 | YouKei 毛色+眼色 | **红虎斑+浅绿色** | 银虎斑+琥珀 (按真实) |
| Q3 | YouKei 名字读法 | **YouKei (日语发音, 太阳/阳光)** | 优琪 (中文) |

### 新增拍板项 (P1-P4, 启动 v0.2)

| # | 项 | 候选 | **黑推荐** |
|---|---|---|---|
| **P1** | 接受 v0.2 架构 (fork short-drama references + 3 Agent)? | 接受 / 退回 v0.1 / 砍 Critic/Memory | ✅ **接受** (fork 8 份 + 3 Agent 是核心增量) |
| **P2** | fork 时是否保留 short-drama 原文 + LICENSE? | 保留 / 仅摘要 / 删除 | ✅ **保留原文 + LICENSE** (MIT 要求, 也方便审) |
| **P3** | Agent 1 候选数 N? | N=2 / N=3 / N=5 | ✅ **N=3** (2 太单一, 4+ 边际收益低, token 多) |
| **P4** | Critic 评分阈值? | ≥35/50 / ≥38/50 / ≥40/50 | ✅ **≥38/50** (优良线, 38-44 微调后可用) |
| **🆕 P5** | 大纲从 GitHub 拉取? | 是 / 否 / 私仓 | ✅ **是 (本仓 public)** — 老板可在 web UI 编辑 |
| **🆕 P6** | 备份仓库? | 新建 / 复用 obsidian-novel-backups / 不备份 | ✅ **复用 obsidian-novel-backups/yk-script/** (不新建) |
| **🆕 P7** | 微信推送? | 是 (新 cron job) / 否 | ✅ **是 (新独立 cron job `notify-yk-script-wechat`)** |
| **🆕 P8** | 备份失败是否阻塞主推送? | 阻塞 / 不阻塞 | ✅ **不阻塞** (微信告警标 "备份失败") |

---

## 📅 实施计划 (估 5.4 工作日, 比 v0.1 多 1d)

| P | 内容 | 文件 | 阻塞 | 时 |
|---|---|---|---|---|
| **P0** | 仓库骨架 (README + .env + .gitignore + tests/) | 5 | 无 | 0.3d |
| **P1** | 角色卡 (youkei.json + protagonist.json + apartment.json) | 3 | Q1-Q3 ✅ | 0.3d |
| **P2** | 故事弧 season-01.json (12 集 + 节奏四段 + 钩子分布) | 1 | 无 | 0.3d |
| **P3** | **fork short-drama references/ → data/knowledge/references/** | 8 (+ LICENSE) | **P2** (MIT 标识) | 0.3d |
| **P4** | prompts/ (writer.yaml + critic_rubric.yaml + hook_distribution.json + satisfaction_matrix.json + memory_constraints.yaml) | 5 | **P1** | 0.5d |
| **P5** | `src/screen_writer.py` (Agent 1, 注入 5 份 references + 生成 3 候选) | 1 | **P4** | 0.6d |
| **P6** | `src/critic.py` (Agent 2, 5 维评分 + Island 反馈循环) | 1 | **P5** | 0.7d |
| **P7** | `src/memory_manager.py` (Agent 3, 状态机 + 硬约束) | 1 | **P2** | 0.5d |
| **P8** | `src/daily.py` + `src/state.py` + `src/markdown_renderer.py` + `src/hmac_client.py` | 4 | **P7** | 0.8d |
| **P9** | systemd timer 06:00 + logrotate + 告警 | 3 | **P8** | 0.3d |
| **P10** | 测试: 单测 (5 文件) + 集成 (e2e dry-run + knowledge loading) | 7 | **P8** | 0.5d |
| **P11** | docs/ (RUNBOOK + CHANGELOG) | 2 | **P9** | 0.2d |
| **🆕 P12** | src/backup_reader.py + src/outline_fetcher.py + pull-outline.py (GitHub 拉大纲) | 3 | **P11** | 0.5d |
| **🆕 P13** | src/github_backup.py + verify-backup.py (备份生成内容) | 2 | **P12** | 0.4d |
| **🆕 P14** | src/wechat_notifier.py + 新 cron job 创建 + daily.py 集成推送 | 3 | **P13** | 0.3d |

**总代码量**: ~1400 LOC (vs v0.2 1100 LOC, 多 300 LOC 来自 GitHub/备份/微信模块)
**总工时**: **5.6d** (vs v0.2 5.4d, 加 0.2d)

---

## 💰 Token 成本估算 (每日 1 集)

| 步骤 | Token | 折算 (minimax 定价) |
|---|---|---|
| 加载 5 份 references (system prompt) | ~3000 input | ~¥0.005 |
| Agent 1 写 3 候选 × 2000 tokens output | 6000 output | ~¥0.10 |
| Agent 2 评审 3 视角 × 500 tokens | 1500 output | ~¥0.025 |
| Agent 3 硬约束检测 | 200 output | ~¥0.003 |
| 失败重写 (5% 概率) × 1 轮 | ~3000 output | ~¥0.05 |
| **每天总成本** | **~10000-13000** | **~¥0.13-0.18** |

每天不到 0.2 元,token 预算完全可承受。

---

## 🛡️ 风控 / 风险 (v0.2 增量)

| 风险 | 等级 | v0.2 缓解 |
|---|---|---|
| YouKei 表演不可控 (猫不听指挥) | 🟡 | 脚本设计偏"日常向"而非"摆拍", 真实反应拍 |
| 老板忘了拍 / 没时间拍 | 🟢 | 脚本只进博客, 不强制产出视频 |
| LLM 故事雷同 / 套路化 | 🟡 (v0.1) | **Memory Manager 强制差异化** (上集钩子必须回收, 不可重复) |
| 故事连续性断裂 (跨季) | 🟢 | season_no 强制 + prev_summary + memory 状态机 |
| 老板个人形象不想曝光 | 🟢 | 化名+只出手 (Q1) |
| 公寓场景单一 | 🟢 | 6 室 + 5 外出备选, 季 2 可加搬家/朋友家 |
| 🆕 5 维评分过严 → 频繁触发重写 | 🟡 | 阈值 38/50 (优良线), 失败 ≥3 次兜底人工告警 |
| 🆕 知识库注入太多 token | 🟢 | 按 stage 只注入相关 5 份, 全文 93KB 但 system prompt 仅取核心 3000 tokens |

---

## ✅ 不在本期范围 (deferred)

- ❌ AI 自动生成视频 (本期只文字脚本, 老板真人拍)
- ❌ 配音自动合成 (老板自己配)
- ❌ 多猫角色 (YouKei 单主角, 后期可加 YouKei 朋友)
- ❌ 跨账号发布 (博客先稳定, 后期接抖音/小红书)
- ❌ 商业化 (赞助/带货/接广告 — 完全不做)
- ❌ 粉丝互动 (评论回复 — 博客无)

---

## 🚦 老板拍板后启动

老板回复 P1-P4 → 黑立即开 P0。
**最快 5.4 天上线, 第二天就有第一集草稿。**

---

## 📚 调研参考资料

| 来源 | URL | 协议 | 借鉴 |
|---|---|---|---|
| short-drama | https://github.com/0xsline/short-drama | MIT | ✅ 直接 fork 8 份 references + 5 维评分 |
| ShakeDrama | https://github.com/XiangTodayEatsWhat/ShakeDrama | Apache 2.0 | ⚠️ 借鉴 multi-agent 拆分思想 |
| COMIC 论文 | https://arxiv.org/abs/2603.11048v1 | 学术 | ⚠️ 借鉴 Island-based 写作循环 |
| COMIC 项目页 | https://susunghong.github.io/COMIC/ | — | 参考 |
---

## 🆕 v0.2 → v0.3 核心变更 (基于 2026-07-11 21:43 老板三增项)

| 维度 | v0.2 (旧) | **v0.3 (新)** | 来源 |
|---|---|---|---|
| 备份机制 | ❌ 无 | ✅ **每日生成内容备份到 `obsidian-novel-backups/yk-script/`** (md + json + index + CHANGELOG) | 对标 publisher/src/github_backup.py |
| 大纲数据源 | ⚠️ 本地 `data/seasons/season-01.json` (老板需手动 PR) | ✅ **GitHub Contents API 拉 `obsidian-yk-script` 仓** (老板可在 web UI 编辑) | 对标 publisher/src/backup_reader.py + novel_outline.py |
| 微信推送 | ❌ 无 | ✅ **复用 publisher 模式: pending.txt + 新 cron job `notify-yk-script-wechat` + 20s sleep** | 对标 publisher/src/wechat_notifier.py + cron job 5225d68b |
| 失败隔离 | ❌ 无 | ✅ **备份失败 → log warning + 微信告警 (不阻塞主推送)** | publisher v0.40 实战教训 |
| Outline 缓存 | ❌ 无 | ✅ **sha 检测 + 3 级 fallback (GitHub → cache → 本地)** | publisher/novel_outline.py |
| 决策项 | P1-P4 | **P1-P8** (新增 P5-P8 拍板: 大纲/备份/微信/失败隔离) | 老板 21:43 拍 |

### v0.3 老板决策清单 (增量)

| # | 项 | 候选 | **黑推荐** |
|---|---|---|---|
| **P5** | 大纲数据源 (GitHub 拉)? | 本仓 public / 私仓 `obsidian-yk-config` / 本地 | ✅ **本仓 public** (老板 web UI 编辑最直接, 角色化名"上坤"+ 标题都是非敏感) |
| **P6** | 备份仓库? | 新建 `obsidian-yk-backups` / 复用 `obsidian-novel-backups/yk-script/` / 不备份 | ✅ **复用** (同 PAT, 路径隔离) |
| **P7** | 微信推送? | 是 (新 cron job) / 否 | ✅ **是 (新独立 cron job `notify-yk-script-wechat`, 防与 publisher race)** |
| **P8** | 备份失败是否阻塞主推送? | 阻塞 / 不阻塞 | ✅ **不阻塞** (微信告警标 "备份失败", 保证博客上线) |

### v0.3 工程量

- 新增 4 个 src/ 模块: `backup_reader.py` (~180 LOC) + `outline_fetcher.py` (~140 LOC) + `github_backup.py` (~220 LOC) + `wechat_notifier.py` (~130 LOC) ≈ **670 LOC**
- 新增 2 个 scripts/: `pull-outline.py` + `verify-backup.py` ≈ **80 LOC**
- 新增 7 个测试文件 (unit 4 + integration 3) ≈ **30 测试**
- 新增 4 项决策 (P5-P8) + 10 项风险 (R13-R22)
- 总工时: **5.2d → 5.6d** (+0.4d)

### v0.3 GitHub 备份策略详解

**复用 publisher 现有模式**, 写入路径:

```
obsidian-novel-backups 私仓 (已有, 不新建)
└── yk-script/                          ← 新增子路径, 与 publisher 隔离
    ├── CHANGELOG.md                    ← 每日追加 1 行
    └── truth/
        └── scripts/
            └── s01/
                ├── ep01.md             ← 渲染 Markdown
                ├── ep01.json           ← EpisodeScript JSON + critic_score
                ├── ep02.md
                ├── ep02.json
                └── index.json          ← 季索引 (追加, 不覆盖)
```

**老板编辑大纲流程** (超简单):

1. 打开 https://github.com/blackclaw0318/obsidian-yk-script/edit/main/data/seasons/season-01.json
2. 直接在 GitHub web UI 编辑 (改标题/钩子/爽点/冲突)
3. 点 "Commit changes"
4. 明天 06:00 cron 自动用最新大纲, 推送老板微信: "📥 outline changed: season-01 sha=xxx→yyy"

### v0.3 微信推送策略详解

**新建独立 cron job `notify-yk-script-wechat`** (避免与 publisher 的 `5225d68b` 撞):

```
publisher  → notify-publisher-wechat (5225d68b-...)
yk-script  → notify-yk-script-wechat (新 job id, 待 P14 创建)
```

**成功消息 (4 行)**:
```
✅ 剧本生成成功 · S01-EP05 洗澡大作战
3 候选 / 最高分 42/50
钩子 悬念钩
https://www.shangkun.uk/posts/yk-s01-ep05
```

**失败消息 (4 行)**:
```
❌ 剧本生成失败 · S01-EP05 洗澡大作战
原因: 3 候选全失败 (LLM 超时)
建议: tail logs/yk-script.log
```

**备份失败独立告警** (主推送已成功时):
```
⚠️ 备份失败 · S01-EP05 洗澡大作战
主推送已成功 · GitHub backup 失败
查看: tail logs/yk-script.log
```

---

*文档版本*: v0.2 (2026-07-11 06:50 GMT+8)
*基于*: v0.1 + 2026-07-11 老板调研请求 (short-drama + ShakeDrama)
*变更摘要*: fork short-drama 8 份 references (MIT) + 引入 3 Agent 架构 (Screenwriter/Critic/MemoryManager) + 5 维评分 + 节奏四段 + 钩子 5 类 + 萌宠适配爽点配比
*作者*: 黑 (Hei)