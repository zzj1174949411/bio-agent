# 本地文献工作台实施计划

> **面向 AI 代理的工作者：** 使用 writing-plans 制定计划、executing-plans 在当前聊天执行。全部步骤属于唯一编号任务 40；保留 renv 用户改动，不启动其他任务，不 push/merge/PR。

**目标：** 用户可在工作台管理本地 PDF 知识库，在对话选择库，通过受控动作获得可信问答和可撤销的 PDF/表格/图片证据预览。

**架构：** 复用 KnowledgeStore、RetrievalEngine、AnswerService 和现有模型配置。对话 JSON 增加带默认值的库选择，轮次保存服务端产生的 scope/index revision 快照及 ask ID，兼容旧记录。提交时冻结 READY 版本与已准备模型；知识动作不接受库 ID，完全由轮次授权范围决定。问答前后核对固定版本，重建/删除后失败且要求用户重发。工作台事件仅保存知识任务 ID/操作状态，不复制可撤销答案；答案与引用始终从 Task 39 服务读取，历史消息和事件不能重放撤销文本。

**技术栈：** Python 3.12、FastAPI、SQLite/Pydantic；React/TypeScript、Vitest、Playwright；已有离线 Docling/E5/Qdrant。测试模型为 Mock，凭据仅内存。

## 文件与职责

- `src/bioagent/workbench/models.py`、`store.py`：对话选择、轮次快照/ask 关联、消息引用，旧 JSON 默认值兼容。
- `src/bioagent/workbench/actions.py`、`turns.py`、`tool_loop.py`：强类型 knowledge_ask 动作、服务端范围与生命周期、取消。
- `src/bioagent/workbench/knowledge.py`：可信问答桥接、所属关系核对与证据预览。
- `src/bioagent/knowledge/retrieval.py`、`retrieval_models.py`、`answers.py`：固定 READY revision 检索、固定模型/证据快照、验证阶段事件和失效语义。
- `src/bioagent/api/workbench_routes.py`、`dependencies.py`、`app.py`：选库验证、可信任务读取和受控资源路由、装配及错误码。
- `src/bioagent/knowledge/preview.py`：固定命令、无网络/密钥、有限时间/内存/输出的静态 PDF 页渲染。
- `frontend/src/api/knowledge.ts`、`types.ts`、`client.ts`：知识类型与受控请求、SSE 序号恢复。
- `frontend/src/features/knowledge/KnowledgeManager.tsx`、`KnowledgeAnswer.tsx`、`frontend/src/App.tsx`、`features/chat/ChatTimeline.tsx`：管理、选库、可信答案和原文预览；沿用 CSS。
- `tests/integration/api/test_workbench_knowledge.py`：固定版本/模型、越权动作、旧记录兼容和撤销重放关键失败用例。
- `frontend/src/features/knowledge/KnowledgeAnswer.test.tsx`、`frontend/e2e/knowledge.spec.ts`：转义/失效/窄屏隔离路径与真实本地全流程。
- `scripts/serve_literature_workbench.py`：仅自制样本与内存 Mock 模型的真实本地 UI 验收服务。
- `docs/knowledge-workbench.md`、原导入/检索说明、本计划、`docs/progress/current-state.md`：使用与实际结果、限制及 38–40 自查依据。

### 任务 40：知识库管理、聊天动作与可信证据预览

- [x] **步骤 1：关键红灯。** 测试提交轮次后修改库/模型和重建，仍使用固定快照或稳定 EVIDENCE_STALE；模型不能指定未授权库；答案撤销后历史/事件不暴露旧内容。

```python
fixed = engine.snapshot([base_id])
engine.build(document_id)
with pytest.raises(KnowledgeError, match='EVIDENCE_STALE'):
    engine.search('question', [base_id], fixed=fixed)
```

运行 `uv run --extra rag --offline pytest tests/integration/api/test_workbench_knowledge.py -q -p no:cacheprovider`，记录新增契约缺失红灯，再实现。

