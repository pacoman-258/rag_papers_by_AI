# PROJECT_LOG

本文件用于记录仓库内每一次有意义的改动，方便后续开发、回溯与交接。

## 记录规则

- 每次新增、修改、重构、修复功能后，都要追加一条日志，最新记录放在最上面。
- 每条记录至少包含：时间、摘要、涉及文件、验证方式、后续事项。
- 如果改动影响使用方式、接口协议、配置项或目录职责，除更新本文件外，也要同步更新 `AGENTS.md`、README 或示例配置。
- 纯格式化、无行为变化的小改动也建议记录，但可以写得简短。

## 记录模板

```md
## YYYY-MM-DD HH:MM

- 摘要：一句话说明本次改动。
- 涉及文件：`path/a`、`path/b`
- 验证：执行的命令、手动检查或未验证原因。
- 后续：遗留风险、待办事项，若无可写“无”。
```

## 2026-04-17 01:26

- 摘要：重构 `Paper Reader` 的可读性与结构化输出链路，前端改成“左侧阅读导航 + 中央导读卡 + 同卡双色 insight cards”，后端进一步收紧分页提示词，避免长段混合文本或 JSON 字符串直接进入页面。
- 涉及文件：`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`backend/paper_reader_service.py`、`PROJECT_LOG.md`
- 验证：执行 `cd frontend && npm run build`（通过）；执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m py_compile backend/paper_reader_service.py`（通过）
- 后续：
  1. 旧的 `Paper Reader` 会话不会自动迁移到新结构化阅读卡片，需重新载入论文后才能看到新的导读与双色 insight 布局。
  2. 当前助手仍以右侧独立栏形式存在，后续可继续收敛成浮动抽屉，以进一步释放主阅读区宽度。

## 2026-04-17 00:41

- 摘要：将论文精读分页从“每页内部重复五栏模板”改为“整篇论文先按 Core question / Method or mechanism / Evidence or experiments / Conclusion / Open questions or limitations 五个全文级阅读焦点分卷，再按预算拆页”。
- 涉及文件：`backend/paper_reader_service.py`、`PROJECT_LOG.md`
- 验证：执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m compileall backend`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `./.venv/bin/python` 伪造 chunk 验证 `_pack_chunks_into_pages` 会按全文级阅读焦点顺序建页（通过）
- 后续：
  1. 当前全文级焦点分类仍是启发式规则，后续可以结合标题层级和更细粒度语义分类继续提升边界页的准确度。
  2. 已生成的旧会话仍保留旧分页结果，需要重新载入论文才能看到新的分页结构。

## 2026-04-17 00:26

- 摘要：为论文精读页和助手层补上显式语言协议，强制精读解析与论文追问采用“英文原文 + 页面语言解读”，并让 Live2D 助手严格跟随当前页面语言回复。
- 涉及文件：`backend/schemas.py`、`backend/main.py`、`backend/paper_reader_service.py`、`backend/live2d_service.py`、`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/styles.css`
- 验证：执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m compileall backend`（通过）；执行 `cd frontend && npm run build`（通过）
- 后续：
  1. 当前已生成的 `Paper Reader` 页面内容仍沿用建会话时的语言；如果用户在会话中途切换页面语言，需要重新载入论文才能让既有页面内容整体切换。
  2. 现在的“双语格式”主要靠提示词约束加后端兜底包装；若后续要做更强展示，可以把“英文原文 / 解读”拆成前端独立字段而不是单个文本块。

## 2026-04-16 23:01

