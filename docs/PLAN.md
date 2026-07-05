# obsidian-yk-script — 方案稿 v0.1 (2026-07-05)

> **项目代号**: obsidian-yk-script
> **目标**: 每天 06:00 自动生成"老板 + 缅因猫 YouKi"生活化短视频脚本（30s-1:30）, POST 到 obsidian-journal 生活分类
> **状态**: ⏸️ 等老板 Q1-Q10 拍板开 P0

---

## 🎯 一句话定位

**每天早上自动写好一集《上坤 × YouKi》单元剧剧本,老板下班回家照着拍。**

12 集一季,前后连贯,可独立观看;主场景上海 60 平小两居,少量外出。

---

## 🏗️ 架构图

```
┌─────────────────────────────────────────────────────────────┐
│  本机 systemd timer: 06:00 daily                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  src/daily.py — 主入口                                       │
│                                                              │
│  1. state = load_state("data/state.json")                   │
│       {season_no, episode_idx (1-12), prev_summary, arc_pos}│
│  2. chars = load("data/characters/*.json")                   │
│       (老板卡 + YouKi 卡 + 公寓场景清单)                     │
│  3. arc = load("data/seasons/season-{N:02d}.json")           │
│       (本季 12 集主线 + 分集要点)                            │
│  4. episode = YKScriptWriter.write_episode(                 │
│       season_no, episode_idx,                               │
│       prev_summary=state.prev_summary,                      │
│       arc_context=arc.episodes[episode_idx - 1]             │
│     ) → EpisodeScript                                       │
│  5. md = render_markdown(episode)                           │
│  6. push_to_obsidian(md, meta)                              │
│       POST /api/external/posts (HMAC)                       │
│       {category:"life", tags:"YouKi,季1-EP02"}              │
│  7. update_state(next_idx, summary, next_hook)              │
│  8. alert_on_failure()                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  obsidian-journal posts 表                                   │
│   category='life', tags='YouKi,季1-EP01'                    │
│   公开页 /posts?tag=YouKi 列表自动展示                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 YouKi 角色卡 (data/characters/)

### YouKi 卡 (`youki.json`) — ⚠️ 待老板 Q1-Q2 补充

```json
{
  "name": "YouKi",
  "species": "Maine Coon (缅因猫)",
  "age_months": 7,
  "gender": "公",
  "appearance": {
    "毛色": "❓ 待老板定 (建议: 银虎斑 / 烟灰 / 纯黑)",
    "眼睛": "❓ 待老板定 (建议: 琥珀 / 蓝绿 / 金)",
    "体型": "中大 (7 月龄, ~3-4kg, 还在长)",
    "特征": "长毛、围脖、大尾巴、耳朵长毛簇"
  },
  "personality": [
    "温顺亲人 (缅因典型)",
    "聪明, 会开门/开抽屉",
    "好奇心重, 对纸袋/箱子痴迷",
    "活泼但不过度闹腾",
    "夜里有跟脚跑习惯"
  ],
  "habits": {
    "晨": "蹭脸叫醒 (5-7 点)",
    "午": "阳台晒太阳 / 窗台观鸟",
    "晚": "跟主人走 / 客厅沙发趴",
    "夜": "凌晨蹦迪 / 钻被窝"
  },
  "forbidden": [
    "❌ 说话 (YouKi 不开口, 字幕可用 '喵' 表示情绪)",
    "❌ 跳跃过高 (拍不到细节)",
    "❌ 危险动作 (爬窗台外侧 / 啃电线)"
  ]
}
```

### 老板卡 (`protagonist.json`) — ⚠️ 待老板 Q1 补充

```json
{
  "name": "上坤",
  "occupation": "HandFoot 商业帝国老板 / AI 工程师 黑 的主人",
  "appearance": "❓ 待老板定",
  "voice_tone": "❓ 待老板定",
  "age_estimate": "❓ 待老板定",
  "living_space": "上海 60 平小两居",
  "daily_rhythm": {
    "morning": "6-7 点被 YouKi 蹭醒",
    "work": "远程办公 / 偶尔外出",
    "evening": "回家陪 YouKi / 做饭 / 拍摄",
    "night": "加班或与 YouKi 互动"
  }
}
```

### 公寓场景卡 (`apartment.json`)

```json
{
  "rooms": {
    "客厅": {
      "面积": "20 ㎡",
      "陈设": "沙发 / 茶几 / 电视 / 书架 / 落地窗 + 阳台门",
      "光线": "南向, 午后强光",
      "适合场景": "沙发互动 / 地板玩耍 / 落地窗观鸟 / 跟脚"
    },
    "主卧": {
      "面积": "12 ㎡",
      "陈设": "1.5 床 / 床头柜 / 衣柜 / 飘窗",
      "光线": "东向, 晨光",
      "适合场景": "晨起蹭脸 / 睡觉 / 飘窗看楼下"
    },
    "次卧 (书房)": {
      "面积": "8 ㎡",
      "陈设": "书桌 / 椅子 / 显示器 / 书架",
      "光线": "北向, 稳定",
      "适合场景": "YouKi 趴键盘 / 电脑前的观众 / 加班陪伴"
    },
    "厨房": {
      "面积": "5 ㎡",
      "陈设": "L 型台面 / 冰箱 / 微波炉",
      "光线": "顶灯",
      "适合场景": "偷鱼 / 跳上台面 / 偷水 (注意拍摄安全)"
    },
    "卫生间": {
      "面积": "4 ㎡",
      "陈设": "淋浴 / 马桶 / 洗手台",
      "光线": "顶灯",
      "适合场景": "洗澡大作战 / 镜前好奇"
    },
    "阳台": {
      "面积": "6 ㎡",
      "陈设": "洗衣区 / 小桌 / 几盆绿植",
      "光线": "全天候, 看天气",
      "适合场景": "晒太阳 / 看鸟 / 看楼下行人"
    }
  },
  "outdoor_optional": [
    "小区楼道 + 电梯 (第一次外出)",
    "楼下小花园 (晒太阳/草地打滚)",
    "街角便利店 (带猫包出镜)",
    "宠物医院 (打疫苗/年检)",
    "朋友家串门 (社交)"
  ]
}
```

---

## 📚 第 1 季故事弧 (data/seasons/season-01.json)

> 主线: **"上坤 × YouKi 入住 60 平新家 30 天"**
> 主题: 适应、共处、萌点、生活小摩擦、温馨收尾

| EP | 标题 | 场景 | 核心冲突 | 钩子 |
|---|---|---|---|---|
| **01** | 📦 搬家日 | 客厅纸箱堆 | YouKi 钻进最大箱子不出来了 | 上集: 新家空荡 / 下集: 第一夜 |
| **02** | 🛏️ 第一夜 | 主卧 | 半夜 3 点 YouKi 第一次跳上床踩肚子 | 上集: 不敢上床 / 下集: 阳台征服 |
| **03** | 🐦 阳台征服 | 阳台 | YouKi 第一次看窗外飞过的鸟, 激动撞到玻璃 | 上集: 鸟在窗外 / 下集: 厨房 |
| **04** | 🐟 厨房事变 | 厨房+客厅 | YouKi 把我没吃完的鱼叼到沙发下藏起来 | 上集: 鱼香味 / 下集: 洗澡 |
| **05** | 🛁 洗澡大作战 | 卫生间 | YouKi 第一次洗澡, 全程爆走 + 抓伤 | 上集: 准备洗澡 / 下集: 加班 |
| **06** | 💻 电脑前的观众 | 书房 | 我加班 YouKi 趴键盘, 误发奇怪邮件 | 上集: 加班夜 / 下集: 窗台 |
| **07** | 🪟 窗台哲学家 | 客厅窗台 | YouKi 看楼下遛狗的人, 困惑脸 | 上集: 第一次看狗 / 下集: 朋友来访 |
| **08** | 👥 朋友来访 | 客厅+玄关 | 朋友对猫毛过敏打喷嚏, YouKi 反而蹭他 | 上集: 客人按门铃 / 下集: 第一次外出 |
| **09** | 🚪 第一次外出 | 楼道+电梯 | 把 YouKi 装猫包出门, 它全程叫 | 上集: 不出门 / 下集: 摄影 |
| **10** | 📸 摄影日 | 全屋 | 给 YouKi 拍照纪念, 它一直动 + 表情包 | 上集: 摄影日 / 下集: 生病 |
| **11** | 🤒 生病记 | 主卧 | YouKi 第一次打喷嚏, 我吓到查百度 | 上集: 打喷嚏 / 下集: 冬至 |
| **12** | 🎄 季末冬至 | 客厅+阳台 | 冬至包饺子, YouKi 偷面团, 季末温馨 | 上集: 冬至 / 下集预告: 季 2 第一集 |

**季 2 钩子** (本季末预告): "新年第一天, YouKi 跳上窗台看烟火, 第一次听到鞭炮声, 它会怎么反应?"

---

## 🎬 单集脚本结构 (LLM 输出格式)

```json
{
  "season": 1,
  "episode": 5,
  "title": "🛁 洗澡大作战",
  "duration_estimate": "75s",
  "logline": "YouKi 的第一次洗澡, 从惊慌失措到全身湿漉漉, 主人全程被抓伤",
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
      "type": "特写",
      "subject": "浴缸 + 温水 + 宠物洗发水",
      "action": "主人试水温, YouKi 在门口探头发呆",
      "dialog": "主人画外音: 'YouKi, 来洗澡了'",
      "sfx": "水声"
    },
    {
      "shot": 2,
      "duration_s": 8,
      "type": "中景",
      "subject": "YouKi 全程",
      "action": "把 YouKi 放进浴缸, 它瞬间弹起 4 只爪子抓盆边",
      "dialog": "主人画外音: '别... 别抓...'",
      "sfx": "哗啦水声 + YouKi 喵叫"
    },
    ... (3-8 个镜头, 总时长 30-90s)
  ],
  "key_moments": [
    "0:15 - YouKi 第一次泼水到主人脸上",
    "0:40 - 全身泡沫的 YouKi 像棉花糖",
    "1:05 - 用毛巾裹成猫卷"
  ],
  "post_production_notes": [
    "BGM: 紧张喜剧配乐 (2 拍)",
    "字幕: YouKi '喵语' 字幕化",
    "慢动作: 泼水瞬间 0.5x"
  ],
  "next_episode_seed": "EP06 加班夜, YouKi 陪我熬夜",
  "continuity_check": {
    "characters_present": ["上坤", "YouKi"],
    "location_previous_ep": "厨房",
    "time_gap": "当天晚 8 点 (EP05 是当天晚 8 点)",
    "mood": "紧张→搞笑→温馨"
  }
}
```

**Markdown 渲染模板**:
```markdown
# EP05 · 🛁 洗澡大作战 (75s)

