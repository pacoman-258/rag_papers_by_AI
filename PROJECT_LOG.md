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

## 2026-06-27 11:12

- 摘要：修复研究画像刷新拿不到最新论文精读上下文的问题；画像页刷新请求现在会携带当前同步给小助手的 `workflow_context`，后端将其纳入本次画像提取，同时画像页沿用持久化的小助手会话 ID 更新函数。
- 涉及文件：`backend/assistant_memory.py`、`backend/live2d_service.py`、`backend/main.py`、`backend/schemas.py`、`frontend/src/App.jsx`、`frontend/src/ResearchProfilePage.jsx`、`tests/test_assistant_research_profile.py`、`tests/test_research_profile_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_research_profile_frontend.ResearchProfileFrontendTest.test_research_profile_refresh_sends_latest_assistant_workflow_context` 与 `.venv/bin/python -m unittest tests.test_assistant_research_profile.AssistantResearchProfileTest.test_research_profile_refresh_request_accepts_workflow_context`，确认前后端缺少 `workflow_context` 的红灯；实现后执行 `.venv/bin/python -m unittest tests.test_assistant_research_profile tests.test_research_profile_frontend`（10 tests OK）、`.venv/bin/python -m py_compile backend/assistant_memory.py backend/live2d_service.py backend/main.py backend/schemas.py tests/test_assistant_research_profile.py tests/test_research_profile_frontend.py`（通过）。
- 后续：自动画像仍不会在每次论文精读追问后立即更新；用户点击“刷新画像”时会使用最近同步到小助手的精读上下文，长期可考虑增加显式“记录到画像”按钮或后台节流刷新。

## 2026-06-27 10:37

- 摘要：将引用溯源第二步接入 `citation_trace_worker_chat` 副模型，由副模型从 References 原文结构化解析参考文献；规则解析保留为兜底，并在候选召回前过滤明显的 prompt/rubric 脏片段，避免不同引用格式导致误查 arXiv。
- 涉及文件：`backend/citation_trace_service.py`、`tests/test_citation_trace_service.py`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_citation_trace_service.CitationTraceServiceTest.test_worker_reference_resolution_replaces_polluted_rule_parse`，确认缺少副模型解析入口的红灯；实现后执行该测试（通过）、`.venv/bin/python -m unittest tests.test_citation_trace_service`（31 tests OK）、`.venv/bin/python -m unittest tests.test_citation_trace_api tests.test_citation_trace_cleanup`（12 tests OK）、`.venv/bin/python -m py_compile backend/citation_trace_service.py tests/test_citation_trace_service.py`（通过）。
- 后续：副模型解析当前一次最多接收 References 前 50000 字符、采纳前 200 条结构化引用；如果后续遇到超长 bibliography，可再做分块解析与合并。

## 2026-06-26 22:48

- 摘要：将工作台品牌展示从 arxiv-paper-rag 调整为 Iplatform，顶部副标题改为 `design by pacoman-258`，页面底部新增远端仓库与作者 GitHub 链接，并同步 README、包名和浏览器标题中的项目名。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/styles.css`、`frontend/package.json`、`frontend/package-lock.json`、`README.md`、`README.zh-CN.md`、`pyproject.toml`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest discover -s tests`（139 tests OK，含既有 research profile 降级日志输出）、`.venv/bin/python -m py_compile backend/main.py backend/schemas.py local_paper_db/app/search_service.py local_paper_db/app/external_sources.py tests/test_search_relevance_review.py tests/test_fuzzy_arxiv_search.py tests/test_paper_reader_persistence_frontend.py tests/test_research_topics_frontend.py`（通过）、`npm run build`（在 `frontend/` 下通过）、`git diff --check`（通过）。
- 后续：远端 GitHub 仓库将在本次提交前后重命名为 `Iplatform`，并更新本地 `origin` 地址。

## 2026-06-26 22:22

- 摘要：在搜索执行完成检索与重排后、回答流生成前新增 Top3 简介复审环节；若复审模型判断重排前三明显偏离用户原始要求，会重写检索方案并重新检索，最多重复 3 次，复审失败时沿用当前结果并返回 warning。
- 涉及文件：`local_paper_db/app/search_service.py`、`backend/main.py`、`tests/test_search_relevance_review.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_search_relevance_review`，确认 `build_search_review_messages` 与 `execute_search_with_review` 缺失红灯；实现后执行 `.venv/bin/python -m unittest tests.test_search_relevance_review`（5 tests OK）、`.venv/bin/python -m py_compile local_paper_db/app/search_service.py backend/main.py tests/test_search_relevance_review.py`（通过）、`.venv/bin/python -m unittest tests.test_search_relevance_review tests.test_fuzzy_arxiv_search tests.test_arxiv_reliability tests.test_assistant_chat_config tests.test_citation_trace_api`（28 tests OK）、`.venv/bin/python -m unittest discover -s tests`（139 tests OK，含既有 research profile 降级日志输出）、`git diff --check -- local_paper_db/app/search_service.py backend/main.py tests/test_search_relevance_review.py README.md README.zh-CN.md PROJECT_LOG.md`（通过）。
- 后续：复审当前只使用重排前三的标题、分类、日期、摘要和方法简介；如需要更细粒度判断，可再接入引用证据或全文片段，但要控制模型调用成本。

## 2026-06-26 22:08

- 摘要：修复采纳搜索建议后课题页仍为空的问题；小助手采纳 `open_in_topic` 建议后会创建课题、挂接论文精读线程，并把线程上下文传入 Paper Reader 继续记录阅读进度。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/PaperReaderPage.jsx`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_accepting_search_suggestion_starts_topic_thread`，确认缺少采纳后启动课题线程的红灯；实现后执行该测试（通过）、`.venv/bin/python -m unittest tests.test_research_topics_frontend tests.test_research_topics_api tests.test_research_topics_service tests.test_paper_reader_persistence_frontend`（29 tests OK）、`.venv/bin/python -m py_compile backend/main.py backend/research_topics_service.py backend/schemas.py tests/test_research_topics_frontend.py`（通过）、`git diff --check -- frontend/src/App.jsx frontend/src/Live2DAssistant.jsx frontend/src/PaperReaderPage.jsx tests/test_research_topics_frontend.py`（通过）、`npm run build`（在 `frontend/` 下通过）。
- 后续：若后续要减少重复课题，可让建议卡携带并优先复用已有 `topic_id`；当前修复先保证用户采纳后课题页能立刻出现记录。

## 2026-06-26 18:25

- 摘要：修复论文精读在切到其他卡片/标签后返回丢失的问题；`PaperReaderPage` 改为常驻挂载并用 `hidden` 控制显示，隐藏时不渲染小助手实例且停用精读快捷键，同时新增显式“结束阅读”按钮作为用户主动清空阅读状态的入口。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/PaperReaderPage.jsx`、`tests/test_paper_reader_persistence_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_paper_reader_persistence_frontend`，确认 App 条件卸载 PaperReader、缺少结束阅读入口、隐藏状态仍可能挂载助手/快捷键和同 URL 复载保护缺失的红灯；实现后执行 `.venv/bin/python -m unittest tests.test_paper_reader_persistence_frontend`（4 tests OK）、`.venv/bin/python -m unittest tests.test_paper_reader_persistence_frontend tests.test_paper_reader_source_layout tests.test_paper_reader_live2d_behavior tests.test_research_topics_frontend tests.test_global_selection_translation_frontend`（23 tests OK）、`npm run build -- --outDir /private/tmp/rag-papers-by-ai-codex-paper-reader-persist-dist --emptyOutDir`（在 `frontend/` 下通过）。
- 后续：如需跨浏览器刷新后也恢复精读，可再把当前 session id 持久化到 localStorage；本次只修复应用内切换不应自动丢状态。

