# 文献混合检索实现计划（任务 44）

> 面向 AI 工作者：使用 executing-plans 在当前聊天执行；本文件只含一个编号任务。已批准设计不重复审批，任务结束提交并停止。

**目标：** 提供可审计的原文/Wiki 混合问答、冻结的工作台模式和公平三组评测工具。

**架构：** 原文仍使用 BM25/E5/Qdrant。独立混合服务关键词检索 CURRENT Wiki，通过页面及链接引用补找同库原文；完整原文和派生导航分别分配预算。Ask、聊天轮次保存原文 revision 与 Wiki generation/page 快照，发布、读取和 SSE 重放重新验证。

**技术栈：** Python/Pydantic/FastAPI/SQLite、React/TypeScript、pytest/Playwright、已有离线 Docling/E5/Qdrant。

## 文件职责

- `src/bioagent/knowledge/hybrid.py`：CURRENT Wiki 检索、同库回源、去重、上下文分配及冻结快照校验。
- `retrieval_models.py`、`answers.py`：mode、两路实际上下文审计、生成/撤销；旧请求默认 rag。
- `workbench/models.py`、`store.py`、`turns.py`、`knowledge.py`、`api/workbench_routes.py`、`api/dependencies.py`：每对话模式、提交冻结和可信绑定。
- `frontend/src/App.tsx`、`api/{types,client,knowledge}.ts`、`features/knowledge/KnowledgeAnswer.tsx`：模式选择及实际模式/回退/派生来源展示。
- `knowledge/evaluation.py`、`scripts/evaluate_literature.py`、`models/evaluation_limits.py`：三模式同协议、Wiki成本/覆盖、源码hash、供应商能力声明与完整分母。
- `tests/unit/knowledge/test_hybrid.py`、既有评测/聊天/API/UI测试：关键差异、预算、跨库、版本撤销、失败分母。
- `scripts/verify_literature_hybrid.py`、`frontend/e2e`：真实本地API/UI，模型Mock。
- `docs/knowledge-hybrid.md`、`knowledge-evaluation.md`、`docs/progress/current-state.md`、`docs/reviews/2026-10-15-tasks42-44.md`：使用、证据与三任务复盘。

## 任务 44

- [x] 先写并运行关键红灯：`uv run --offline pytest tests/unit/knowledge/test_hybrid.py -q -p no:cacheprovider`。检验 hybrid 真正增加原文、wiki 不调用正文 search、独立预算和实际计数、无Wiki回退、严格评测禁止回退、跨库与generation改变撤销。
- [x] 实现混合服务与 Ask。候选页面限制为当前scope/generation；最终citation只能来自实际送入的原文。`rag` 原路径保持，`wiki` 仅消融，实验无Wiki稳定失败。检索数量与实际发送数量/JSON字节/chunk和page ID分别保存。
- [x] 聊天/API/UI先增加失败用例，再实现conversation mode；提交时冻结 mode、库、原文和Wiki快照。模型action无scope/path/mode权限。刷新/切换/取消/撤销不泄漏旧内容。
- [x] 评测先红灯再实现 rag/wiki/hybrid。锁定同语料、模型、题目、上下文上限及Wiki generation；Wiki构建成本/覆盖独立记录。保留正式60题六类各10、15/45隔离；未知usage/评分为null。盲评去模式元数据，配对比较完整题集。
- [x] 调查官方DeepSeek协议与本地SDK（仅文档和代码，不读Key/真实探测）。可证明的调用/应用输入/输出限制明确列出，无法证明的token/费用界限拒绝受控live；不改用户profile、不宣称历史故障已修复。
- [x] 真实本地链路：三份自制PDF，Docling/E5/Qdrant/Wiki存储真实，LLM内存Mock。命令 `uv run --extra rag --offline python scripts/verify_literature_hybrid.py --output data/task44/acceptance`；验证三路上下文不同、回源、冻结、取消、重建/删除后历史与SSE撤销。
- [x] 独立端口4184启动 `scripts/serve_literature_workbench.py`，生产前端真实Playwright流程；查看桌面/390px截图和布局、切换/刷新/取消/证据预览/旧答案失效。禁止全fixture浏览器冒充真实集成，不操作8000。
- [x] 验证受影响pytest、前端Vitest/typecheck/build、Ruff/mypy、pre-commit全hooks、`git diff --cached --check`。只对相关改动回归，不跑无关R统计套件。
- [x] 更新本计划、使用说明、current-state和42–44复盘；记录获授权试跑的真实结果，明确ENGINEERING_COMPLETE与REAL_COMPARISON_PENDING。显式暂存任务44文件，提交 `feat(任务44): ...`，核验Git及renv SHA256，然后停止。