- 摘要：修复论文精读在超大 `max_context_tokens` 配置下容易整篇压成单页的问题，将分页逻辑改为“上下文窗口硬上限 + 阅读页目标预算 + chunk 目标预算”两层策略。
- 涉及文件：`backend/paper_reader_service.py`
- 验证：执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m compileall backend/paper_reader_service.py`（通过）
- 后续：
  1. 旧会话仍保留原分页结果；需要重新载入论文才能看到新的分页行为。
  2. 当前目标预算仍是固定常量，后续可以考虑把“阅读页目标长度”也开放成设置项。

## 2026-04-16 21:54

- 摘要：新增独立后端启动脚本，修复在非仓库根目录手动运行后端时可能出现的 `ModuleNotFoundError: No module named 'backend'` 问题，并让一键工作台启动复用该入口。
- 涉及文件：`scripts/start_backend.sh`、`start_backend.command`、`scripts/start_workbench.sh`、`README.md`、`README.zh-CN.md`、`AGENTS.md`
- 验证：执行 `chmod +x start_backend.command scripts/start_backend.sh`；执行 `bash -n start_backend.command scripts/start_backend.sh scripts/start_workbench.sh`（通过）
- 后续：
  1. 以后若需手动启动后端，优先使用 `./start_backend.command` 或 `./scripts/start_backend.sh`，不要在 `frontend/` 目录直接裸跑 `uvicorn backend.main:app ...`。
  2. 如需额外自定义 host/port，可通过环境变量 `BACKEND_HOST`、`BACKEND_PORT` 覆盖。

## 2026-04-16 21:46

- 摘要：新增可双击的一键启动脚本，统一拉起前后端并在服务就绪后自动打开浏览器。
- 涉及文件：`start_workbench.command`、`scripts/start_workbench.sh`、`README.md`、`README.zh-CN.md`、`AGENTS.md`
- 验证：执行 `chmod +x start_workbench.command scripts/start_workbench.sh`；执行 `bash -n start_workbench.command scripts/start_workbench.sh`（通过）
- 后续：
  1. 当前脚本面向 macOS，本地通过 `open` 打开浏览器。
  2. 如果前后端依赖尚未安装，脚本会直接报缺失项而不会自动安装。

## 2026-04-16 21:34

- 摘要：将本地开发环境中的后端默认端口从 `8000` 调整为 `9178`，同步更新前端代理与中英文文档命令示例。
- 涉及文件：`frontend/vite.config.js`、`README.md`、`README.zh-CN.md`、`AGENTS.md`
- 验证：人工核对端口相关配置与文档；未运行服务启动命令，本次修改仅涉及代理地址和说明文本
- 后续：如果本地有自定义启动脚本、IDE Run Configuration 或反向代理配置，也需要同步把后端端口改为 `9178`

## 2026-04-16 21:31

- 摘要：为搜索工作台和论文精读页新增统一的可视化流程进度面板，显示当前阶段、存活状态以及中断提示，并补充旋转加载指示。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/ProgressTracker.jsx`、`frontend/src/styles.css`
- 验证：执行 `cd frontend && npm run build`（通过）
- 后续：
  1. 当前“存活状态”主要基于前端请求与 SSE 生命周期判断，还未做更细粒度的后端 heartbeat。
  2. 如果后续要把入库流程也统一纳入这套状态组件，可以直接复用 `ProgressTracker.jsx`。

## 2026-04-16 17:38

- 摘要：落地独立的 `Paper Reader` 精读页，打通 `paper_reader_chat` 运行时配置、动态分页解析、分页流式生成、论文追问接口，以及助手层 `paper_reader` 上下文联动。
- 涉及文件：`backend/main.py`、`backend/paper_reader_service.py`、`backend/schemas.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`backend/config_store.py`、`local_paper_db/app/search_service.py`、`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`config/runtime_settings.example.json`、`requirements.txt`、`pyproject.toml`、`AGENTS.md`
- 验证：执行 `npm run build`（通过）；执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m compileall backend local_paper_db/app`（通过）
- 后续：
  1. 当前 PDF 解析基于 `pypdf` 文本抽取，不支持 OCR 或扫描版 PDF。
  2. 论文精读会话仍是进程内缓存，服务重启后会话失效。
  3. 如后续要支持从搜索结果直接跳入精读页，需要补充页面间状态跳转与入口设计。

## 2026-04-16 16:30

- 摘要：初始化项目治理文档，创建 `PROJECT_LOG.md` 与 `AGENTS.md`，并基于前端、后端、助手层三路扫描结果整理当前仓库约定。
- 涉及文件：`PROJECT_LOG.md`、`AGENTS.md`
- 验证：人工核对仓库结构、README、`backend/main.py`、`backend/config_store.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`frontend/src/App.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/styles.css`；本次未运行自动化测试，因为改动仅新增治理文档
- 后续：
  1. 后续每次代码改动都应追加日志，不要覆盖既有记录。
  2. 如果后端接口或助手协议变化，需要同步检查 `backend/schemas.py` 与前端调用是否一致。
  3. `TODO.txt` 中提到的“检索规模增长后的效果衰减”和“基于 graph RAG 的长期记忆/用户画像”仍是后续重点方向。

## 当前项目快照

- 前端：`frontend/` 为 Vite + React 18 工作台，主状态集中在 `frontend/src/App.jsx`，Live2D 助手集中在 `frontend/src/Live2DAssistant.jsx`。
- 后端：`backend/main.py` 是 FastAPI 编排入口，搜索与 trace 的核心逻辑下沉到 `local_paper_db/app/search_service.py`。
- 助手层：Live2D、TTS、长期记忆与记忆管理主要由 `backend/live2d_service.py` 和 `backend/assistant_memory.py` 提供。
- 数据与配置：本地检索依赖 PostgreSQL + `pgvector`；运行时配置通过 `config/runtime_settings.json` 落地，仓库只提交示例文件。