## 2026-06-26 16:47

- 摘要：为模糊学习型检索新增轻量 `search_intent`，对入门、从头学习和权威论文请求启用 arXiv 多路意图查询与粗排加权，同时保持普通检索、latest 时间窗、provider 降级和 rerank fallback 原链路。
- 涉及文件：`local_paper_db/app/search_service.py`、`local_paper_db/app/external_sources.py`、`backend/schemas.py`、`backend/main.py`、`tests/test_fuzzy_arxiv_search.py`、`README.md`、`README.zh-CN.md`、`docs/superpowers/plans/2026-06-26-fuzzy-arxiv-search.md`、`PROJECT_LOG.md`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search.FuzzyArxivSearchTest.test_coerce_query_plan_detects_beginner_intent_when_model_omits_it`，确认 `search_intent` 缺失红灯；再执行 arXiv 多路查询、beginner 排序和嵌套 `search_intent` 兼容测试，确认新函数缺失、旧相似度排序和旧 payload 兼容红灯；实现后执行 `.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search`（9 tests OK）、`.venv/bin/python -m unittest tests.test_fuzzy_arxiv_search tests.test_arxiv_reliability`（12 tests OK）、`.venv/bin/python -m py_compile local_paper_db/app/search_service.py local_paper_db/app/external_sources.py backend/main.py backend/schemas.py tests/test_fuzzy_arxiv_search.py`（通过）、`.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api`（37 tests OK）、`.venv/bin/python -m unittest tests.test_assistant_chat_config tests.test_research_topics_api tests.test_research_topics_service`（23 tests OK）、`.venv/bin/python -m unittest discover -s tests`（129 tests OK，含既有 research profile 降级日志输出）、`git diff --check -- local_paper_db/app/search_service.py local_paper_db/app/external_sources.py backend/main.py backend/schemas.py README.md README.zh-CN.md PROJECT_LOG.md`（通过）。
- 后续：权威度仍主要来自 arXiv 元数据和轻量词法信号；若后续要更稳，可接入 Citation Trace / WOS 引用信号做 evidence-backed canonical ranking。

## 2026-06-26 11:13

- 摘要：为小助手增加不打断式建议卡托盘；搜索完成会静默生成论文打开到课题的建议，精读问题可生成开放问题建议，溯源完成后刷新建议卡状态。
- 涉及文件：`backend/main.py`、`backend/schemas.py`、`frontend/src/App.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/CitationTracePage.jsx`、`frontend/src/styles.css`、`tests/test_research_topics_api.py`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api.ResearchTopicsApiTest.test_thread_open_question_suggestion_route_records_on_accept`（确认路由 404 红灯）和 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_assistant_has_quiet_suggestion_tray tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_workflows_refresh_quiet_suggestion_cards`（确认前端接线缺失红灯）；实现后执行上述测试（通过）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api tests.test_research_topics_service tests.test_research_topics_frontend`（通过，24 tests）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m py_compile backend/main.py backend/schemas.py tests/test_research_topics_api.py`（通过）、`npm run build -- --outDir /private/tmp/rag-papers-by-ai-codex-research-topics-assistant-dist --emptyOutDir`（在 `frontend/` 下通过，使用临时 `node_modules` 符号链接，已清理）、`git diff --check -- backend/main.py backend/schemas.py frontend/src/App.jsx frontend/src/CitationTracePage.jsx frontend/src/Live2DAssistant.jsx frontend/src/PaperReaderPage.jsx frontend/src/styles.css tests/test_research_topics_api.py tests/test_research_topics_frontend.py`（通过）。
- 后续：真实浏览器里还需观察建议卡数量和重复策略；当前搜索每次完成会为 Top3 候选生成待处理建议。

## 2026-06-26 11:05

- 摘要：新增前端课题档案页，App 顶部导航增加课题入口，并在设置页为小助手暴露独立 `assistant_chat` 模型/API 配置。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/ResearchTopicsPage.jsx`、`frontend/src/styles.css`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_app_exposes_research_topics_tab_and_assistant_chat_settings`，确认 App 缺少课题页入口和小助手配置的红灯；实现后执行该测试（通过）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend`（通过，3 tests）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend tests.test_citation_trace_frontend tests.test_research_profile_frontend`（通过，7 tests）、`npm run build -- --outDir /private/tmp/rag-papers-by-ai-codex-research-topics-assistant-dist --emptyOutDir`（在 `frontend/` 下通过，使用临时 `node_modules` 符号链接，已清理）、`git diff --check -- frontend/src/App.jsx frontend/src/ResearchTopicsPage.jsx frontend/src/styles.css tests/test_research_topics_frontend.py`（通过）。
- 后续：继续把不打断式建议卡接到小助手层，让搜索、精读、溯源阶段建议可以静默生成并待用户处理。

## 2026-06-26 10:58

- 摘要：为 `Citation Trace` 增加可选课题线程上下文，溯源完成后可把目标论文、最终 Top5、warning 和小助手解释保存为当前精读线程中的溯源行动。
- 涉及文件：`frontend/src/CitationTracePage.jsx`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_citation_trace_can_store_action_in_research_thread`，确认 Citation Trace 缺少课题线程接入的红灯；实现后执行该测试和 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend`（通过，2 tests）、`git diff --check -- frontend/src/CitationTracePage.jsx tests/test_research_topics_frontend.py`（通过）、`npm run build`（在 `frontend/` 下通过，使用临时 `node_modules` 符号链接，已清理）。
- 后续：继续实现课题页和 App 标签页，把课题选择、线程查看和建议卡入口串起来。

## 2026-06-26 10:55

- 摘要：为 `Paper Reader` 增加课题线程接入点，支持将当前论文挂接到课题线程、在已关联线程时记录阅读进度事件，并在精读页头部显示课题记录状态。
- 涉及文件：`frontend/src/PaperReaderPage.jsx`、`frontend/src/styles.css`、`tests/test_research_topics_frontend.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend.ResearchTopicsFrontendTest.test_paper_reader_can_attach_to_topic_and_publish_thread_events`，确认 Paper Reader 缺少课题线程代码的红灯；实现后执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_frontend`（通过）、`git diff --check -- frontend/src/PaperReaderPage.jsx frontend/src/styles.css tests/test_research_topics_frontend.py`（通过）、`npm run build`（在 `frontend/` 下通过，使用临时 `node_modules` 符号链接，已清理）。
- 后续：继续让 Citation Trace 在存在课题线程上下文时保存溯源行动。