## 实际结果

工程步骤全部完成；核心后端99 passed，前端42 tests，真实离线API退出0、真实UI最终1 passed(1.5m)，静态及8项pre-commit通过。已查看桌面/390px截图。实际供应商小试验按停止条件完成：最小DeepSeek探测成功，首Wiki请求连接失败、usage未知；台账2次、23454消息输入bytes，stopped=true，三组各10 NOT_RUN。没有真实准确率/独立盲评结果，不能称质量验收完成；完整60题未运行。失败重建历史撤销、按声明裁剪、HTTP参数及参考跨chunk映射均先红后绿。所有详细命令和真实结果见current-state与42–44复盘。

## 父会话最终验收（2026-10-16）

- [x] 审阅实现/修复提交、调用台账和真实三组三十条结果；核验同条件及关键原文挤出实例，未以Mock或COMPLETED统计准确率。正式专家盲评待做，小样本未证明混合稳定优于RAG。
- [x] 新跑35项聚焦回归通过（19.42s）；真实本地API验证输出 `data/task44/parent-local-20261016-b` 退出0。检查已有真实UI记录/原文与390px截图，未重跑或冒称新浏览器验收。具体命令见current-state。
- [x] 更新current-state及42–44复盘。保持默认RAG、49/50调用台账与未知usage，不追加供应商调用，不开始45；本次文档检查/编号提交后停止自动跟进。

## 停止条件

### 任务44故障修复跟进（2026-10-16）

用户询问如何解决真实连接失败，授权故障调查与修复，不领取45。旧台账2次/stopped保留，不自动重发。调查本地SDK缓存和脚本探测/后端调用的事件循环差异；用本机HTTP/1.1假服务器、假Key复现“首探测成功、跨循环后续APIConnectionError→RuntimeError/Event loop is closed”。先加入连续两次调用的回归红灯，再将探测移入TestClient现有后端portal。验证4项预算/参考/keep-alive回归、静态和hooks，记录结论及历史底层异常缺失的限制，任务44编号fix提交。真实复验必须另有明确继续授权，沿用原50总预算与台账，不能清零旧失败或换目录绕过停止。

- [x] 追加人工恢复台账与未知在途拒绝回归；旧失败和usage未知原样保留，用户已明确答“继续，沿用原50次总预算”。
- [x] 输出截断、模型导航候选和孤立短标签过滤先红后绿；保持输出2000与逐条精确原文引用检查。DeepSeek JSON模式使用实际SDK HTTP Mock验证。
- [x] 相关回归 `uv run --offline pytest tests/unit/knowledge tests/integration/api/test_wiki.py tests/integration/api/test_knowledge_retrieval.py tests/integration/api/test_workbench_knowledge.py tests/unit/workbench/test_turn_service.py -q -p no:cacheprovider --basetemp data/task44/repair-regression --tb=short`：114 passed in39.42s。首次广回归误写不存在test_evaluation.py，0 tests/退出1，纠正路径后得到有效结果。Ruff通过，mypy112 source files通过。
- [x] 同台账受控恢复退出0：49/50调用、584607消息bytes；Wiki成功，rag10完成/wiki9完成1失败/hybrid10完成，30问全分母，盲评材料已导出但未评分。保留旧未知usage，恢复后没有新连接失败，不追加剩余1次，不启动45。最终文档、8 hooks及暂存检查后编号fix提交。

用户已答“你觉得ok就行，模型有什么用什么，你直接决定”，授权自行选择现有配置与3–5篇真实论文、10题三组试跑。全部探测、Wiki构建、问答、失败与未知请求共最多50次，单次输出最多2000 token；应用消息内容每次最多32000 UTF-8 bytes、累计1600000 bytes，不将字节上限说成供应商token/费用保证。预留30次问答，构建和探测最多20次。全局台账先持久预留，不自动重试；未知传输失败停止后续调用。后端正常解析系统凭据，代理不打印或转交Key。完整60题未授权。真实质量仍需独立盲评，不把合法引用或Mock当语义准确率；不要求hybrid胜出。任何范围扩展到45、视觉理解、图数据库或统计执行均停止。保留用户renv原哈希和根runs，不push/merge。
