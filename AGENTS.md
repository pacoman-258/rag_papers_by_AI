# AGENTS.md

本文件面向后续进入本仓库协作的 Codex / agent，目标是让开发动作稳定、可追踪、可交接。

## 1. 项目目标

- 这是一个面向论文检索与问答的实验工作台，主链路是“抓取 / 入库 / 检索 / 重排 / 回答”。
- 主产品能力在搜索工作台、PST-lite trace 与独立的 `Paper Reader` 单篇精读页；Live2D 助手属于增强层，不是主检索链路。
- 任何改动都应优先保护主搜索链路的可用性，其次再扩展助手层体验。

## 2. 目录职责

- `frontend/`：React + Vite 前端工作台。
- `backend/`：FastAPI 编排层、配置存储、Live2D 服务、助手长期记忆。
- `local_paper_db/app/`：检索、重排、模型调用、数据库查询等核心 RAG 逻辑。
- `ArXiv_craw/`：arXiv 抓取与元数据准备。
- `config/`：运行时配置文件目录，只提交 `runtime_settings.example.json`。
- `docker/` 与 `docker-compose.postgres.yml`：本地 PostgreSQL/扩展初始化。

## 3. 常用命令

- Python 环境：`python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- 一键启动工作台：`./start_workbench.command`
- 后端开发：`./start_backend.command`
- 后端脚本入口：`./scripts/start_backend.sh`
- 前端开发：`cd frontend && npm install && npm run dev`
- 前端构建：`cd frontend && npm run build`
- 抓取论文：`cd ArXiv_craw && python crawer.py`
- 本地入库：`cd local_paper_db/app && python in.py`
- CLI 检索：`cd local_paper_db/app && python search.py`

## 4. 全局协作约定

- 开始改动前先阅读受影响文件，不要只凭 README 猜行为。
- 每次有意义的改动完成后，必须更新根目录 `PROJECT_LOG.md`。
- 如果改动影响命令、接口、配置项、目录职责或用户可见行为，优先考虑同步更新 `README.md` / `README.zh-CN.md`。
- 不要提交真实的 `config/runtime_settings.json`、API key、数据库凭据或其他本地秘密。
- API key 在前后端都应保持“只写不回显”；响应只返回 `has_api_key` 一类布尔状态。
- 避免把业务逻辑继续堆进超大入口文件；新增能力优先放进职责明确的模块。

## 5. 前端约定

- 前端技术栈固定为 React 18 + Vite，入口在 `frontend/src/main.jsx`，页面主编排在 `frontend/src/App.jsx`。
- `frontend/src/App.jsx` 目前承担标签页、设置页、搜索工作台、trace 工作台、`Paper Reader`、入库管理和助手层容器；改动前先确认状态是否已经存在于该文件中。
- `frontend/src/PaperReaderPage.jsx` 负责单篇论文精读页，包含 arXiv / PDF 入口、分页精读、分页预取和论文追问；涉及该页的接口变更要同步检查其流式分页逻辑。
- 复杂助手逻辑保持在 `frontend/src/Live2DAssistant.jsx`，不要把 Live2D 实现重新塞回 `App.jsx`。
- 样式集中在 `frontend/src/styles.css`，应沿用已有的 CSS 变量、卡片布局和响应式分区，避免引入第二套视觉规则。
- 前端通过 `/api/*` 与后端通信，并依赖 SSE 事件流驱动回答与日志展示；变更接口时必须同步检查前后端。
- 语言与助手会话 ID 当前使用 `localStorage` 持久化，键名分别为 `app_language` 与 `live2d_assistant_session_id`，修改时要考虑兼容迁移。

## 6. 后端约定

- `backend/main.py` 主要负责路由、编排和响应封装；检索、重排、模型调用不要继续直接堆进这里。
- 检索主逻辑优先放在 `local_paper_db/app/search_service.py`；配置读写只走 `backend/config_store.py`。
- `backend/paper_reader_service.py` 负责单篇 PDF / arXiv 论文的解析、动态分页、分页缓存和论文追问；`main.py` 只负责暴露 `/api/paper-reader/*` 路由。
- 请求/响应模型统一收敛到 `backend/schemas.py`，新增接口尽量先补 schema 再写路由。
- 运行时配置优先级保持为：请求体设置 > `config/runtime_settings.json` > 环境变量。
- `paper_reader_chat` 是独立于 `query_chat` / `answer_chat` 的精读模型配置，前后端都要保证 `max_context_tokens` 会参与分页预算计算。
- 当前 `search_sessions`、`trace_sessions`、`IngestManager` 都是进程内状态；如果要改成持久化或多 worker 模式，需要在日志和文档里明确说明。
- Python 依赖当前同时存在于 `pyproject.toml` 与 `requirements.txt`，新增或删除依赖时尽量同步两边，避免环境漂移。

## 7. 助手层约定

- 助手层是附加增强模块，不得影响主搜索/trace 功能；`bootstrap`、TTS、记忆召回、记忆写入失败时应允许降级为普通聊天。
- 助手不得编造论文、引用、检索结果或工作流上下文。
- `/api/live2d/chat` 的协议由 `backend/schemas.py`、`backend/main.py`、`frontend/src/Live2DAssistant.jsx` 共同约束；修改任一侧时必须联动检查另外两侧。
- `session_id` 应尽量稳定复用；`answer_context` / `workflow_context` 只表示最近一次 QA 或 PST 结果，不应当成全局事实库。
- 新增 `workflow_context.kind = "paper_reader"` 后，助手只做精读摘要和当前页问答的辅助解释，不得替代主精读区或论文追问接口。
- 长期记忆表结构和召回逻辑在 `backend/assistant_memory.py`；如果调整记忆阈值或 summary 策略，要确认配置项是否真正接入运行逻辑。
- `pin/delete` 等记忆操作当前按 `memory_id` 工作，未来若扩展多 profile / 多 session，需要格外小心兼容性。

## 8. 修改收尾清单

- 确认受影响层的接口、文案、配置和 README 是否一致。
- 运行与改动匹配的最小验证；如果没跑测试，要在 `PROJECT_LOG.md` 或最终说明里写明原因。
- 将本次改动按时间追加到 `PROJECT_LOG.md` 顶部。
- 若新增长期约束、目录职责或跨层协议，也要同步更新本文件。

## 9. 当前已知风险

- `frontend/src/App.jsx` 与 `frontend/src/Live2DAssistant.jsx` 仍然偏大，继续加功能时要警惕状态耦合。
- SSE 事件名和 JSON 结构目前缺少类型层保护，后端接口改动容易直接打断前端。
- 助手层配置项已经对外暴露，但 `backend/assistant_memory.py` 中仍有部分常量硬编码，后续最好逐步收敛。
- `TODO.txt` 中关于“检索规模扩大后的效果衰减”和“基于 graph RAG 的长期记忆/用户画像”仍是值得持续推进的方向。
