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

## 2026-06-20 23:32

- 摘要：新增 `Citation Trace / 论文溯源` 实现计划，将旧 PST-lite 删除、新 `citation_trace_service`、API、前端、助手联动、测试和文档迁移拆成可执行任务。
- 涉及文件：`docs/superpowers/plans/2026-06-20-citation-trace-implementation.md`、`PROJECT_LOG.md`
- 验证：执行计划文档占位词/类型一致性自查；执行 `git diff --check -- docs/superpowers/plans/2026-06-20-citation-trace-implementation.md PROJECT_LOG.md`（通过）；未运行代码测试，因为本次仅新增实现计划文档。
- 后续：按计划选择执行模式后开始逐任务实现。

## 2026-06-20 22:58

- 摘要：记录 `Citation Trace / 论文溯源` 设计方案，明确其将彻底替代旧 PST-lite，并以证据账本、两轮引用/探索扩展和 LLM 启发价值 top5 为核心。
- 涉及文件：`docs/superpowers/specs/2026-06-20-citation-trace-design.md`、`.gitignore`、`PROJECT_LOG.md`
- 验证：执行文档自查，确认无占位项、旧 `/api/trace/*` 删除要求明确、低证据探索项最多 2 篇的约束明确；未运行代码测试，因为本次仅新增设计文档。
- 后续：按该设计进入实施计划，删除旧 PST-lite 前端/API/schema，并实现新的 `citation_trace_service` 与独立标签页。

## 2026-06-20 16:11

- 摘要：在设置页的 `paper_reader_translation` 翻译配置中新增 `Google 翻译` 模式；后端支持 `google_translate` provider 直接调用 Google Translate 进行 PDF 选区翻译，并避免该 provider 被用于非翻译模型。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`local_paper_db/app/search_service.py`、`frontend/src/App.jsx`、`tests/test_paper_reader_translation.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `test_selected_text_translation_can_use_google_translate_mode` 并先看到缺少 `google_translate_text` 适配函数的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_selected_text_translation_can_use_google_translate_mode`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py local_paper_db/app/search_service.py backend/config_store.py tests/test_paper_reader_translation.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，26 tests）；执行 `git diff --check`（通过）。
- 后续：Google 翻译模式依赖运行环境能够访问 `translate.googleapis.com`；若网络不可达，选区翻译会返回请求失败。

## 2026-06-20 16:03

- 摘要：在 `Paper Reader` 中间 PDF 原文区增加 `- / 100% / +` 缩放按钮，缩放整页 PDF 容器并同步透明文本选区层，避免放大缩小时选区坐标偏移。
- 涉及文件：`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_source_layout.py`、`PROJECT_LOG.md`
- 验证：新增 `test_frontend_pdf_reader_has_zoom_controls` 并先看到缺少 `pdfZoom`/缩放控件的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_frontend_pdf_reader_has_zoom_controls`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `git diff --check`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，25 tests）；执行 `.venv/bin/python -m py_compile backend/main.py backend/paper_reader_service.py backend/schemas.py tests/test_paper_reader_source_layout.py`（通过）。
- 后续：无。

## 2026-06-19 13:17

- 摘要：修复原生 PDF iframe 导致选中功能失效的回归；后端新增单页 PDF 暴露接口，前端改为每页原生 PDF 底图叠加透明可选文本层，使鼠标选区、右键清除、双击切换和 `t` 快捷翻译重新回到 React DOM 内工作。
- 涉及文件：`backend/main.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_source_layout.py`、`PROJECT_LOG.md`
- 验证：新增 `test_single_source_page_pdf_is_exposed_for_selectable_overlay_viewer` 与 `test_frontend_pdf_reader_keeps_selectable_page_layer` 并先看到缺少 helper/文本层的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_single_source_page_pdf_is_exposed_for_selectable_overlay_viewer tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_frontend_pdf_reader_keeps_selectable_page_layer`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m py_compile backend/main.py backend/paper_reader_service.py backend/schemas.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，24 tests）；执行 `git diff --check`（通过）；重启后端并用假 session 请求确认 `/api/paper-reader/session/{session_id}/source-pages/{page_number}/pdf` 命中业务层 404。
- 后续：单页 PDF 由浏览器 PDF 渲染，透明文本层来自 PDF 文本抽取；极复杂公式的可复制文本仍受 PDF 自身文本抽取质量影响，但视觉层不再依赖该抽取结果。

## 2026-06-19 12:49