## 2026-06-26 10:49

- 摘要：新增规则优先的小助手建议卡服务和 API；搜索结果只生成“打开到课题精读”的推荐，不会直接写入课题记录，精读线程建议在用户接受后才写入线程事件。
- 涉及文件：`backend/research_topics_service.py`、`backend/main.py`、`backend/schemas.py`、`tests/test_research_topics_service.py`、`tests/test_research_topics_api.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_service.ResearchTopicSuggestionTest` 与 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api.ResearchTopicsApiTest.test_search_suggestion_route_does_not_write_topic_records`，确认建议函数缺失和路由 404 的红灯；实现后执行上述测试（通过），执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_service tests.test_research_topics_api`（通过，18 tests）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m py_compile backend/research_topics_service.py backend/main.py backend/schemas.py tests/test_research_topics_service.py tests/test_research_topics_api.py`（通过）、`git diff --check -- backend/research_topics_service.py backend/schemas.py backend/main.py tests/test_research_topics_service.py tests/test_research_topics_api.py`（通过）。
- 后续：继续把 Paper Reader 和 Citation Trace 前端工作流接到课题线程与建议卡 API。

## 2026-06-26 10:43

- 摘要：开放课题中心 API，支持列出/创建课题、将论文挂接为精读线程、记录线程事件并保存 Citation Trace 行动到对应线程。
- 涉及文件：`backend/main.py`、`backend/schemas.py`、`tests/test_research_topics_api.py`、`PROJECT_LOG.md`
- 验证：先执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api`，确认新增 API 测试因路由缺失返回 404 失败；实现后执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api`（通过，2 tests）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_api tests.test_research_topics_service`（通过，14 tests）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m py_compile backend/main.py backend/schemas.py tests/test_research_topics_api.py`（通过）、`git diff --check -- backend/main.py backend/schemas.py tests/test_research_topics_api.py`（通过）。
- 后续：继续实现规则优先的小助手建议卡服务，确保搜索只产生推荐、不直接写入课题记录。

## 2026-06-26 10:36

- 摘要：为小助手新增独立 `assistant_chat` 模型配置，并建立课题中心的论文精读线程服务；课题服务默认走 PostgreSQL 持久化，数据库不可用时可粘性降级到进程内存储。
- 涉及文件：`local_paper_db/app/search_service.py`、`backend/schemas.py`、`backend/config_store.py`、`backend/live2d_service.py`、`backend/main.py`、`backend/research_topics_service.py`、`config/runtime_settings.example.json`、`tests/test_assistant_chat_config.py`、`tests/test_research_topics_service.py`、`PROJECT_LOG.md`
- 验证：分阶段执行 `/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_assistant_chat_config`、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest discover -s tests`、`cd frontend && npm run build`（均通过）；本次 durable store 收尾执行 `git diff --check -- backend/research_topics_service.py tests/test_research_topics_service.py`（通过）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m unittest tests.test_research_topics_service`（12 tests OK）、`/Users/lyj/lyj/third_round/rag_papers_by_AI/.venv/bin/python -m py_compile backend/research_topics_service.py tests/test_research_topics_service.py`（通过）。
- 后续：继续接入 `/api/research-topics` 薄路由、规则优先的建议卡服务，以及 Paper Reader / Citation Trace / 前端课题页联动。

## 2026-06-25 23:54

- 摘要：新增课题档案助手实现计划，将 `assistant_chat` 配置、课题/论文精读线程持久化、建议卡、Paper Reader/Citation Trace 联动、前端课题档案页和验证步骤拆成可执行任务。
- 涉及文件：`docs/superpowers/plans/2026-06-25-research-topics-assistant.md`、`PROJECT_LOG.md`
- 验证：执行 `rg -n "TBD|TODO|FIXME|PLACEHOLDER|to be decided|implement later|Similar to|appropriate|same pattern|\\?\\?" docs/superpowers/plans/2026-06-25-research-topics-assistant.md`（无输出）；执行 `git diff --check -- docs/superpowers/plans/2026-06-25-research-topics-assistant.md`（通过）；手动检查计划覆盖设计文档中的课题项目、唯一论文精读线程、搜索只推荐、溯源行动记录、静默建议卡和小助手独立模型配置。
- 后续：等待用户选择 Subagent-Driven 或 Inline Execution 后开始按计划执行。

## 2026-06-25 23:42

- 摘要：新增课题档案助手设计文档，明确以课题为项目、论文精读为最小线程单位、搜索仅做推荐、溯源作为论文线程行动记录，并将小助手独立 `assistant_chat` API 配置纳入后续实现范围。
- 涉及文件：`docs/superpowers/specs/2026-06-25-research-topics-assistant-design.md`、`PROJECT_LOG.md`
- 验证：执行 `rg -n "TBD|TODO|FIXME|PLACEHOLDER|to be decided|\\?\\?" docs/superpowers/specs/2026-06-25-research-topics-assistant-design.md`（无输出）；执行 `git diff --check -- docs/superpowers/specs/2026-06-25-research-topics-assistant-design.md`（通过）；手动检查设计文档的写入边界、迁移策略和小助手独立模型配置说明。
- 后续：待用户确认设计文档后，再进入实现计划；实现时需要补齐 `assistant_chat` 配置、课题档案持久化、建议卡和 Paper Reader/Citation Trace 联动。

## 2026-06-25 22:04

- 摘要：补齐远端仓库安全自动化配置，新增 CodeQL 扫描与 Dependabot 依赖更新检查，并在中英文 README 中说明仓库安全卫生、只写 API Key 和示例配置提交规则。
- 涉及文件：`.github/workflows/codeql.yml`、`.github/dependabot.yml`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：执行 `git fetch --prune origin`（通过，当前分支相对 `origin/mac-dev` 为 ahead 23 / behind 0）；执行 `rg` 秘密扫描（未发现 OpenAI key、私钥或明文 `OPENAI_API_KEY=`）；执行 `git diff --check`（通过）；执行 `git status --ignored -s config`（确认 `config/runtime_settings.json` 为 ignored）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，92 tests）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：远端启用 GitHub Advanced Security 或分支保护需要仓库权限；当前提交已提供仓库内可追踪的 CodeQL / Dependabot 配置。

## 2026-06-25 11:01

- 摘要：新增仓库工作流图资产，使用图像生成工具生成四流程视觉参考，并用可复现渲染脚本输出搜索、引用溯源、精读和用户画像系统的 1920×1080 PNG 流程图。
- 涉及文件：`docs/workflows/render_workflow_diagrams.py`、`docs/workflows/search-workflow.svg`、`docs/workflows/search-workflow.png`、`docs/workflows/citation-trace-workflow.svg`、`docs/workflows/citation-trace-workflow.png`、`docs/workflows/paper-reader-workflow.svg`、`docs/workflows/paper-reader-workflow.png`、`docs/workflows/research-profile-workflow.svg`、`docs/workflows/research-profile-workflow.png`、`docs/workflows/workflow-overview-imagegen.png`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m py_compile docs/workflows/render_workflow_diagrams.py`（通过）；执行 `.venv/bin/python docs/workflows/render_workflow_diagrams.py`（通过，非沙箱渲染 PNG）；执行 `file docs/workflows/*.png docs/workflows/*.svg`（确认四张主图为 1920×1080 PNG，SVG 源图存在）；用本地图片查看确认主图文字与排版未明显截断。
- 后续：若工作流协议继续变化，直接更新 `render_workflow_diagrams.py` 中的流程数据并重新渲染图片。

