## arxiv-paper-rag

这是一个面向 arXiv 论文的本地 RAG 实验项目，当前由两部分脚本组成：

- `ArXiv_craw/crawer.py`：按固定关键词搜索 arXiv，下载 PDF，并把论文元数据写入 JSONL。
- `local_paper_db/app/in.py` 与 `local_paper_db/app/search.py`：把元数据写入 PostgreSQL + `pgvector`，再通过召回、重排和 Ollama 生成回答。

英文文档见：[README.md](README.md)

## 项目能力

这个项目实现了一条比较直接的本地论文助手流程：

1. 用固定关键词搜索 arXiv。
2. 下载匹配论文的 PDF。
3. 保存标题、作者、摘要、本地 PDF 路径和 arXiv URL 等元数据。
4. 通过 Ollama 生成向量并写入 PostgreSQL/pgvector。
5. 用向量检索召回相关论文。
6. 使用 `BAAI/bge-reranker-v2-m3` 对候选结果重排。
7. 调用 Ollama 聊天模型，基于召回论文摘要生成答案。

## 目录结构

```text
.
|-- ArXiv_craw/
|   |-- crawer.py
|   |-- pyproject.toml
|   `-- arxiv_papers_rag/        # 本地 PDF 和元数据输出，属于生成数据
|-- local_paper_db/
|   `-- app/
|       |-- in.py                # 入库脚本
|       |-- search.py            # 本地 RAG 检索命令行
|       |-- metadata_log.jsonl   # 示例/生成元数据
|       `-- ingest_error.log
|-- requirements.txt
|-- pyproject.toml
|-- README.md
`-- README.zh-CN.md
```

## 流程结构

```text
arXiv API
  -> crawer.py
  -> metadata_log.jsonl + PDFs
  -> in.py
  -> PostgreSQL + pgvector
  -> search.py
  -> reranker + Ollama
  -> 最终回答
```

## 环境要求

- Python `3.13`
- 已安装并启用 `pgvector` 扩展的 PostgreSQL
- 本地可访问的 Ollama 服务，地址默认为 `http://localhost:11434`
- 与脚本中硬编码名称一致的 Ollama 模型：
  - [`local_paper_db/app/in.py`](local_paper_db/app/in.py) 中使用 `qwen3-embedding:0.6b`
  - [`local_paper_db/app/search.py`](local_paper_db/app/search.py) 中使用 `qwen3-embedding` 和 `qwen3:0.6b`
- 足够的磁盘空间用于保存 PDF
- 可选但推荐：GPU，用于重排模型和 Ollama 推理

## 安装

建议使用虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

如果 `FlagEmbedding` 在你的环境里没有自动安装兼容版本的 `torch`，先手动安装对应的 `torch`，再执行上面的依赖安装。

## 数据库准备

入库脚本会自动建表，但数据库本身仍然需要准备好扩展。尤其是：

- `vector`
- `gen_random_uuid()` 所依赖的扩展能力，通常可通过 `pgcrypto` 提供

示例：

```sql
CREATE DATABASE paper_db;
\c paper_db
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

需要特别注意：当前两个脚本的数据库配置并不一致，不能直接无修改运行。

- [`local_paper_db/app/in.py`](local_paper_db/app/in.py) 默认连 `pacoman:5433`
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py) 默认连 `paper_db:5432`

实际使用前，需要先把它们改成同一个 PostgreSQL 实例。

## 使用方式

### 1. 抓取 arXiv 论文

抓取器在 [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py) 里写死了以下参数：

- 关键词：`Retrieval Augmented Generation`
- 分类：`cs.CL`
- 最大结果数：`100`

运行：

```bash
cd ArXiv_craw
python crawer.py
```

输出：

- PDF 保存在 `ArXiv_craw/arxiv_papers_rag/`
- 元数据保存在 `ArXiv_craw/arxiv_papers_rag/metadata_log.jsonl`

### 2. 将元数据写入 PostgreSQL

入库脚本默认从当前工作目录读取 `metadata_log.jsonl`。仓库里现在也放着一份 `local_paper_db/app/metadata_log.jsonl` 作为现有生成结果。

如果你刚重新抓取过新数据，需要手动复制该 JSONL 文件，或者直接修改脚本里的 `METADATA_FILE`。

运行：

```bash
cd local_paper_db/app
python in.py
```

脚本会：

- 动态检测 Ollama 向量维度
- 创建 `papers_meta` 和 `papers_embeddings`
- 自动跳过已存在的 `arxiv_id`
- 以批量方式写入 PostgreSQL

### 3. 查询本地 RAG 系统

运行：

```bash
cd local_paper_db/app
python search.py
```

然后在终端输入研究问题。脚本会：

- 用 Ollama 生成查询向量
- 从 PostgreSQL 召回前 `50` 条候选
- 经过重排后保留前 `5` 条
- 通过 Ollama 流式输出最终答案

输入 `q` 退出。

## 当前本地数据情况

当前工作区里已经存在：

- `100` 篇 PDF，位于 `ArXiv_craw/arxiv_papers_rag/`
- `99` 条元数据，位于 `local_paper_db/app/metadata_log.jsonl`

这些文件都属于生成产物，默认不建议推送到 GitHub。

## 已知限制

- 配置全部硬编码在 Python 文件中。
- 抓取、入库、检索三部分没有统一配置源。
- `search.py` 查询的是 `summary_for_embedding`、`methodology` 等字段，而抓取器当前产出的主要是 `summary`。如果直接使用现有抓取结果，可能需要修改 SQL 或补充元数据字段。
- 当前没有 Web UI、API 服务或自动化测试。
- 这个仓库更适合本地实验，不是生产级实现。

## 后续可改进方向

- 用环境变量统一管理数据库和模型配置。
- 统一 crawl、ingest、search 的元数据结构。
- 增加 PostgreSQL/pgvector 初始化脚本。
- 增加入库和检索的测试。
- 提供可复现 demo 用的小样本数据。

## 校验情况

以下脚本已经在本地完成 Python 语法校验：

- [`ArXiv_craw/crawer.py`](ArXiv_craw/crawer.py)
- [`local_paper_db/app/in.py`](local_paper_db/app/in.py)
- [`local_paper_db/app/search.py`](local_paper_db/app/search.py)