- [x] **步骤 2：服务端快照与动作。** scope/revision 由服务端取得；knowledge_ask 仅有 question。轮次保存快照，问答复用当轮模型和临时已准备客户端（不持久化凭据/闭包）。固定检索集合允许新增无关文献但拒绝原版本失效，不偷偷换版本。取消传递给 ask，服务端核对 conversation/turn/ask 归属。
- [x] **步骤 3：工作台管理。** 库 CRUD、每批四份 PDF、本地解析/索引 readiness、各阶段与错误、取消/重试/索引/重建/删除。缺依赖给出可打开安装文档；不阻塞模型设置或其他聊天。
- [x] **步骤 4：对话与证据。** 选库 PATCH 持久化；切换/刷新恢复。消息内显示可观察状态、命中数、已验证答案分段、引用验证和失败/取消。受控预览路由核验本轮引用与磁盘哈希，返回 PDF 页/结构表格/裁剪。前端转义内容，不信模型链接；历史定期核验并撤销旧答案和打开预览。
- [x] **步骤 5：真实 UI 验收。** `uv run --extra rag --offline python scripts/serve_literature_workbench.py` 启动隔离 ignored data 服务；Playwright 创建库→上传自制 PDF→解析→索引 READY→选库提问→观察事件→PDF/表格/图片→切换/刷新恢复→重建/删除失效。真实 Docling/E5/Qdrant、Mock 回答，无真实 Key/用户文献。保存 ignored 验收记录/截图。
- [x] **步骤 6：回归与收尾。** 定向 Python、相关组件/Playwright，`npm run typecheck`、`npm run build`、`uv run --offline ruff check .`、`uv run --offline mypy src`、`uv run --offline pre-commit run --all-files`、`git diff --cached --check`。更新文档、复盘自查和真实结果；明确图片 not_performed、解析/检索质量、供应商问答未验收。逐文件暂存提交 `feat(任务40): 集成知识库工作台与可信聊天证据`；确认 renv SHA256 和 Git 状态。

## 执行记录

起点 `7b52703`，分支 `agent/bio-agent-mvp`，仅既有 `renv/activate.R` 修改。父会话独立验收后完成任务 38–40 整体复盘。

- 初始关键契约 **3 failed**：缺少固定版本、受控动作和桥接；前端证据组件缺失红灯。实现后，额外前言泄漏红灯揭示未经验证文本进入历史，改为有界缓冲并丢弃知识动作前言。新增取消、排队重建、owner 和旧 JSON 兼容回归。
- 首轮真实 UI 暴露创建库加载竞争、测试服务 override 键写错、删除测试等待缺失；已修复。错误 override 曾导致本地 Ollama 连接失败，未调用公网/真实供应商。PDF iframe 请求成功但 Chrome 实际阻止插件，不能据 HTTP 200 算通过；改为受控静态 PNG，修复现有 pypdfium2 不支持 context manager，最终检查自然宽度并人工查看截图。
- 最终后端定向命令（workbench/knowledge/retrieval 单元及 workbench/tools/analysis/knowledge/model_profiles API）**140 passed in 109.79s**；之后仅增加旧 JSON 兼容测试，`tests/integration/api/test_workbench_knowledge.py` **7 passed in 9.27s**。前端 **17 files / 35 passed in 8.54s**。`npm run typecheck`、`npm run build` 通过；Ruff 退出 0（既有 ACL 警告），mypy **102 source files** 通过。
- 全部浏览器用例顺序运行：`BIOAGENT_REAL_KNOWLEDGE_UI=1 npm exec --offline -- playwright test --workers=1 --output=../data/task40/playwright-final`，**6 passed (1.2m)**。真实本地文献用例约 1.1m；另五项覆盖模型设置、角色/键盘/刷新/窄屏、GEO 搜索与 raw counts 人工确认、分析审批、Skills/MCP。
- 最终真实记录 `data/task40/ui-acceptance/acceptance.json`：2026-10-12 UTC 12:19:12.728 开始、12:20:05.472 三份 READY、12:20:19.996 完成。SSE 记录六条命中、RETRIEVING/GENERATING/VALIDATING、两段已验证答案、COMPLETED。PDF 页/结构化表格/实际 picture 裁剪、选择切换与刷新、重建/删除撤销三轮答案、旧 PDF 409、失效 SSE 不重放旧答案均通过。截图已实际查看；所有样本、模型、数据库、索引和截图 ignored。
- 真实用例必须显式启用，不改变默认 fixture e2e 所需环境。没有真实供应商问答质量、任意语料召回率或视觉理解验收；引用校验不保证语义正确。PDF 子进程是资源/环境边界，不是操作系统沙箱。已下载文件不能撤回。
- 收尾：旧 JSON 专项在持久化记录移除新增字段后重启恢复通过；任务定向 **7 passed (9.27s)**。八项 `uv run --offline pre-commit run --all-files` 全部 Passed；`git diff --cached --check` 退出 0。仅暂存本任务 31 份代码/测试/说明/计划与进度文件，用户 renv 未暂存，SHA256 保持 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。使用上列任务 40 message 本地提交，提交后检查状态；不 push/merge/PR，不启动任务 41。