> **剧情**: YouKi 的第一次洗澡, 从惊慌失措到全身湿漉漉
> **场景**: 卫生间 / 20:00 / 顶灯
> **钩子**: 上集鱼香 → 本集洗澡 → 下集加班夜

---

## 🎬 分镜

### Shot 1 (0:00-0:05) · 特写
- **画面**: 浴缸 + 温水 + 宠物洗发水
- **动作**: 主人试水温, YouKi 在门口探头发呆
- **配音**: "YouKi, 来洗澡了"
- **音效**: 水声

### Shot 2 (0:05-0:13) · 中景
- ...

---

## ✨ 关键瞬间
- 0:15 - YouKi 泼水到主人脸上
- 0:40 - 全身泡沫像棉花糖
- 1:05 - 毛巾裹成猫卷

## 🎞️ 后期
- BGM: 紧张喜剧配乐
- 字幕: YouKi 喵语字幕
- 慢动作: 泼水 0.5x

---

🔜 **下集预告**: EP06 · 💻 电脑前的观众 - 加班夜, YouKi 趴键盘

📌 **连续性**: 同一晚 20:00 / 卫生间 / 承接 EP04 鱼香
```

---

## 🔧 技术栈

| 项 | 选 |
|---|---|
| 语言 | **Python 3.12** (与项目 A 同步, 复用 LLM 客户端) |
| 调度 | **systemd timer** 06:00 daily |
| LLM | **minimax M3** (与项目 A 共享 .env API key) |
| HTTP | `requests` + `hmac` (复用项目 A hmac_client) |
| 状态 | JSON (`data/state.json`) |
| 日志 | `logs/yk-script.log` (滚动 10MB × 5) |
| 凭据 | `.env` (gitignored) — `MINIMAXI_API_KEY` / `OBSIDIAN_PUBLISH_SECRET` / `YK_PUBLISHER_ID` |

---

## 📡 推送 obsidian-journal

**复用项目 A 的 `app/api/external/posts/route.ts`** (HMAC 鉴权)。

```json
{
  "slug": "yk-s01-ep05",
  "title": "EP05 · 🛁 洗澡大作战",
  "excerpt": "YouKi 的第一次洗澡, 从惊慌失措到全身湿漉漉",
  "content": "<上文的 Markdown 渲染>",
  "category": "life",
  "tags": "YouKi,缅因猫,日常,季1-EP05,生活vlog",
  "external_id": "yk-s01-ep05",
  "external_meta": {
    "season": 1,
    "episode": 5,
    "duration_estimate_s": 75,
    "scene_location": "卫生间",
    "next_episode_seed": "EP06 加班夜"
  }
}
```

---

## 📋 老板决策清单 (Q1-Q10, 启动前必须拍)

### 角色设定 (Q1-Q3)
| # | 决策项 | 候选 | **黑推荐** |
|---|---|---|---|
| **Q1** | 老板本人形象 | 实名/化名/不出镜只配音 | **化名"上坤", 只出手/配音, 露脸后期再加** |
| **Q2** | YouKi 毛色+眼色 | 银虎斑+琥珀 / 烟灰+绿 / 纯黑+金 | **银虎斑+琥珀** (缅因经典, 拍摄对比强) |
| **Q3** | YouKi 名字读法 | You-Ki / 优琪 / 油鸡 (萌系) | **优琪** (中文可爱读法, 字幕/配音用) |

### 内容设计 (Q4-Q6)
| # | 决策项 | 候选 | **黑推荐** |
|---|---|---|---|
| **Q4** | 跳集策略 | 不跳 / 累了跳过 / 老板说补 | **不跳, 老板累了说一声我跳 (state.skip_next)** |
| **Q5** | 脚本格式 | JSON / Markdown / 分镜表 | **Markdown** (前端好读) |
| **Q6** | 拍摄主体 | 老板自拍 / 黑远程写实拍 / AI 生成 | **老板自拍** (成本 0, 真情感) |

### 部署运维 (Q7-Q10)
| # | 决策项 | 候选 | **黑推荐** |
|---|---|---|---|
| **Q7** | 发布渠道 | 只博客 / + 抖音 / + 小红书 / + B 站 | **只博客** (先稳定, 后期再外发) |
| **Q8** | YouKi 对话风格 | 不说话+喵字幕 / 配音中文化 / 心声独白 | **不说话+喵语字幕** (萌, 拍不出戏) |
| **Q9** | 触发时间 | 06:00 / 09:00 / 22:00 前一天 | **06:00** (早间写好, 老板下班拍) |
| **Q10** | 视频产出 | 只脚本 / 脚本+拍摄清单 / 脚本+AI 视频 | **只脚本** (黑写剧本, 老板真人拍) |

---

## 📅 实施计划 (估 4.5 工作日)

| P | 内容 | 文件 | 时 |
|---|---|---|---|
| **P0** | 仓库骨架 + .env.example + README + .gitignore | 4 | 0.5d |
| **P1** | 角色卡 (`youki.json` `protagonist.json` `apartment.json`) — 需老板 Q1-Q3 拍板 | 3 | 1d |
| **P2** | 故事弧 (`seasons/season-01.json` 12 集) — 待老板 Q3 第 1 季主题确认 | 1 | 0.5d |
| **P3** | `src/daily.py` 主入口 + `src/state.py` + `src/yk_writer.py` (LLM prompt) | 3 | 1d |
| **P4** | `src/markdown_renderer.py` (JSON → MD 模板) | 1 | 0.5d |
| **P5** | systemd timer 06:00 + logrotate + 告警 | 3 | 0.5d |
| **P6** | 测试: 单测 (角色卡/弧/状态机) + 集成 (mock LLM) + e2e (curl dry-run) | 5 | 0.5d |

**总代码**: ~700 LOC
**总工时**: 4.5d (依赖老板 Q1-Q3 拍板才能开 P1-P2)

---

## 🛡️ 风控 / 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| YouKi 表演不可控 (猫不听指挥) | 🟡 | 脚本设计偏"日常向"而非"摆拍", 用真实反应拍 |
| 老板忘了拍 / 没时间拍 | 🟢 | 脚本只进博客, 不强制产出视频 |
| LLM 故事雷同 / 套路化 | 🟡 | arc_context + 上一集 seed, 12 集一季强制 reset |
| 故事连续性断裂 (跨季) | 🟢 | season_no 强制 + prev_summary 持久 |
| 老板个人形象不想曝光 | 🟢 | 化名+只出手, 后期加 Q1 选项 |
| 公寓场景单一 | 🟢 | 6 室 + 5 外出备选, 季 2 可加搬家/朋友家 |

---

## 📂 仓库结构

```
obsidian-yk-script/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── PLAN.md              # 本文档
│   ├── ARCHITECTURE.md      # 详细架构
│   ├── CHARACTERS.md        # 角色卡摘要 (老板+YouKi)
│   ├── RUNBOOK.md           # 运维
│   └── CHANGELOG.md
├── data/
│   ├── characters/
│   │   ├── youki.json       # YouKi 卡 (Q2 待定)
│   │   ├── protagonist.json # 老板卡 (Q1 待定)
│   │   └── apartment.json   # 公寓场景清单
│   ├── seasons/
│   │   ├── season-01.json   # 第 1 季 12 集 (草稿)
│   │   ├── season-02.json   # 第 2 季 (Q1 末开)
│   │   └── ...
│   ├── state.json           # 当前进度 (gitignored)
│   └── continuity/
│       └── prev_summaries.json
├── src/
│   ├── daily.py             # 主入口 (cron 调用)
│   ├── yk_writer.py         # LLM 写剧 (新)
│   ├── state.py             # 状态机 (新)
│   ├── markdown_renderer.py # JSON → MD (新)
│   └── hmac_client.py       # 复用项目 A
├── scripts/
│   ├── publish-today.py
│   ├── skip-next.py         # 老板说"今天跳过"
│   └── dry-run.py
├── systemd/
│   ├── yk-script.service
│   └── yk-script.timer      # 06:00 daily
├── logs/                    # gitignored
└── tests/
    ├── unit/
    │   ├── test_yk_writer.py
    │   ├── test_state_machine.py
    │   └── test_markdown_renderer.py
    └── integration/
        └── test_daily_e2e.py
```

---

## ✅ 不在本期范围 (deferred)

- ❌ AI 自动生成视频 (本期只文字脚本, 老板真人拍)
- ❌ 配音自动合成 (老板自己配)
- ❌ 多猫角色 (YouKi 单主角, 后期可加 YouKi 朋友)
- ❌ 跨账号发布 (博客先稳定, 后期接抖音/小红书)
- ❌ 商业化 (赞助/带货/接广告 — 完全不做)
- ❌ 粉丝互动 (评论回复 — 博客无)

---

## 🚦 老板拍板后启动

老板回复 Q1-Q10 (尤其 Q1-Q3 角色设定) → 黑立即开 P0。
**最快 4.5 天上线, 第二天就有第一集草稿。**

---

*文档版本*: v0.1 (2026-07-05 09:35 GMT+8)
*作者*: 黑 (Hei)