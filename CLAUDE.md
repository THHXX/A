# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

MiroFish 是一个多智能体仿真预测引擎：上传种子文档 + 自然语言预测需求 → 自动生成本体、构建知识图谱、生成 Agent 人设、运行 Twitter/Reddit 双平台 OASIS 仿真、产出预测报告并支持深度交互。仿真引擎基于 [CAMEL-AI/OASIS](https://github.com/camel-ai/oasis)。

## 常用命令

依赖：Node.js ≥18，Python ≥3.11 且 ≤3.12，[uv](https://docs.astral.sh/uv/)。所有命令在仓库根目录执行（`npm run` 脚本会自动 `cd` 到子目录）。

```bash
# 一次性安装所有依赖（根 + frontend npm + backend uv sync）
npm run setup:all

# 同时启动前后端（concurrently，两个窗口合并输出）
npm run dev

# 单独启动
npm run backend     # cd backend && uv run python run.py  → :5001
npm run frontend    # cd frontend && vite --host          → :3000

# 前端构建
npm run build

# 后端测试（dev 依赖含 pytest / pytest-asyncio）
cd backend && uv run pytest
cd backend && uv run pytest tests/path/to/test_xxx.py::test_name   # 单条测试

# Docker
docker compose up -d   # 读取根目录 .env，端口 3000 / 5001
```

启动前若 3000 / 5001 被占用，**强制 kill 占用进程**，不更换端口（见下方"项目规则"）。

## 必需的环境变量

`.env` 放在仓库**根目录**（`backend/app/config.py:11` 显式从 `../../.env` 加载，未配置时回退到进程环境）：

- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME`：OpenAI 兼容格式（推荐阿里百炼 qwen-plus）
- `ZEP_API_KEY`：Zep Cloud（图谱后端）
- `LLM_BOOST_*`：可选的加速 LLM；不使用时**不要在 .env 中保留这些键**（即便为空）

`Config.validate()` 在启动时检查，缺失会直接 `sys.exit(1)`。

## 高层架构

### 五步用户流水线（前端路由 ↔ 后端蓝图）

`frontend/src/router/index.js` 定义的页面流程，与后端三大蓝图一一对应：

| 步骤 | 前端路由 / 视图 | 后端蓝图 | 关键服务 |
|---|---|---|---|
| 1. 图谱构建 | `/process/:projectId` → `MainView.vue`（含 `Step1GraphBuild.vue`） | `/api/graph/*` | `OntologyGenerator` → `GraphBuilderService`（写入 Zep） |
| 2. 环境搭建 | `Step2EnvSetup.vue` | `/api/simulation/entities/*`、`/prepare`、`/generate-profiles` | `ZepEntityReader`、`OasisProfileGenerator`、`SimulationConfigGenerator` |
| 3. 模拟运行 | `/simulation/:simulationId/start` → `SimulationRunView.vue` | `/api/simulation/start`、`/run-status`、`/timeline` 等 | `SimulationRunner`（subprocess + IPC） |
| 4. 报告 | `/report/:reportId` → `ReportView.vue` | `/api/report/*` | `report_agent.py`（带工具与反思循环） |
| 5. 互动 | `/interaction/:reportId` → `InteractionView.vue` | `/api/simulation/interview*`、`/api/report/chat` | IPC `INTERVIEW` 命令 + ReportAgent 对话 |

### 后端：Flask 应用工厂 + 蓝图

`backend/app/__init__.py:create_app()` 注册三个蓝图，所有 API 都在 `/api/*` 之下：

- `graph_bp` (`/api/graph`)：项目 CRUD、本体生成（`/ontology/generate`）、异步图谱构建（`/build` → 后台线程 + `/task/<id>` 轮询）
- `simulation_bp` (`/api/simulation`)：实体读取、人设/配置生成、`/start` 启动子进程、`/run-status` 轮询、`/interview*` IPC 调用、`/close-env` 关闭
- `report_bp` (`/api/report`)：报告生成（带 `progress` / SSE 流接口）、章节增量获取、`/chat` 对话、工具调用日志

健康检查：`GET /health`。CORS 对所有 `/api/*` 开放。Windows 控制台 UTF-8 处理在 `backend/run.py:9-16` 和 `scripts/run_parallel_simulation.py:35-39` 同样要重复——**修改启动脚本时不要删掉这些 import 之前的代码块**。

### 状态持久化（无数据库）

所有状态用文件落盘在 `backend/uploads/`：

```
backend/uploads/
├── projects/<project_id>/
│   ├── project.json          # ProjectManager 序列化的 Project（含 status、graph_id）
│   ├── extracted_text.txt    # 文档解析后合并文本
│   └── 原始上传文件
├── simulations/<simulation_id>/
│   ├── simulation_config.json     # 喂给 OASIS 的最终配置
│   ├── twitter_profiles.json / reddit_profiles.json
│   ├── state.json / run_state.json / env_status.json
│   ├── twitter/actions.jsonl / reddit/actions.jsonl   # 每轮动作流水
│   ├── ipc_commands/  ipc_responses/                  # 进程间通信文件队列
│   └── simulation.log
└── reports/<report_id>/
    ├── meta.json / outline.json / progress.json
    ├── sections/, agent_log/, console_log/
```

`ProjectStatus` 状态机：`CREATED → ONTOLOGY_GENERATED → GRAPH_BUILDING → GRAPH_COMPLETED`（`FAILED` 任意态可达）。前端不要重复传大对象——后端按 `project_id` / `simulation_id` / `report_id` 自取。

### 模拟子进程模型（重点）

`/api/simulation/start` **不**在 Flask 进程内跑模拟，而是 spawn `backend/scripts/run_parallel_simulation.py` 子进程，原因：

1. OASIS / camel-ai 重度使用 asyncio + 第三方库，与 Flask 主线程冲突
2. 单次模拟可运行数十轮、数十分钟，必须可独立 kill
3. 子进程结束后**默认不退出**，进入"等待命令模式"以支持后续 Interview

通信走**基于文件的 IPC**（`simulation_ipc.py`）：Flask 把命令 JSON 写入 `ipc_commands/`，子进程轮询执行并把结果写入 `ipc_responses/`。命令类型见 `CommandType`：`INTERVIEW` / `BATCH_INTERVIEW` / `CLOSE_ENV`。**新增命令时三处都要改**：`CommandType` 枚举、子进程 dispatcher、Flask `SimulationIPCClient` 调用方。

服务器关闭时 `SimulationRunner.register_cleanup()`（`__init__.py:46-49`）会 `atexit` 终止所有未关闭的子进程，避免孤儿。

### 异步任务

图谱构建用 `threading.Thread(daemon=True)`（`backend/app/api/graph.py:507`）+ `TaskManager` 内存任务表，前端轮询 `/api/graph/task/<task_id>`。报告生成走类似的 `progress.json` + SSE 流。**没有** Celery / Redis Queue——保持现状，引入前先讨论。

### 前端：Vue 3 + Vite + Vue Router + axios

- 全局 axios 在 `frontend/src/api/index.js`，超时 5 分钟（本体生成耗时长），自动解包 `{success, data}` 失败时 reject
- `requestWithRetry()` 是指数退避重试帮手；按需用，不要默认套
- 视图分两层：`Home.vue` 入口 → `MainView.vue` 五步主流程 → 各 Step 组件；模拟运行/报告/互动是独立路由
- D3 用于 `GraphPanel.vue` 力导向图

## 项目规则

### 运行规范
- 启动项目前若端口被占用，强制杀死占用进程，不更换端口号

### 代码规范
- 优先编辑现有文件（Edit），不重写整个文件（Write）
- 不重复读取本轮对话中已读取且未修改的文件
- 不添加未要求的功能、注释、错误处理、类型注解
- 生成的单个文件不超过 400 行，代码嵌套不超过 4 层

### 回复规范
- 回复简洁，不在末尾总结刚做的事
