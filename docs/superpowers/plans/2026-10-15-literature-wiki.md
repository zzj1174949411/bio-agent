# 文献 Wiki 实现计划（任务 43）

> **面向 AI 代理的工作者：** 使用 superpowers:executing-plans 在本聊天完成唯一编号任务43。设计已经批准，不再申请设计批准；不开始44。

**目标：** 为一个本地知识库显式构建有来源、可撤销、可浏览的 AI Wiki。

**架构：** 复用 KnowledgeStore 的 SQLite 事务及 RetrievalEngine 已校验的 chunk。Wiki 服务冻结 READY 原文、模型、提示词和输入分段，逐论文生成，再用有界原文综合概念/主题；所有陈述必须引用实际发送片段。SQLite 保存任务、版本、依赖和当前版本指针，全部校验后事务发布。源变更通过数据库触发器递归撤销，读取再核验物理 hash；旧有效版本在生成失败时保留。

**技术栈：** Python/FastAPI/Pydantic/SQLite、React/TypeScript、pytest、Playwright；Docling/E5/Qdrant 本地验收，模型仅内存 Mock。

## 职责与文件

- 新建 `src/bioagent/knowledge/wiki_models.py`：有界构建请求、preflight、来源、草稿、页面和任务契约。
- 新建 `src/bioagent/knowledge/wiki_store.py`：规范 SQLite 版本/依赖、原子发布、递归撤销、恢复与受控 Markdown 导出。
- 新建 `src/bioagent/knowledge/wiki.py`：冻结原文/模型、分段与覆盖、调用预算、生成/取消/重试、来源逐字段/quote 校验。
- 新建 `src/bioagent/api/wiki_routes.py`；修改 `api/app.py`、`api/dependencies.py`：既有 owner/Host/Origin/CSRF 范围下装配生命周期和 UUID API。
- 新建 `frontend/src/api/wiki.ts`、`frontend/src/features/knowledge/KnowledgeWiki.tsx`；修改 `frontend/src/api/client.ts`、`KnowledgeManager.tsx`：预检、显式启动、停止/重试、页/链接、回源和下载。沿用现有可滚动管理面板。
- 新建 `tests/unit/knowledge/test_wiki.py`、`tests/integration/api/test_wiki.py`、`frontend/e2e/wiki.spec.ts`：只测关键完整性与真实 UI 路径。
- 新建 `scripts/verify_literature_wiki.py`、`docs/knowledge-wiki.md`；必要修改 `scripts/serve_literature_workbench.py` 仅增加验收 Mock Wiki adapter。
- 更新本计划与 `docs/progress/current-state.md`；不改 AGENTS.md、renv、评测模式、统计/GEO 或用户模型设置。

## 任务 43

- [x] 1. 编写关键失败测试并运行：`uv run --offline pytest tests/unit/knowledge/test_wiki.py -q -p no:cacheprovider --basetemp data/task43/red`。初始因 Wiki 模块不存在收集失败；后续测试覆盖 quote/hash/跨库伪造、发布失败旧版本、源删除/重建及主题/链接递归撤销、取消/恢复、无变化零调用、调用预算和长输入覆盖。

```python
assert service.pages(base_id).items == ()  # 未显式启动不生成
job = await service.submit(base_id, request, model=mock)
assert job.calls <= request.max_calls
assert all(c.quote in sent[c.chunk_id].text for p in pages for s in p.statements for c in s.citations)
```

