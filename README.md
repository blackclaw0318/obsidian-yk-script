# obsidian-yk-script

> 每天自动生成《上坤 × 缅因猫 YouKei》单元剧短视频脚本 → 备份到 GitHub → 微信通知老板

[![Status](https://img.shields.io/badge/status-v0.3%20in%20development-yellow)]()
[![Python](https://img.shields.io/badge/python-3.12+-blue)]()
[![LLM](https://img.shields.io/badge/LLM-MiniMax--M2.7-orange)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## 🎯 这是什么

每天早上 06:00 自动生成 1 集《上坤 × 缅因猫 YouKei》生活化短视频脚本:

- **时长**: 30s - 1:30 (短视频/抖音/B站长度)
- **场景**: 上海 60 平小两居为主, 少量外出
- **结构**: 12 集一季, 单元剧 + 连续剧双线 (可独立看 + 主线连贯)
- **主角**: 上坤 (化名, 只出手+配音) + 7 月龄公缅因猫 YouKei (红虎斑+浅绿眼, 日语读音)
- **风格**: 有趣 + 生活化 + 拍摄可行
- **3 层保障**: Screenwriter (写 3 候选) → Critic (5 维评分) → Memory (硬约束)

老板下班回家, 照着脚本用手机拍真人版 → 上传 B站/小红书。

---

## 🏗️ v0.3 架构亮点

```
06:00 cron 触发
  ↓
GitHub 拉取大纲 (sha 检测 + 3 级 fallback)
  ↓
3 Agent 协作 (Writer → Critic → Memory)
  ↓
Render Markdown → 推送 obsidian-journal
  ↓
GitHub 备份 (失败不阻塞, 微信告警)
  ↓
微信推送 (✅ 成功 / ❌ 失败 / ⚠️ 备份失败)
```

**核心创新**:
- 🆕 **大纲从 GitHub 拉** — 老板可在 web UI 直接编辑 `data/seasons/season-XX.json`,明天自动生效
- 🆕 **GitHub 备份** — 每日生成内容备份到 `obsidian-novel-backups/yk-script/` (复用 publisher 私仓)
- 🆕 **微信推送** — 复用 publisher 模式,新建独立 cron job `notify-yk-script-wechat`

---

## 📦 依赖关系

```
┌─────────────────────────────────────┐
│  obsidian-yk-script                 │
│  (Python 3.12, systemd timer 06:00) │
└──────┬──────────┬──────────┬────────┘
       │          │          │
       ▼          ▼          ▼
┌──────────┐ ┌─────────┐ ┌────────────────┐
│ HMAC POST│ │ GitHub  │ │ 微信 cron job  │
│ (publish)│ │ (拉+备份)│ │ (openclaw-     │
│          │ │         │ │  weixin)       │
└──────────┘ └─────────┘ └────────────────┘
       │          │          │
       ▼          ▼          ▼
┌──────────────┐ ┌─────────────┐ ┌─────────────┐
│ obsidian-    │ │ obsidian-   │ │ 老板微信    │
│ journal      │ │ novel-      │ │ o9cq805h... │
│ (博客)       │ │ backups     │ └─────────────┘
└──────────────┘ └─────────────┘
```

---

## 📁 仓库结构 (v0.3)

```
obsidian-yk-script/
├── README.md
├── LICENSE                             # MIT
├── .env.example                        # 凭据模板 (gitignored .env)
├── .gitignore                          # + data/cache/ + data/state/
├── pyproject.toml                      # Python 3.12 + 依赖
│
├── data/
│   ├── characters/                     # 📥 boss 可编辑
│   │   ├── youkei.json
│   │   ├── protagonist.json
│   │   └── apartment.json
│   ├── seasons/                        # 📥 boss 可编辑 (从 GitHub 拉)
│   │   └── season-01.json
│   ├── knowledge/references/           # 🔒 fork 自 short-drama (MIT)
│   │   ├── opening-rules.md
│   │   ├── rhythm-curve.md
│   │   ├── hook-design.md
│   │   └── ... (8 份)
│   ├── cache/                          # 🆕 v0.3 GitHub 拉取缓存 (gitignored)
│   └── state/                          # gitignored
│
├── prompts/                            # LLM 模板 (YAML + JSON)
│   ├── writer.yaml
│   ├── critic_rubric.yaml
│   ├── hook_distribution.json
│   ├── satisfaction_matrix.json
│   └── memory_constraints.yaml
│
├── src/                                # Python 代码
│   ├── daily.py                        # 主入口 orchestrator
│   ├── types.py                        # Pydantic 数据类
│   ├── llm_client.py                   # minimax M2.7 wrapper
│   ├── screen_writer.py                # Agent 1: 写
│   ├── critic.py                       # Agent 2: 审
│   ├── memory_manager.py               # Agent 3: 管
│   ├── markdown_renderer.py            # JSON → MD
│   ├── hmac_client.py                  # 推 obsidian-journal
│   ├── state.py                        # 状态读写
│   ├── backup_reader.py                # 🆕 GitHub Contents API 只读
│   ├── outline_fetcher.py              # 🆕 sha 检测 + 缓存
│   ├── github_backup.py                # 🆕 备份到 obsidian-novel-backups
│   ├── wechat_notifier.py              # 🆕 微信推送
│   └── logger.py
│
├── scripts/
│   ├── publish-today.py
│   ├── skip-next.py
│   ├── dry-run.py
│   ├── regenerate.py
│   ├── seed-state.py
│   ├── pull-outline.py                 # 🆕
│   └── verify-backup.py                # 🆕
│
├── systemd/
│   ├── yk-script.service
│   └── yk-script.timer                 # 06:00 daily
│
└── tests/
    ├── unit/                           # 单元测试
    └── integration/                    # 集成测试
```

---

## 🎬 第一季剧集 (12 集)

> 主线: **"上坤 × YouKei 入住 60 平新家 30 天"**

| EP | 标题 | 阶段 | 时长 |
|---|---|---|---|
| 01 | 📦 搬家日 | 起势 | 60s |
| 02 | 🛏️ 第一夜 | 起势 | 45s |
| 03 | 🐦 阳台征服 | 攀升 | 50s |
| 04 | 🐟 厨房事变 | 攀升 | 70s |
| 05 | 🛁 洗澡大作战 | 攀升 | 75s |
| 06 | 💻 电脑前的观众 | 攀升 | 60s |
| 07 | 🪟 窗台哲学家 | 风暴 | 55s |
| 08 | 👥 朋友来访 | 风暴 | 80s |
| 09 | 🚪 第一次外出 | 风暴 | 65s |
| 10 | 📸 摄影日 | 风暴 | 50s |
| 11 | 🤒 生病记 | 决战 | 70s |
| 12 | 🎄 季末冬至 | 决战 | 90s |

**节奏**: 起势 17% / 攀升 33% / 风暴 33% / 决战 17%

---

## 🚀 快速预览

```bash
# 1. 安装依赖
pip install -e ".[dev]"

# 2. 配置 .env
cp .env.example .env
# 填入 MINIMAXI_API_KEY / OBSIDIAN_PUBLISH_SECRET / GITHUB_BACKUP_TOKEN / YK_WEIXIN_CRON_JOB_ID

# 3. 单日脚本生成 (调试用)
python -m scripts.dry_run --force-episode 0

# 4. 手动拉取 GitHub 大纲 (调试)
python -m scripts.pull_outline

# 5. 验证备份 (调试)
python -m scripts.verify_backup

# 6. systemd timer 启动 (本机)
sudo cp systemd/yk-script.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yk-script.timer

# 7. 查看日志
tail -f logs/yk-script.log
```

---

## 📚 文档

| 文档 | 用途 |
|---|---|
| 📋 [docs/PLAN.md](docs/PLAN.md) | why/what — 战略层 + 季弧 + 角色 + 决策清单 (P1-P8) |
| 🛠 [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) | how — prompt 模板 + Agent 代码 + 测试矩阵 + 15 步 gated commits + 22 风险 + 14 决策 |
| 🏗 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 详细架构 + 数据流 |
| 📚 [docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md) | 8 份 references 摘要与用法 |
| 🛡 [docs/RUNBOOK.md](docs/RUNBOOK.md) | 运维 / 部署 / 故障排查 (P15 落地) |

---

## 📅 状态 (v0.3 进度)

- [x] **v0.1 方案稿** (2026-07-05) — commit `d189407`
- [x] **v0.2 调研 + 方案** (2026-07-11) — commit `a7c0419`
- [x] **v0.3 三增项落地** (2026-07-11 21:43) — commit `1265001`
- [ ] **P0-P15 实施** (5.6d) — 当前 ⏳ feat/v0.3-implementation 分支
  - [x] P0 仓库骨架 ✅ (2026-07-11 21:58)
  - [ ] P1 角色卡
  - [ ] P4 prompts
  - [ ] P5-P8 Agent 代码 + 主入口
  - [ ] P9-P11 systemd + 集成 + scripts
  - [ ] P12-P14 outline_fetcher / github_backup / wechat_notifier
  - [ ] P15 RUNBOOK + dry-run EP01
- [ ] **v1.0 上线** — 每天 06:00 自动产出 + 老板微信收到推送

---

*作者*: 黑 (Hei) · *License*: MIT
*仓库*: https://github.com/blackclaw0318/obsidian-yk-script