## 2026-06-25 10:45

- 摘要：进一步收紧 Citation Trace 候选召回评分，将作者重叠从主证据降为极小 bonus；当候选只有作者/年份/来源置信度而缺少标题、主题或标识符证据时强制低分并写入 warning，同时前端将该字段显示为 `author_bonus`。
- 涉及文件：`backend/citation_trace_service.py`、`frontend/src/CitationTracePage.jsx`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_frontend.py`、`PROJECT_LOG.md`
- 验证：新增作者-only 候选回归测试，先确认旧公式会给到 0.2062；修复后执行 `.venv/bin/python -m unittest tests.test_citation_trace_service.CitationTraceServiceTest.test_reference_recall_treats_author_overlap_as_tiny_bonus_not_evidence tests.test_citation_trace_frontend.CitationTraceFrontendTest.test_citation_trace_page_contains_required_sections`（通过，2 tests）；执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_frontend`（通过，33 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py tests/test_citation_trace_service.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：若后续引入更多 bibliographic matching 信号，仍需保持作者只作为 tie-breaker，不能单独构成候选证据。

## 2026-06-25 10:41

- 摘要：将选区翻译卡扩展到 `Paper Reader` 以外的页面；新增通用 `/api/translate-selection` 接口，前端在非论文精读页监听页面文本选区并用 `paper_reader_translation` 配置翻译。
- 涉及文件：`backend/main.py`、`backend/paper_reader_service.py`、`backend/schemas.py`、`frontend/src/App.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_translation.py`、`tests/test_global_selection_translation_frontend.py`、`PROJECT_LOG.md`
- 验证：新增 `test_standalone_selected_text_translation_uses_translation_config_without_session` 与 `test_app_exposes_global_selection_translation_card_outside_paper_reader` 并先确认缺少无 session 翻译服务和全局卡片时失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation.PaperReaderTranslationTest.test_standalone_selected_text_translation_uses_translation_config_without_session`（通过）；执行 `.venv/bin/python -m unittest tests.test_global_selection_translation_frontend`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation tests.test_global_selection_translation_frontend`（通过，11 tests）；执行 `.venv/bin/python -m py_compile backend/main.py backend/paper_reader_service.py backend/schemas.py tests/test_paper_reader_translation.py tests/test_global_selection_translation_frontend.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，91 tests）；执行 `git diff --check`（通过）。
- 后续：全局卡片会忽略输入框、下拉框和可编辑区域里的选区；`Paper Reader` 页继续使用其专用 PDF 选区翻译卡，避免重复出现两个翻译入口。

## 2026-06-25 10:39

- 摘要：澄清 Citation Trace 详情页中 `reference_text` 的展示语义，将“原始问题”改为“原始参考文献片段”，并修复未编号 References 被 PDF 抽取成单段时多个 arXiv 引用粘连的问题。
- 涉及文件：`backend/citation_trace_service.py`、`frontend/src/App.jsx`、`frontend/src/CitationTracePage.jsx`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_frontend.py`、`PROJECT_LOG.md`
- 验证：新增未编号 arXiv references 分割测试和 Citation Trace 专用文案测试，先确认当前实现失败；修复后执行 `.venv/bin/python -m unittest tests.test_citation_trace_service.CitationTraceServiceTest.test_extract_reference_entries_splits_collapsed_unnumbered_arxiv_references tests.test_citation_trace_frontend.CitationTraceFrontendTest.test_citation_trace_page_contains_required_sections`（通过，2 tests）；执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_frontend`（通过，32 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py tests/test_citation_trace_service.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：未编号参考文献仍只能用启发式切分；若 PDF 完全丢失句点/年份边界，仍建议上传更干净的 PDF 或后续接入更强的 reference parser。

## 2026-06-25 10:18

- 摘要：修复 Citation Trace / Paper Reader 载入 arXiv PDF 时因 SSL EOF 或 429 限流直接中断的问题，新增 arXiv PDF 备用端点重试、短退避、PDF 内容校验、可操作的限流提示，并为 arXiv 标题候选解析增加缓存以减少重复 API 请求。
- 涉及文件：`backend/paper_reader_service.py`、`local_paper_db/app/external_sources.py`、`backend/main.py`、`tests/test_arxiv_reliability.py`、`tests/test_citation_trace_api.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `tests.test_arxiv_reliability` 先确认 SSL EOF 不重试、429 抛原始 HTTPError、title 查询重复请求；修复后执行 `.venv/bin/python -m unittest tests.test_arxiv_reliability tests.test_citation_trace_api`（通过，10 tests）；执行 `.venv/bin/python -m unittest tests.test_arxiv_reliability tests.test_citation_trace_service tests.test_citation_trace_api tests.test_paper_reader_index`（通过，42 tests）；执行 `.venv/bin/python -m py_compile backend/paper_reader_service.py backend/citation_trace_service.py backend/main.py local_paper_db/app/external_sources.py tests/test_arxiv_reliability.py tests/test_citation_trace_api.py`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，88 tests）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：arXiv 真实限流仍由远端控制，若持续 429，用户仍需稍后重试或上传本地 PDF；后续可考虑为已成功下载的 arXiv PDF 加磁盘缓存。

