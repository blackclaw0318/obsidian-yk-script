# obsidian-yk-script

> 每天自动生成《上坤 × YouKi》单元剧短视频脚本, 推送到 obsidian-journal 生活分类
> **状态**: ⏸️ 方案稿 v0.1, 等老板拍板启动开发

[![Status](https://img.shields.io/badge/status-proposal-yellow)]()
[![Python](https://img.shields.io/badge/python-3.12+-blue)]()
[![LLM](https://img.shields.io/badge/LLM-MiniMax--M3-orange)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## 🎯 这是什么

每天早上 06:00 自动生成 1 集《上坤 × 缅因猫 YouKi》生活化短视频脚本:

- **时长**: 30s - 1:30 (短视频/抖音/B站长度)
- **场景**: 上海 60 平小两居为主, 少量外出
- **结构**: 12 集一季, 单元剧 + 连续剧双线 (可独立看 + 主线连贯)
- **主角**: 老板(化名"上坤") + 7 月龄公缅因猫 YouKi
- **风格**: 有趣 + 生活化 + 拍摄可行

老板下班回家, 照着脚本用手机拍真人版 → 上传 B站/小红书。

---

## 📦 依赖关系

```
┌─────────────────────────────┐
│  obsidian-yk-script         │  ← 本仓库 (剧本生成器)
│  (Python 3.12, cron 06:00)  │
└──────────────┬──────────────┘
               │ HTTPS POST
               │ HMAC-SHA256 鉴权 (与项目 A 共用)
               ▼
┌─────────────────────────────┐
│  obsidian-journal           │  ← 博客 (接收方)
│  app/api/external/posts     │  ← 共享项目 A 的 API
└─────────────────────────────┘
```

---

## 🎬 第一季剧集 (12 集)

> 主线: **"上坤 × YouKi 入住 60 平新家 30 天"**

| EP | 标题 | 时长 |
|---|---|---|
| 01 | 📦 搬家日 | 60s |
| 02 | 🛏️ 第一夜 | 45s |
| 03 | 🐦 阳台征服 | 50s |
| 04 | 🐟 厨房事变 | 70s |
| 05 | 🛁 洗澡大作战 | 75s |
| 06 | 💻 电脑前的观众 | 60s |
| 07 | 🪟 窗台哲学家 | 55s |
| 08 | 👥 朋友来访 | 80s |
| 09 | 🚪 第一次外出 | 65s |
| 10 | 📸 摄影日 | 50s |
| 11 | 🤒 生病记 | 70s |
| 12 | 🎄 季末冬至 | 90s |

---

## 🚦 状态

- [x] **v0.1 方案稿** (2026-07-05) — 本 README
- [ ] 等老板拍 Q1-Q10 决策 (尤其 Q1-Q3 角色设定)
- [ ] v0.2 P0-P6 实施 (~4.5d)
- [ ] v1.0 上线, 每天 1 集自动产出

---

## 📚 文档

- 📋 [docs/PLAN.md](docs/PLAN.md) — **完整方案稿** (角色卡 + 故事弧 + 决策清单)
- 🐱 [docs/CHARACTERS.md](docs/CHARACTERS.md) — 角色卡摘要 (老板 + YouKi + 公寓)
- 🏗️ [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 详细技术架构
- 🛠 [docs/RUNBOOK.md](docs/RUNBOOK.md) — 运维 / 部署 / 故障排查

---

## 🚀 快速预览 (待实现)

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 .env
cp .env.example .env
# 填入 MINIMAXI_API_KEY 和 OBSIDIAN_PUBLISH_SECRET

# 3. 单日脚本生成 (调试用)
python scripts/publish-today.py

# 4. 跳过明天 (老板累了)
python scripts/skip-next.py

# 5. systemd timer 启动 (本机)
sudo cp systemd/yk-script.{service,timer} /etc/systemd/system/
sudo systemctl enable --now yk-script.timer

# 6. 查看日志
tail -f logs/yk-script.log
```

---

## ⚠️ 关键决策等老板

详见 [docs/PLAN.md § 老板决策清单](docs/PLAN.md#-老板决策清单-q1-q10-启动前必须拍):

**角色设定 (必拍)**:
- **Q1**: 老板本人形象 (化名/露脸/只配音)
- **Q2**: YouKi 毛色 + 眼色
- **Q3**: YouKi 中文读法 (优琪/油鸡/You-Ki)

**内容设计**:
- **Q4**: 跳集策略
- **Q5**: 脚本格式
- **Q6**: 拍摄主体

**部署运维**:
- **Q9**: 触发时间
- **Q10**: 视频产出范围

---

*作者*: 黑 (Hei) · *创建*: 2026-07-05
*License*: MIT