- 摘要：将 `Paper Reader` 中间阅读区切换为浏览器原生 PDF 渲染，避免自制文本层造成水印、字号、公式和图表错位；同时停用自动精读页生成，创建会话和旧 `/stream` 兼容接口都不再调用 `paper_reader_chat` 生成结构化精读内容。
- 涉及文件：`backend/main.py`、`backend/paper_reader_service.py`、`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_source_layout.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `test_build_session_does_not_generate_deep_reading_page` 并先看到 `_generate_page_content_internal` 被调用的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_build_session_does_not_generate_deep_reading_page tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_session_pdf_path_is_exposed_for_native_pdf_rendering`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，22 tests）；执行 `git diff --check`（通过）。
- 后续：已重启本地后端并用假 session 请求确认 `/api/paper-reader/session/{session_id}/pdf` 路由命中业务层 404；前端 dev server 仍在 `http://127.0.0.1:5173/` 监听。

## 2026-06-19 12:28

- 摘要：修复 `Paper Reader` PDF 原文页显示过度挤压的问题，后端为源页返回 PDF 坐标、字号和字体粗细的 layout spans，前端改用 SVG 按原始版心渲染文本。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_source_layout.py`、`PROJECT_LOG.md`
- 验证：新增 `test_pdf_source_layout_preserves_positions_and_font_weight` 并先看到缺少 layout 提取函数的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，20 tests）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `git diff --check`（通过）。
- 后续：当前方案用 PDF 文本坐标渲染正文和标题，能保留段落、字号和粗体；暂不栅格化图片/图表，后续若要完全像 Chrome PDF Viewer 一样显示图像，需要引入 Poppler/PyMuPDF 或前端 PDF.js。

## 2026-06-18 11:47

- 摘要：重设计 `Paper Reader` 中间阅读区为 PDF 原文页阅读面，移除中间原文/解读卡片流；新增持久原文选区与右侧选区翻译卡，按 `paper_reader_translation` 配置只翻译选中文本。
- 涉及文件：`backend/schemas.py`、`backend/main.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_translation.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `test_selected_text_translation_uses_translation_config_only` 并先看到缺少 schema 的失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_selected_text_translation_uses_translation_config_only`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，19 tests）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `git diff --check`（通过）。
- 后续：当前已运行的后端进程需要重载后才会暴露 `/source` 和 `/translate-selection` 新接口；建议在真实 PDF 会话里人工检查浏览器原文选区高亮与 `t` 快捷翻译体验。

## 2026-06-17 11:06

- 摘要：修复旧配置中缺少 `paper_reader_translation` 时原文卡片翻译仍回退到默认本地模型的问题；现在未显式配置翻译模型时会继承当前保存的 `paper_reader_chat` provider/model/base_url/key，避免页面卡片解读持续为空。
- 涉及文件：`backend/config_store.py`、`tests/test_paper_reader_translation.py`、`PROJECT_LOG.md`
- 验证：用本地 `config/runtime_settings.json` 安全检查确认原始配置缺少 `paper_reader_translation` 且精读模型为 `openai_compatible / gemini-3.1-pro-preview`；新增回归测试 `test_missing_translation_config_inherits_saved_paper_reader_chat` 并先看到失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_missing_translation_config_inherits_saved_paper_reader_chat`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，18 tests）；执行 `.venv/bin/python -m py_compile backend/config_store.py backend/paper_reader_service.py backend/main.py backend/schemas.py local_paper_db/app/search_service.py tests/test_paper_reader_translation.py`（通过）；执行 `cd frontend && npm run build`（通过）；再次调用 `load_runtime_settings()` 确认 `paper_reader_translation` 加载为 `openai_compatible / gemini-3.1-pro-preview` 且 `has_api_key=True`。
- 后续：当前浏览器里已经缓存的旧 Paper Reader 页面不会自动补翻译；需要后端重载后重新生成当前页或重新载入论文。

## 2026-06-15 14:31