## 2026-06-24 17:24

- 摘要：将 Live2D 研究画像从小助手常驻面板中移出，新增独立“研究画像”页面用于查看、刷新、置顶和删除画像条目。
- 涉及文件：`frontend/src/App.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/ResearchProfilePage.jsx`、`frontend/src/styles.css`、`tests/test_research_profile_frontend.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `tests.test_research_profile_frontend` 并先确认旧结构下失败；修复后执行 `.venv/bin/python -B -m unittest tests.test_assistant_research_profile tests.test_research_profile_frontend`（通过，7 tests）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：画像真实生成仍依赖长期记忆数据库；独立页面只负责管理与降级提示，不改变画像抽取策略。

## 2026-06-24 15:16

- 摘要：为 `Paper Reader` 新增整篇论文级 Live2D 助手上下文接口，并将 PDF 选区改为点击“同步给小助手”后才作为助手回答焦点；同步修正 Live2D 的 Paper Reader prompt，不再按当前页上下文回答，并将最近用户/助手对话也打包进 workflow context。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`backend/main.py`、`backend/live2d_service.py`、`frontend/src/PaperReaderPage.jsx`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/styles.css`、`tests/test_paper_reader_translation.py`、`tests/test_paper_reader_live2d_behavior.py`、`README.md`、`README.zh-CN.md`、`docs/superpowers/specs/2026-06-24-paper-reader-assistant-selection-design.md`、`docs/superpowers/plans/2026-06-24-paper-reader-assistant-selection.md`、`PROJECT_LOG.md`
- 验证：新增 `test_assistant_context_uses_whole_paper_source_pages`、`test_live2d_paper_reader_context_renders_manual_selection_focus`、`test_paper_reader_syncs_whole_paper_context_not_active_page_context`、`test_live2d_paper_reader_context_renders_conversation_context`、`test_live2d_request_packages_conversation_context_with_workflow_context` 并先确认缺少功能时失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_translation tests.test_paper_reader_live2d_behavior`（通过，13 tests）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py backend/live2d_service.py tests/test_paper_reader_translation.py tests/test_paper_reader_live2d_behavior.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `git diff --check`（通过）。
- 后续：助手上下文为预算内整篇论文压缩切片，不替代主 Paper Reader 追问接口的检索式精读回答。

## 2026-06-24 14:43

- 摘要：修复 Live2D 研究画像在长期记忆数据库未连接时一直显示“研究画像暂时不可用”的问题，画像接口改为非致命降级返回，并在前端显示“连接长期记忆库后会开始积累画像”的行动提示。
- 涉及文件：`backend/live2d_service.py`、`backend/main.py`、`backend/schemas.py`、`frontend/src/Live2DAssistant.jsx`、`tests/test_assistant_research_profile.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -B -m unittest tests.test_assistant_research_profile.AssistantResearchProfileTest.test_live2d_research_profile_list_degrades_when_memory_store_is_unavailable`（先失败后通过）；执行 `.venv/bin/python -B -m unittest tests.test_assistant_research_profile`（通过，6 tests）；执行 `.venv/bin/python -B -m py_compile backend/live2d_service.py backend/main.py backend/schemas.py tests/test_assistant_research_profile.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `git diff --check`（通过）。
- 后续：真正生成画像仍需要本地 PostgreSQL/pgvector 记忆库可用；未连接时只做 UI 降级，不会保存或召回画像。

