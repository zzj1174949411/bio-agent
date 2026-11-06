# 模型设置与统一调用实现计划

> **面向 AI 代理的工作者：** 使用 superpowers:executing-plans 在当前已授权会话内执行；步骤使用复选框跟踪。仅包含一个编号任务，不另建 worktree、不推送。

**目标：** 任务 37：页面管理多个模型、记忆对话选择，并使上传及 GEO 规划使用当轮模型。

**架构：** 复用 ProfileStore、系统凭据库与 ModelAdapter。PreparedChat 在服务端持有同一客户端装配的 Planner；AnalysisService 通过服务端工厂创建绑定 Planner 的独立图实例，共享现有 checkpoint/执行器。工厂与模型不会序列化，图中只保留原有非密钥快照；旧 API 继续使用默认 Planner 和真实 readiness。

**技术栈：** FastAPI、LangGraph、Pydantic、SQLite、React/TypeScript、Vitest、Playwright。

### 任务 37：模型与 API 设置及当轮规划绑定

**文件与职责：**
- 修改 `src/bioagent/llm/planner.py`、`src/bioagent/models/adapters.py`、`src/bioagent/models/store.py`：按固定快照创建客户端，凭据在请求边界解析。
- 修改 `src/bioagent/workbench/turns.py`：PreparedChat 持有 Planner；上传和 GEO 回调传递服务端 Planner。
- 修改 `src/bioagent/api/dependencies.py`、`src/bioagent/services/analysis.py`：规划依赖作用域，与旧 API 默认依赖隔离。
- 修改 `frontend/src/App.tsx`、`frontend/src/api/client.ts`、`frontend/src/features/models/ModelSettings.tsx`、`frontend/src/features/chat/Composer.tsx`、`frontend/src/styles.css`：独立设置页签、异步保存反馈、聊天选择持久化与失效提示。
- 修改 `tests/integration/api/test_workbench_analysis.py`、`tests/unit/workbench/test_turn_service.py`、`frontend/src/features/models/ModelSettings.test.tsx`、`frontend/e2e/workbench.spec.ts`：关键回归与固定浏览器流程。
- 修改 `README.md`、`docs/getting-started.md`、`docs/workbench.md` 和 GEO 搜索计划：同步页面配置、关键词搜索及已有任务证据。
- 纳入交接的模型设置规格和 `docs/progress/current-state.md`；不暂存 `renv/activate.R`。

- [x] **步骤 1：关键失败测试与红灯**

构造无环境 Key 的应用，用 Mock 的 ChatOpenAI/Ollama 构造器记录模型 ID；两个保存的 profile 分别发送上传规划，断言 Planner 的同步 invoke 与聊天 stream 使用同一 ID。聊天途中编辑 profile 后原轮仍使用旧快照；GEO READY 回调也从原 turn 快照创建规划，删除配置时明确失败且不调用环境 Planner。断言审批前 attempts 为空、run/checkpoint 不含凭据。

```python
assert turn["status"] == "WAITING_USER"
assert planned_models == ["model-a", "model-b"]
assert state["status"] == "AWAITING_APPROVAL"
assert not list((runs_dir / run_id / "attempts").glob("*"))
```

运行 `uv run --offline pytest tests/integration/api/test_workbench_analysis.py -q -p no:cacheprovider`，新增用例应因调用环境 Planner 而失败。前端补保存中重复操作和保存失败反馈测试，运行 `npm --prefix frontend run test -- --run` 确认红灯。

- [x] **步骤 2：统一服务端调用链**

`ModelAdapter.create(identity, fixed=None)` 按 `fixed or profile.snapshot()` 装配客户端。`PreparedChat` 增加仅内存 `planner` 字段，由 `AnalysisPlanner(model)` 构造。上传路径传入 job 的 Planner；GEO READY 使用 turn 的 profile ID 和固定 snapshot 在回调边界装配。`DependencyContainer.planning_graph(planner)` 复用 checkpointer 与 execution adapter 创建独立图，`AnalysisService.create_run(..., planner=None)` 只在本次调用使用该图，避免并发模型污染。保持所有旧 API/Mock override 接口兼容。

```python
graph = dependencies.planning_graph(planner)
result = graph.invoke(initial, config)
```

无模型/已删除/凭据缺失时返回稳定错误；GEO 回调发出不含异常文本的失败事件，禁止静默回退。运行步骤 1 命令及 `tests/unit/models tests/unit/workbench tests/integration/api tests/e2e/test_geo_workflow.py tests/e2e/test_geo_search_workflow.py` 相关回归。

- [x] **步骤 3：独立设置入口和对话选择**

设置页有“模型与 API / Skills / MCP”和“返回聊天”，保留已挂载聊天状态；模型表单移出结果侧栏。编辑 ID 与聊天 ID 分开。聊天选择通过已有 conversation PATCH 持久化，切换对话读取 `selected_profile_id`，不重置正在进行的聊天。表单在 Promise 完成前禁用动作，失败显示具体可操作提示，成功后清空密码；credential API 返回值更新列表，失败后重读真实配置。

```typescript
const profile = await api.saveProfile(configuration);
const saved = payload.apiKey ? await api.saveCredential(profile.id, payload.apiKey) : profile;
setProfiles((items) => [...items.filter((item) => item.id !== saved.id), saved]);
```

三个协议提供可读名称、URL 示例与 Ollama 无 Key 提示；探针仅宣称结构化输出验证。无模型或已删除选择提供设置入口。

- [x] **步骤 4：浏览器与回归门禁**

固定 route fixture 覆盖进入设置、保存多个配置、返回聊天、独立选择、刷新/对话切换记忆、生成待审批计划，以及窄屏操作。运行：

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run e2e
uv run --offline ruff check .
uv run --offline mypy src
uv run --offline pre-commit run --all-files
```

预期全部退出 0。所有外部模型和 GEO 调用使用 Mock/本地 fixture；不读取真实 Key。

- [x] **步骤 5：文档、复核与提交**

按实际结果更新当前进度、此计划复选框和旧任务 34/35 已有提交支持的复选框；用户入口说明以页面配置为主，环境配置明确可选只读。审阅变更、只暂存明确文件，执行 `git diff --cached --check` 后以 `feat(任务37): 添加模型设置并统一聊天与规划配置` 提交。运行 `git status --short --branch` 与 `git log -1 --oneline`，报告真实验证结果、未提交用户改动和限制，完成后停止。

执行记录：后端关键红灯、前端重复保存红灯及临时移除 Planner 绑定的红灯均已验证。受影响后端 171 项通过；最终模型/Planner 聚焦 107 项通过，追加审批/readiness/失败规划复核 9 项通过。Vitest 33 项、Playwright 5 条、typecheck/build、Ruff、mypy（80 文件）、pre-commit 8 hooks 通过。规划文档提交 `dbf7877`；最后实施提交以 Git HEAD 为准。真实服务与系统凭据库端到端联调不在自动 Mock 验收范围。
