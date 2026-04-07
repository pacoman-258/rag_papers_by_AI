## arxiv-paper-rag

这是一个面向 arXiv 论文的本地实验项目，用于抓取论文、写入 PostgreSQL + pgvector，并通过命令行或 Web 工作台完成 RAG 检索与问答。

英文文档见：[README.md](README.md)

## 仓库内容

- `ArXiv_craw/crawer.py`
  搜索 arXiv、下载 PDF，并写入元数据 JSONL。
- `local_paper_db/app/in.py`
  使用 Ollama 生成摘要向量，并写入 PostgreSQL + pgvector。
- `local_paper_db/app/search.py`
  搜索链路的命令行入口。
- `local_paper_db/app/search_service.py`
  可复用的搜索服务层，供 CLI 和 FastAPI 共用。
- `backend/main.py`
  FastAPI 后端，负责配置管理、搜索 API、SSE 回答流和入库任务管理。
- `frontend/`
  React + Vite 前端工作台。

## 搜索链路

当前搜索流程如下：

1. 用户输入问题。
2. `QUERY_CHAT_*` 先将问题改写为英文检索计划。
3. 用户确认是否使用改写结果、继续优化，或直接使用原句。
4. Ollama 为最终确认的检索文本生成 embedding。
5. PostgreSQL + pgvector 粗排取前 `50` 篇论文。
6. SiliconFlow 使用 `BAAI/bge-reranker-v2-m3` 对结果重排，保留前 `10` 篇。
7. `ANSWER_CHAT_*` 仅基于这 10 篇论文生成最终回答。

降级策略：

- rewrite 失败时，直接回退到原始问题。
- rerank 失败时，直接使用粗排前 10 篇继续回答。

## Web 工作台

FastAPI + React 工作台包含两个主区域：

- `Search Workspace`
  可配置 query chat、answer chat、rerank、embedding 和 retrieval 参数，并完成 rewrite 确认、论文结果查看和最终回答流式展示。
- `Ingest Manager`
  可在前端启动 `in.py` 入库任务、查看数据库概览，并通过 SSE 查看实时日志。

前端支持中英文界面切换，并会在浏览器中记住上一次选择的界面语言。

配置优先级：

1. 前端当前请求携带的设置
2. `config/runtime_settings.json`
3. 环境变量默认值

前端不会回显明文 API Key，后端只返回 `has_api_key: true/false`。  
出于安全考虑，仓库只提交 [`config/runtime_settings.example.json`](config/runtime_settings.example.json)，真实的 `config/runtime_settings.json` 应保留在本地。

## 目录结构

```text
.
|-- ArXiv_craw/
|   |-- crawer.py
|   `-- arxiv_papers_rag/
|-- backend/
|   |-- config_store.py
|   |-- ingest_manager.py
|   |-- main.py
|   `-- schemas.py
|-- config/
|   `-- runtime_settings.json
|-- frontend/
|   |-- package.json
|   |-- src/
|   `-- vite.config.js
|-- local_paper_db/
|   `-- app/
|       |-- in.py
|       |-- search.py
|       `-- search_service.py
|-- pyproject.toml
|-- requirements.txt
|-- README.md
`-- README.zh-CN.md
```

## 环境要求

- Python `3.13`
- Node.js `20+`
- 已安装 `pgvector` 的 PostgreSQL
- 运行中的 Ollama，默认地址 `http://localhost:11434`
- 一个与 `OLLAMA_EMBED_MODEL` 对应的 embedding 模型
- 可选：本地 Ollama chat 模型
- 若要使用 API rerank：SiliconFlow API Key
- 若要使用远程 chat model：OpenAI-compatible API 凭证

## 安装

### Python 依赖

```bash
python -m venv .venv
```

激活虚拟环境：

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows cmd.exe
.venv\Scripts\activate.bat
```

然后安装依赖：

```bash
pip install -r requirements.txt
```

### 前端依赖

```bash
cd frontend
npm install
```

## 数据库准备

入库脚本会自动建表，但 PostgreSQL 仍需要先启用扩展：

```sql
CREATE DATABASE pacoman;
\c pacoman
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

默认连接参数：

- 数据库：`pacoman`
- 主机：`localhost`
- 端口：`5433`

如有需要，可通过 `PAPER_DB_*` 环境变量覆盖。

## 环境变量

### 数据库与 embedding

- `PAPER_DB_NAME`
- `PAPER_DB_USER`
- `PAPER_DB_PASSWORD`
- `PAPER_DB_HOST`
- `PAPER_DB_PORT`
- `OLLAMA_API_URL`
- `OLLAMA_EMBED_MODEL`

### Query rewrite 模型

- `QUERY_CHAT_PROVIDER`
  可选：`ollama`、`openai_compatible`
- `QUERY_CHAT_MODEL`
- `QUERY_CHAT_BASE_URL`
- `QUERY_CHAT_API_KEY`

### 最终回答模型

- `ANSWER_CHAT_PROVIDER`
  可选：`ollama`、`openai_compatible`
- `ANSWER_CHAT_MODEL`
- `ANSWER_CHAT_BASE_URL`
- `ANSWER_CHAT_API_KEY`

### Rerank API

- `RERANK_API_KEY`
- `RERANK_BASE_URL`
  默认：`https://api.siliconflow.cn/v1`
- `RERANK_MODEL`
  默认：`BAAI/bge-reranker-v2-m3`

## 使用方式

### 1. 抓取论文

```bash
cd ArXiv_craw
python crawer.py
```

### 2. 写入 PostgreSQL

```bash
cd local_paper_db/app
python in.py
```

### 3. 命令行搜索

交互模式：

```bash
cd local_paper_db/app
python search.py
```

单次问题模式：

```bash
cd local_paper_db/app
python search.py "RAG 是什么？"
```

两种模式都会进入 rewrite 确认环节，你可以：

1. 使用优化后的查询
2. 告诉模型哪里还要改进
3. 直接使用原句查询

### 4. 启动 FastAPI 后端

```bash
uvicorn backend.main:app --reload
```

### 5. 启动 React 前端

```bash
cd frontend
npm run dev
```

开发环境默认地址：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`

### 6. 构建前端静态文件

```bash
cd frontend
npm run build
```

如果 `frontend/dist` 存在，FastAPI 会自动托管构建后的 SPA。

## macOS 说明

- 代码主体已经基本跨平台，真正依赖平台的是 PostgreSQL + `pgvector`、Ollama、Python 和 Node.js 的本地安装。
- 新版抓取脚本会把 `pdf_local_path` 统一写成使用 `/` 分隔符的可移植路径，便于在 macOS、Linux 和 Windows 之间共享元数据。
- 入库时会自动把旧 metadata 中的 Windows 风格 `\` 路径规范化后再写入 PostgreSQL。
- 如果你要把现有 Windows 数据迁到 macOS，建议至少重新执行一次 metadata 入库，这样数据库中的本地路径会被清洗成统一格式。

## Provider 说明

- embedding 仍然固定使用 Ollama。
- query rewrite 可以使用 Ollama，也可以使用任意 OpenAI-compatible API。
- 最终回答可以使用 Ollama，也可以使用任意 OpenAI-compatible API。
- rerank 不再依赖本地 `FlagEmbedding`，而是改为 SiliconFlow rerank API。

## 主要入口

- [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py)
- [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
- [`backend/main.py`](backend/main.py)