## 2026-06-24 14:37

- 摘要：移除 `Paper Reader` 用户可见的精读页分组概念，后端会话 `pages/page_count` 改为暴露 PDF 物理页，`/pages/{index}/source` 按物理页返回单页原文，前端翻页与总页数改为覆盖完整 PDF 页数。
- 涉及文件：`backend/schemas.py`、`backend/paper_reader_service.py`、`frontend/src/PaperReaderPage.jsx`、`tests/test_paper_reader_source_layout.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增 `test_session_manifest_uses_pdf_pages_not_deep_reading_groups`、`test_source_page_endpoint_uses_physical_pdf_page_index` 并先确认旧协议下失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过，15 tests）；执行 `.venv/bin/python -m py_compile backend/schemas.py backend/paper_reader_service.py backend/main.py tests/test_paper_reader_source_layout.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，77 tests）；执行 `git diff --check`（通过）。
- 后续：现有已打开的 Paper Reader 会话需要刷新或重新载入论文，前端才会拿到新的物理页 manifest。

## 2026-06-23 14:19

- 摘要：调整 `Paper Reader` 中间 PDF 原文区为单页显示，不再一次堆叠当前阅读分组的多张 PDF 页；底部上一页/下一页改为按 PDF 物理页翻页，并移除右侧阅读分组数字跳转。
- 涉及文件：`frontend/src/PaperReaderPage.jsx`、`tests/test_paper_reader_source_layout.py`、`PROJECT_LOG.md`
- 验证：新增 `test_frontend_pdf_reader_shows_one_source_page_with_bottom_navigation` 并先确认缺少 `activeSourcePageNumber` 时失败；修复后执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout.PaperReaderSourceLayoutTest.test_frontend_pdf_reader_shows_one_source_page_with_bottom_navigation`（通过）；执行 `.venv/bin/python -m unittest tests.test_paper_reader_source_layout tests.test_paper_reader_translation`（通过，13 tests）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，75 tests）；执行 `git diff --check`（通过）。
- 后续：无。

## 2026-06-22 17:50

- 摘要：为 Live2D 助手新增 Paper Reader 优先的研究画像能力，从论文阅读上下文中抽取专业方向、后续研究方向和阅读偏好画像信号，并在助手面板中支持刷新、置顶和删除。
- 涉及文件：`backend/assistant_memory.py`、`backend/live2d_service.py`、`backend/main.py`、`backend/schemas.py`、`backend/config_store.py`、`local_paper_db/app/search_service.py`、`frontend/src/Live2DAssistant.jsx`、`frontend/src/styles.css`、`config/runtime_settings.example.json`、`README.md`、`README.zh-CN.md`、`tests/test_assistant_research_profile.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -B -m unittest discover -s tests`（通过，74 tests）；执行 `.venv/bin/python -B -m py_compile backend/assistant_memory.py backend/live2d_service.py backend/main.py backend/schemas.py backend/config_store.py local_paper_db/app/search_service.py tests/test_assistant_research_profile.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `git diff --check`（通过）；使用 Browser 打开 `http://127.0.0.1:5173/`，确认助手画像面板渲染，且 PostgreSQL 未启动时只显示温和降级文案。
- 后续：画像仍是基于论文阅读行为的低频谨慎推断，不代表确定身份或正式专业标签；真实效果需要在多篇 Paper Reader 会话后人工观察建议质量。

