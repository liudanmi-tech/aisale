# AIGC 营销素材智能投放平台（v0.2 演示版）

面向传音（TECNO / Infinix / itel）出海投放：从竞品爆款里找精品 → Agent 洗剧本与本土化 → Seedance 生成视频 → 40 个虚拟用户 Agent 评测 → 按人群标签自动投放 TikTok → 数据回收与自动优化 → 迭代再生成。每个模块产出结论后都要人工审核才继续。

界面风格参考 LibTV（左侧边栏、新建画布面板、Skill 卡片库、作品墙）。核心界面是**项目画布**：左侧 Agent 对话、右侧无限画布。Agent 只能通过画布工具改画布，每次改动都是「计划卡 + 画布预览 → 确认 → 逐步落地 → 可撤销」。

## 目录

```
api/    FastAPI 后端：数据表、画布补丁、Agent、模块工作流与审核门、外部服务适配器
web/    前端：Vite + React 19 + React Router 7 + TypeScript + Ant Design 6 + Tailwind 4 + Zustand + TanStack Query
docs/   UI 设计文档、早期单文件原型
```

前端技术栈与 GitHub 上 star 最多的 AI 生图 / 生视频无限画布项目 [basketikun/infinite-canvas](https://github.com/basketikun/infinite-canvas) 保持一致，画布同样为自研（DOM 节点 + SVG 连线 + 平移缩放），未使用 React Flow。

## 本地运行

```bash
# 后端（默认 SQLite，外部服务全部为模拟模式）
cd api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000

# 前端（开发模式，/api 代理到 8000）
cd web
npm install
npm run dev          # http://localhost:3000
```

单容器部署：`npm run build` 后，后端会直接托管 `web/dist`，访问 `http://localhost:8000` 即可；或 `docker compose up --build`（含 PostgreSQL）。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./aigc.db` | 生产用 `postgresql+psycopg://user:pass@host:5432/db` |
| `LLM_ENABLED` | `false` | 开启后 Agent 用大模型理解指令、写剧本；关闭时用规则解析与模板 |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | OpenRouter / 空 / `google/gemini-2.5-flash` | OpenAI 兼容接口 |
| `SEEDANCE_MODE` | `mock` | `real` 时调用 BytePlus ModelArk，需 `SEEDANCE_API_KEY`、`SEEDANCE_MODEL` |
| `TIKTOK_MODE` | `mock` | `real` 时调用 TikTok Business API v1.3，需 `TIKTOK_ACCESS_TOKEN`、`TIKTOK_ADVERTISER_ID` |
| `STEP_DELAY` | `1.0` | 模拟模式下每个生成步骤的耗时（秒），测试设为 0 |

Seedance 与 TikTok 的真实调用字段按公开资料编写，拿到官方 API 文档和凭证后需逐项核对（见 `api/app/adapters/`）。

## 测试

```bash
cd api && .venv/bin/python -m pytest -q tests
```

`tests/test_flow.py` 走完 9 步核心链路，并覆盖：计划卡调整数量、整组撤销、计划生成后画布被改导致计划失效、驳回必须填理由且自动重做、未审核不能下发、上游未通过时拦截下游指令。已在 SQLite 与 PostgreSQL 16 上通过。

## 与技术方案的差异（演示版取舍）

| 技术方案 | 演示版 | 后续 |
| --- | --- | --- |
| Temporal 工作流 + Signal 审核门 | 进程内异步任务 + 数据库状态机（节点状态 + review_task） | 接口不变，替换 `app/workflows.py` 为 Temporal 子工作流 |
| SSE 流式 Agent 回复 | 请求返回后经 WebSocket 推送刷新 | 接入流式输出 |
| 40 Agent 多模态评测 | 画像抽样 + 确定性模拟打分 | 接入多模态模型逐秒观看成片 |
| ClickHouse 指标库 | `metric_daily` 表（模拟回收数据） | 接入 TikTok 报表 API 与 ClickHouse |
| 第三方广告情报 | 预置 10 条样例爆款 | 采购后接入适配器 |
| 浏览器 Agent 云虚拟机 | 未实现，投放全部走 API 适配器 | 二期 |