- 摘要：为 `Paper Reader` 原文卡片新增独立的 `paper_reader_translation` 翻译配置，主精读模型不再负责 `reading_blocks` 翻译；页面生成后由翻译模型按 `chunk_id` 补齐缺失卡片解读，翻译失败时主精读页继续降级显示占位。
- 涉及文件：`backend/schemas.py`、`backend/config_store.py`、`backend/main.py`、`backend/paper_reader_service.py`、`local_paper_db/app/search_service.py`、`frontend/src/App.jsx`、`config/runtime_settings.example.json`、`README.md`、`README.zh-CN.md`、`tests/test_paper_reader_translation.py`、`tests/test_paper_reader_index.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation`（先失败后通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation tests.test_paper_reader_index tests.test_paper_reader_discipline`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，17 tests）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/config_store.py backend/main.py backend/paper_reader_service.py local_paper_db/app/search_service.py tests/test_paper_reader_translation.py tests/test_paper_reader_index.py`（通过）；执行 `cd frontend && npm run build`（通过）；启动 Vite dev server 并用浏览器打开 `http://127.0.0.1:5174/`，确认设置页出现独立的“原文卡片翻译模型”配置卡片。
- 后续：旧的进程内 Paper Reader 页面缓存不会自动补翻译；需要刷新服务或重新载入/重新生成论文页后才会走新的翻译配置。

## 2026-06-12 12:15

- 摘要：修复 `Paper Reader` 阅读块解读与原文不对应的问题，移除按章节或整页 overview 复用解读的兜底逻辑，仅允许明确 `chunk_id` 对齐的 insight 补齐阅读块，并强化模型提示词要求逐块解释精确对应原文。
- 涉及文件：`backend/paper_reader_service.py`、`tests/test_paper_reader_index.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_index.PaperReaderIndexTreeTest.test_page_model_does_not_reuse_page_or_section_summary_for_reading_blocks`（先失败后通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_index tests.test_paper_reader_discipline`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/live2d_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）。
- 后续：已缓存的旧页面内容可能仍显示错配解读，需要刷新/重新生成当前页以获取新的逐块解读。

## 2026-06-12 10:19

- 摘要：调整 `Paper Reader` 与 Live2D 助手的联动方式，精读页仅静默更新当前页论文上下文，不再在每页生成/切换时触发助手自动总结回复；助手仍可在用户主动提问时参考当前页原文与结构化上下文。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`tests/test_paper_reader_live2d_behavior.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_live2d_behavior`（先失败后通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile tests/test_paper_reader_live2d_behavior.py`（通过）；执行 `cd frontend && npm run build`（通过）。
- 后续：真实浏览器会话中建议刷新前端后确认 Live2D 不再追加“已根据最新回答自动补充建议”的每页自动消息。

## 2026-06-11 23:52

- 摘要：修复 `Paper Reader` 三栏页中阅读块“页面语言解读”误显示英文原文的问题，收紧 `reading_blocks` 生成契约，并在序列化时用同 chunk 的 insight 解读补齐缺失翻译。
- 涉及文件：`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`tests/test_paper_reader_index.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_index.PaperReaderIndexTreeTest.test_page_model_does_not_use_original_as_reading_block_translation`（先失败后通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_index tests.test_paper_reader_discipline`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/live2d_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）。
- 后续：旧会话若已在前端缓存了页面内容，可能需要刷新页面或重新生成当前页后才能看到逐块解读更新。

## 2026-06-11 22:12

- 摘要：修复设置页拉取模型后原生 `datalist` 展开不可靠的问题，为模型输入框新增显式“展开/收起模型列表”按钮和可点击候选列表。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/styles.css`、`PROJECT_LOG.md`
- 验证：执行 `cd frontend && npm run build`（通过）。
- 后续：无。

## 2026-06-11 16:39

- 摘要：重设计 `Paper Reader` 为左侧固定 Live2D 助手、中间原文/页面语言解读、右侧学科卡片三栏布局；新增 `reading_blocks` 页面接口字段，并移除前端底部 Paper Reader 独立追问入口，改由 Live2D 注入当前页原文上下文承接追问。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_index.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_index tests.test_paper_reader_discipline`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/live2d_service.py backend/main.py`（通过）；执行 `cd frontend && npm run build`（通过）。
- 后续：仍建议在真实 Paper Reader 会话中人工检查右侧卡片到原文块的 hover 高亮是否符合阅读预期，尤其是模型未返回逐块 explanation 时的兜底体验。

## 2026-06-10 11:45

- 摘要：为 `Paper Reader` 新增学科自适应精读链路，支持自动/手动学科选择、学科专属分页阅读路线、`discipline_guide` 讲解面板、学科化追问提示词，并同步 Live2D/长期记忆上下文。
- 涉及文件：`backend/schemas.py`、`backend/main.py`、`backend/paper_reader_service.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_discipline.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_discipline tests.test_paper_reader_index`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/live2d_service.py backend/assistant_memory.py`（通过）；执行 `cd frontend && npm run build`（通过）。
- 后续：旧的进程内 `Paper Reader` 会话不会迁移到新的学科路线；切换学科需要重新载入论文生成新会话。