## 2026-06-22 14:39

- 摘要：重做 Citation Trace Top15 候选规则分，降低纯 reference 标识符命中的权重，加入目标论文主题相关性、reference 标题一致性和非论文片段过滤，并修复 worker 返回数字字段时的解析失败。
- 涉及文件：`backend/citation_trace_service.py`、`tests/test_citation_trace_service.py`、`README.md`、`README.zh-CN.md`、`PROJECT_LOG.md`
- 验证：新增回归测试先确认 Toolformer 类主题错位 exact arXiv 命中仍得高分、Algorithm 片段会进入 Top15、数字型 worker `confidence` 会触发失败；修复后执行 `.venv/bin/python -m unittest tests.test_citation_trace_service`（通过，28 tests）；执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_paper_reader_translation`（通过，43 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/config_store.py local_paper_db/app/search_service.py`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，69 tests）；执行 `npm run build`（在 `frontend/` 下，通过）。
- 后续：规则分仍是轻量词法相关性，后续可继续引入候选论文 introduction/conclusion 抽取或本地 embedding 相关性作为更强的 topic alignment 信号。

## 2026-06-22 11:40

- 摘要：将 Citation Trace 默认流程改为一轮 references Top15 候选召回，新增主/副溯源模型配置，接入副模型逐候选分析与主模型 Top5 排序，并保留规则兜底。
- 涉及文件：`backend/citation_trace_service.py`、`backend/config_store.py`、`backend/schemas.py`、`backend/main.py`、`local_paper_db/app/search_service.py`、`frontend/src/App.jsx`、`frontend/src/CitationTracePage.jsx`、`config/runtime_settings.example.json`、`README.md`、`README.zh-CN.md`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_frontend.py`、`tests/test_paper_reader_translation.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_paper_reader_translation`（通过，41 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/config_store.py local_paper_db/app/search_service.py`（通过）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，67 tests）；执行 `npm run build`（在 `frontend/` 下，通过）；执行旧二轮/兜底文案扫描（无输出）；执行 `git diff --check`（通过）。
- 后续：真实远程模型质量依赖主/副模型配置与 arXiv/PDF 可访问性；后续可再做候选 PDF 的 introduction/conclusion 精细抽取和缓存。