- [x] 2. 实现契约、SQLite 与生成服务。每次调用前持久化计数；无隐式重试。输入使用完整 chunk 的有界分段，未送入部分记录 coverage；摘要按实际分段，综合只看实际送入的原文与页面键。新模型/profile/提示词变化重建；否则复用未失效论文页，只重建受影响论文和聚合页。任务 snapshot 与当前所有 READY 文献比较后原子发布。
- [x] 3. 实现受控 API、基本导航与原文预览。preflight 返回库/文献数、输入 chunk/byte/页覆盖、模型及上限，启动重算并核对 preflight hash；不接受任意路径/HTML/模型 URL。页面 AI 标记、未人工审定、候选分歧和研究条件显式显示。每次预览核验当前页面、引用和 PDF hash/页码。
- [x] 4. 运行聚焦回归与静态检查：`uv run --offline pytest tests/unit/knowledge/test_wiki.py tests/unit/knowledge/test_retrieval.py tests/unit/knowledge/test_store.py tests/integration/api/test_wiki.py tests/integration/api/test_knowledge_retrieval.py -q -p no:cacheprovider --basetemp data/task43/final`；`uv run --offline ruff check .`；`uv run --offline mypy src`；`npm --prefix frontend run typecheck`；`npm --prefix frontend run build`；受影响 KnowledgeManager Vitest。
- [x] 5. 真实本地验收：`uv run --extra rag --offline python scripts/verify_literature_wiki.py --output data/task43/acceptance`；复用自制三 PDF、ignored parser/E5 权重，独立 TestClient API，不占8000。证明来源/删除或重建撤销/重启一致，模型仅 Mock。另在独立4183 API及其生产静态UI执行一条真实 Playwright Wiki 管理→预检→启动→页面→链接→原文→取消/失效路径，并核对桌面独立滚动与窄屏可达/无横向溢出。
- [x] 6. 更新使用说明/进度/本计划，记录真实结果与协议/token/语义限制。明确暂存上述任务文件，执行 `uv run --offline pre-commit run --all-files`、`git diff --cached --check`；提交 `feat(任务43): 添加有来源版本与撤销的文献Wiki`。确认 Git 状态及 renv SHA256；停止，等待父会话独立验收。

## 验收边界

未指定真实语料和付费预算，因此不读取 Key、不调用供应商。输入 bytes、存储输出 bytes、调用次数由服务端硬限；provider 输出参数按协议绑定，但未经实测的 token/费用/服务端拒绝能力明确提示，不静默切模型。usage 未知为 null；失败不生成占位摘要。引用匹配证明归属及原文一致，不证明语义蕴含。任务44才添加 hybrid/聊天入口和质量比较。

## 执行记录

- 父会话独立验收：实现 `a940ccb`，Wiki单元/API **13 passed (17.88s)**，真实本地API脚本复跑退出0（三PDF、5次Mock初建/2次增量、重启及撤销通过），输出 `data/task43/parent-acceptance-20261015`。独立审阅关键边界并查看既有真实浏览器记录、原文与390px截图；未重复浏览器全套。真实供应商与语义质量仍未验收；可安排44，不能宣称准确率提升。
- 唯一编号43在原worktree/分支执行；初始红灯为缺Wiki模块。补充长输入页面coverage、在途索引排除、提示词/schema复用快照的红灯后最小修正。没有供应商调用、Key读取、用户PDF或多Agent产品功能。
- 最终聚焦命令使用 `--basetemp data/task43/final-verified --tb=short`：48 passed in28.90s；Ruff通过、mypy109 source files通过；前端typecheck/build通过，KnowledgeManager Vitest4 passed。
- 真实API命令输出 `data/task43/acceptance-final-verified`：三PDF、5页、首次5次Mock，短论文增量2次；quote/跨库/预览/导出/原RAG/撤销/重启通过。PDF、权重、索引、Wiki和报告均ignored。
- Playwright真实路径1 passed (32.3s)，独立4183单Origin生产静态页，不需另启5174。窄屏先纠正既有布局契约断言，再以实际overflow JSON定位选择框403px溢出，修复后390px/overflow空，桌面独立滚动；截图见ignored data/task43/ui-acceptance。自建4183已关闭，不操作8000。
- SQLite递归撤销由trigger执行，物理文件变化再读取验证；输出bytes为返回后拒收，不是供应商token/费用保证。没有语义质量验收；Task44未开始。最终暂存/提交门禁结果记录于current-state收尾条目。