## 2026-06-06 20:34

- 摘要：收敛 `Paper Reader` 已载入论文后的前端布局，隐藏非主链路助手栏、折叠二次导入表单、拓宽精读正文区，并将导师讲解、洞察卡与黑板/术语/检查点整理为更清晰的阅读分区。
- 涉及文件：`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`PROJECT_LOG.md`
- 验证：执行 `cd frontend && npm run build`（通过）；使用 Chrome 导入 `Attention Is All You Need` 的 arXiv `1706.03762` 真实会话（通过）；使用 mock `Attention Is All You Need` session 做桌面与移动端截图检查，确认无横向溢出、导入抽屉闭合、助手栏不再占用主阅读宽度；当前 Chrome 页指标显示阅读卡宽度约 1106px、`scrollWidth == innerWidth`。
- 后续：本机 `Downloads` 目录被 macOS 权限拦截，未能直接读取用户下载好的 PDF 文件路径；建议用户在页面文件选择器中手动选择该 PDF 再做一次最终人工验收。

## 2026-06-06 19:51

- 摘要：修复 SOCKS 代理环境下 `httpx` 缺少 `socksio` 导致 OpenAI/httpx 客户端初始化失败的问题，显式声明并安装 `httpx[socks]`。
- 涉及文件：`pyproject.toml`、`requirements.txt`、`uv.lock`、`tests/test_dependency_declarations.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_dependency_declarations tests.test_paper_reader_index`（通过）；执行 `.venv/bin/python -c "import socksio, httpx; client = httpx.Client(proxy='socks5://127.0.0.1:9999'); client.close(); print('socks proxy support ok')"`（通过）；执行 `uv lock` 并用 `uv pip install "httpx[socks]" --python .venv/bin/python` 更新当前虚拟环境（通过）。
- 后续：无。

## 2026-06-06 14:32

- 摘要：重构 `Paper Reader` 的第一层学习形态，新增 Paper Map 结构树、阅读页到证据节点的映射、论文追问的 selected nodes 返回，并在前端左侧导航展示本地化论文地图与整洁的证据节点信息。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`README.md`、`README.zh-CN.md`、`tests/test_paper_reader_index.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_paper_reader_index`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache .venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py`（通过）；执行 `cd frontend && npm run build`（通过）；使用 mock Paper Reader 会话进行 headless Chrome 截图检查，确认中文阅读焦点本地化且页面无横向溢出。
- 后续：真实 PDF/arXiv 端到端仍需用实际论文人工验收地图节点质量；当前结构树仍基于文本抽取和标题启发式，尚未引入图表/公式/版面级 Paper IR。

## 2026-04-29 10:21

- 摘要：产品化打磨 `Paper Reader` 精读页，后端扩展 insight 的 `why_it_matters` 结构化字段与兼容解析，前端改为默认页面语言解读 + 可展开英文原文、独立 Why callout、metadata 化证据/来源、页内 scrollspy 子锚点、顶部紧凑翻页与键盘左右翻页。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`PROJECT_LOG.md`
- 验证：执行 `cd frontend && npm run build`（通过）；执行 `PYTHONPYCACHEPREFIX=/private/tmp/rag-paper-reader-pycache python3 -m py_compile backend/schemas.py backend/paper_reader_service.py`（通过）
- 后续：真实论文端到端体验仍建议用已有 arXiv/PDF 样例人工检查 scrollspy 锚点、Why callout 内容质量与模型新字段输出稳定性。

## 2026-04-28 00:00

- 摘要：参考 Paper2Gal 的教学结构，为 `Paper Reader` 新增默认 guided 陪读模式、Quick Story 速读页、导师讲解流、黑板笔记、术语降维、阅读提示、理解检查点、研究笔记导出，并在搜索结果卡加入“精读这篇”入口。
- 涉及文件：`backend/schemas.py`、`backend/main.py`、`backend/paper_reader_service.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`
- 验证：执行 `PYTHONPYCACHEPREFIX=/tmp/pythoncache python3 -m compileall backend`（通过）；执行 `cd frontend && npm run build`（通过）
- 后续：
  1. Quick Story 和 guided 阅读结构依赖模型结构化输出，真实论文端到端体验仍需用 arXiv/PDF 做人工验收。
  2. 当前研究笔记导出基于已生成页面内容，尚未生成的分页不会自动补齐到导出文件。

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