## 2026-06-21 23:01

- 摘要：根据最终审查补齐 Citation Trace 的真实第二轮 prior-work 检索扩展，为 arXiv 会话 ID 增加唯一后缀避免缓存串用，并同步设计/计划文档中的兜底 Top5 表述。
- 涉及文件：`backend/citation_trace_service.py`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_cleanup.py`、`docs/superpowers/specs/2026-06-20-citation-trace-design.md`、`docs/superpowers/plans/2026-06-20-citation-trace-implementation.md`、`PROJECT_LOG.md`
- 验证：新增回归测试先观察到同一 arXiv 论文复用 session id、`expand_seed_candidates` 未接入检索函数、设计文档仍有 LLM-ranked Top5 旧表述；修复后执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_citation_trace_cleanup`（通过，35 tests）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，61 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/live2d_service.py backend/assistant_memory.py local_paper_db/app/search_service.py local_paper_db/app/search.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行旧 trace/PST 标识扫描（无输出）；执行旧 Top5 过度承诺措辞扫描（无输出）；执行 `git diff --check`（通过）。
- 后续：模型排序/LLM 主判仍是后续增强项；当前最终 Top5 为证据账本兜底生成。

## 2026-06-21 22:49

- 摘要：清理 Citation Trace 迁移测试中的旧 trace 字面量，让旧接口、旧来源和旧执行标识的残留扫描可以作为硬门禁使用，同时保持负向断言语义不变。
- 涉及文件：`tests/test_citation_trace_api.py`、`tests/test_citation_trace_cleanup.py`、`tests/test_citation_trace_frontend.py`、`PROJECT_LOG.md`
- 验证：执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_citation_trace_cleanup`（通过，32 tests）；执行 `.venv/bin/python -m unittest discover -s tests`（通过，58 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/live2d_service.py backend/assistant_memory.py local_paper_db/app/search_service.py local_paper_db/app/search.py`（通过）；执行 `npm run build`（在 `frontend/` 下，通过）；执行 `rg -n "PST|pst_auto|/api/trace|TraceExecution|execute_trace|stream_trace_answer_tokens" backend frontend/src local_paper_db/app tests README.md README.zh-CN.md`（无输出）；执行 `git diff --check`（通过）。
- 后续：无。

## 2026-06-21 22:01

- 摘要：用新的 `Citation Trace / 论文溯源` 工作台替代旧 PST-lite，新增引用抽取、两轮溯源扩展、证据账本、基于账本的兜底 Top5 后端/API/前端骨架，并移除旧 `/api/trace/*` 与 `pst_auto` 概念。
- 涉及文件：`backend/citation_trace_service.py`、`backend/main.py`、`backend/schemas.py`、`backend/live2d_service.py`、`backend/assistant_memory.py`、`local_paper_db/app/search_service.py`、`local_paper_db/app/search.py`、`frontend/src/App.jsx`、`frontend/src/CitationTracePage.jsx`、`frontend/src/styles.css`、`README.md`、`README.zh-CN.md`、`tests/test_citation_trace_service.py`、`tests/test_citation_trace_api.py`、`tests/test_citation_trace_frontend.py`、`tests/test_citation_trace_cleanup.py`
- 验证：先执行 `.venv/bin/python -m unittest tests.test_citation_trace_cleanup.CitationTraceCleanupTest.test_readmes_document_citation_trace_not_pst`，确认 README 仍缺少 `Citation Trace` 时失败；更新文档后该单测通过。执行 `.venv/bin/python -m unittest tests.test_citation_trace_service tests.test_citation_trace_api tests.test_citation_trace_frontend tests.test_citation_trace_cleanup tests.test_paper_reader_live2d_behavior`（通过，34 tests）；执行 `.venv/bin/python -m py_compile backend/citation_trace_service.py backend/main.py backend/schemas.py backend/live2d_service.py backend/assistant_memory.py local_paper_db/app/search_service.py local_paper_db/app/search.py tests/test_citation_trace_service.py tests/test_citation_trace_api.py tests/test_citation_trace_frontend.py tests/test_citation_trace_cleanup.py tests/test_paper_reader_live2d_behavior.py`（通过）；执行 `cd frontend && npm run build`（通过）；执行 `.venv/bin/python -m unittest tests.test_citation_trace_cleanup`（通过）；执行 `git diff --check -- README.md README.zh-CN.md PROJECT_LOG.md tests/test_citation_trace_cleanup.py`（通过）。
- 后续：记录真实 arXiv/PDF 端到端人工验收结果，以及需要继续增强的图谱交互或引用解析能力。

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
