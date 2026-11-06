# 模型诊断与文献评测基线实施计划（任务 42）

> **面向 AI 代理的工作者：** 使用 executing-plans 在任务 42 的独立 GPT-6.1 聊天执行；每步属于同一编号，不拆会话、不启动 43。先使用 systematic-debugging 找证据，实施前运行关键红灯，结束前 verification-before-completion。

**目标：** 将可区分的模型故障从 MODEL_UNAVAILABLE 中分离，保存安全诊断信息，并建立真实 RAG 基线可复现运行/评分工具，为 Wiki 混合评测固定比较条件。

**架构：** 复用模型 Adapter、Ask API 和当前离线解析检索。确定性评测契约保存语料/问题/模式/模型/版本/预算，runner 默认 dry-run；真实调用必须显式启用并指定上限。工程验证使用 Mock，真实语义分数独立标记。

**技术栈：** Python 3.12、uv/Pydantic/pytest、现有 FastAPI/React；仅当前端错误提示改变时运行相关 Vitest/typecheck/build。所有操作在 `.worktrees/bio-agent-mvp` / `agent/bio-agent-mvp`。

## 文件与职责

- `src/bioagent/models/adapters.py`：允许列表式错误分类，区分连接、超时、认证、额度、模型/路由不存在、协议、服务端错误及内部异常；不解析或持久化原始响应消息。
- `src/bioagent/workbench/turns.py`、`models.py`、`store.py`：保留固定库/模型、动作校验与原审批；新增有默认值的安全诊断，不能把模型动作解析失败误报供应商故障。不做无关重构。
- `src/bioagent/knowledge/answers.py`、`retrieval_models.py`：Ask 终态错误采用相同分类；安全诊断包括阶段、允许列表异常类别、HTTP 状态、经过字符/长度约束的请求 ID，不含 Key/URL/正文/原始 traceback。
- `frontend/src/api/types.ts`、`frontend/src/App.tsx`、`frontend/src/features/knowledge/KnowledgeAnswer.tsx`：显示针对错误的下一步操作，不虚构已知原因；抽取共用文案模块 `frontend/src/features/models/errors.ts`，避免多个不同映射。
- `src/bioagent/knowledge/evaluation.py`：评测集校验、模式/语料快照、开发/保留划分、逐题结果与失败分母、预算控制、配对汇总；本任务只实现真实可用的 rag runner，wiki/hybrid 尚未实现必须明确拒绝执行，不能产生占位分数。
- `scripts/evaluate_literature.py`：命令行入口；仅调用配置的本机 API，默认 dry-run，不接受 Key 参数。线上执行通过 API 的 profile ID，由现有后端取凭据。
- `evals/literature/README.md`、`evals/literature/example.json`：正式60题人工标注规范和短合成示例；不得把示例当真实论文评测集。
- `tests/unit/models/test_model_profiles.py`、`tests/integration/api/test_model_profiles.py`、`tests/unit/knowledge/test_evaluation.py`：最少聚焦错误分类、敏感数据不泄漏、预算/快照/数据分割与汇总行为。
- `docs/knowledge-evaluation.md`、本计划、已批准设计、`docs/progress/current-state.md`：重跑方法、真实执行证据/未完成限制、下一步。

## 前置验收与故障事实

- 任务 41 实现 `4643fd1`；父会话运行上传边界 32 项和浏览器 usability 三项，审阅滚动/选择100/50MiB/失败重试，结果单独记录，不重复实现。
- 历史只读查询看到同一 DeepSeek profile 有成功轮次，随后4次 MODEL_UNAVAILABLE；失败耗时约1秒。仅凭这一点不能判定网络、余额、模型名或工具解析的真实根因。
- 现有 `error_code` 把连接错误、HTTP 402/404/5xx、内部 ValueError 都折叠；`turns.py` 会抛出固定 MODEL_ACTION_INVALID，必须保留该已知语义。旧失败记录不包含异常类型，不能事后捏造；新诊断只改善后续可观测性。
- 父会话此前访问本机8000被拒绝连接；启动/重启用户服务、真实供应商探测和读取Key都不在本任务自动验证范围。不能修完分类就声称用户实际故障已解决。

### 任务 42：诊断与基线

- [x] **步骤 1：验证关键红灯。** 在现有模型测试中增加连接错误、402/404、明确动作解析错误与未知异常的分类/脱敏用例。使用合成 OpenAI/httpx 异常，不发送请求。新增评测契约拒绝重复问题 ID、保留集混入开发集、hash/revision 不一致及缺少 live 预算的用例。

```python
def test_action_parse_failure_preserves_code():
    assert error_code(ValueError("MODEL_ACTION_INVALID")) == "MODEL_ACTION_INVALID"

def test_unknown_error_does_not_echo_private_text():
    assert "synthetic-private" not in error_code(RuntimeError("synthetic-private"))
```

运行 `uv run --offline pytest tests/unit/models/test_model_profiles.py tests/unit/knowledge/test_evaluation.py -q -p no:cacheprovider`；记录缺失契约或错误分类导致的失败，再实现。测试不得依靠真实 Key/网络。

- [x] **步骤 2：最小模型诊断修复。** 为明确错误建立稳定类别与前端解释；只对精确已知动作/输出错误使用语义码，不能把任意用户异常字符串当错误码。有界诊断不包含原始异常消息、聊天正文、提示词、响应体、凭据或主机路径。旧 JSON 兼容且新字段默认空；取消/终态/历史不改变。真实根因未复现时记录为尚未定位，不猜测改模型名称。
- [x] **步骤 3：固定评测协议。** 采用版本化 JSON：dataset_id、文献哈希/解析及索引 revision、每题 id/split/category/question/reference_claims/reference_evidence/answerable、生成配置和上下文上限。正式目标60题，六类各10题，开发15/保留45；示例只作契约说明，不伪造真实文献/专家参考答案。生成代码与标准答案分离，保留集不进入 Wiki 构建输入。
- [x] **步骤 4：实现 dry-run 与受控 rag runner。** CLI 至少提供 `--dataset`、`--output`、默认 `--dry-run`，真实执行必须显式 `--live --model-profile-id --max-calls --max-input-tokens --max-output-tokens`。从本机 bootstrap 获取 token，遵守 CSRF；使用已有 Ask API，不绕过权限/版本。超预算停止后续题目，失败/取消/未运行分别计数，模式未实现直接报错。若供应商不提供 usage，不把空值当零成本；实际调用预算无法可靠约束时禁止 live，而非宣称限制有效。脚本不启动真实模型、不自动抓取用户PDF。
- [x] **步骤 5：实现结果与评分表。** 保存实际模式、快照、逐题输出/证据/失败、用时、可取得的usage；输出待人工盲评表与配对结果，不以ID合法率代替事实准确率。未填写人工评分不能算作0分或已评测；报告无分数而非Mock正确率。未来wiki/hybrid接入同一契约，不复制rag结果冒充三组。
- [x] **步骤 6：聚焦验收与收尾。** 定向 Python 测试、修改的前端提示测试、必要 typecheck/build、Ruff/mypy、pre-commit 和暂存 diff 检查。示例 dry-run 验证不调用模型，Mock API runner验证一次成功、一次失败/超时和预算停止。真正基线需用户指定语料与预算，尚无授权则记录 REAL_BASELINE_PENDING；这不阻止独立 Wiki 工程开发，但最终质量验收不能跳过。

```powershell
uv run --offline pytest tests/unit/models/test_model_profiles.py tests/integration/api/test_model_profiles.py tests/unit/knowledge/test_evaluation.py -q -p no:cacheprovider
uv run --offline python scripts/evaluate_literature.py --dataset evals/literature/example.json --dry-run --output data/task42/dry-run
uv run --offline ruff check src/bioagent tests/unit/models tests/unit/knowledge/test_evaluation.py tests/integration/api/test_model_profiles.py scripts/evaluate_literature.py
uv run --offline mypy src
uv run --offline pre-commit run --all-files
git diff --cached --check
```

记录每条实际结果；明确暂存本任务实际改动清单和进度文件，提交 `feat(任务42): 添加模型故障诊断与文献评测基线`。确认 renv SHA256 保持 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`，只剩用户既有改动。提交后停止，由父会话审阅；不启动43、不push/merge，不将数据/运行报告加入Git。

## 计划自检与后续依赖

### 任务42执行前补充（必要的受限 Ask API 扩展）

现有 Ask 不接受评测冻结语料/生成上限，也不保存 usage。增加可选 evaluation 参数（旧请求默认空）：冻结 source SHA256、parse/index revision 与模型 snapshot；服务端在检索前、生成前、发布/历史读取时核验。上下文仅选完整有界 chunk，不把参考答案发送给 API。生成固定 temperature=0/seed=42/prompt rag-answer.v1，调用一次、无隐式重试。

live 预算采用逐次保守预留：总调用数及每题完整 input/output 上限在发起 Ask 前扣除，失败/超时/usage缺失也不退还。仅已知 byte-level tokenizer、无隐藏推理、支持 max_tokens 的固定 OpenAI 文本模型及官方 endpoint 可用（gpt-4o-2024-08-06 / gpt-4.1-2025-04-14）；文本 UTF-8 bytes 加1024协议余量作为输入token上界，不依赖可能联网下载的tokenizer。自定义兼容 endpoint、DeepSeek/Ollama 等本轮无可靠证明，返回 EVALUATION_LIMITS_UNSUPPORTED，发起模型调用前失败关闭；不擅自更改用户配置。实际usage可空并明示unknown，保守预留不冒充实际成本。

本轮实现独立 diagnostics.py 以避免 workbench/models → profiles → adapters 的循环依赖，并补 API 边界回归。评测 JSON 固定代码/提示词版本、范围与生成配置；正式数据必须人工核验，合成示例只验证契约。CLI 另提供 blind/score/pair 子命令，评分与生成分离。

本任务产出运行质量评测所需的工具与故障观测，不实施Wiki或混合检索，不承诺修复未经复现的实际供应商故障。任务43消费现有来源契约和本任务快照/诊断；任务44接入三模式、填写真实评测报告并做42–44复盘。所有供应商调用授权与本地语料选择须在实际运行前明确，预算未给出不能把无人回复当批准。

## 执行记录（2026-10-15）

- 已完成六个步骤；真实效果基线明确REAL_BASELINE_PENDING。本次没有真实provider/Key/PDF联调。新增安全diagnostics独立模块和必要Ask控制参数均在实现前说明；没有实施43/44。
- 初始分类/契约红灯7 failed（另有23项沙盒TEMP环境error）；环境调整后37 passed/2 missing-contract failed。Ask关键红灯4 failed/1 passed；runner/盲评红灯暴露最终停止分母漏写、截断报告与未跑题评分。独立只读审查两个P2（本机API误分类/中断分母）均补红灯修复，复核关闭；完整context JSON计量红灯也修复。
- 最终受影响Python/API集合：118 passed in25.65s。Ruff All checks passed；mypy105个源文件通过。前端19 files/40 tests passed（2.53s），typecheck/build退出0；默认沙盒TEMP缺失的失败不混入有效结果。
- 指定示例dry-run成功：NOT_RUN=1、REAL_BASELINE_PENDING，零API/模型调用；hybrid模式明确拒绝非零退出。Mock runner覆盖成功、终态失败、HTTP/timeout、预算停止、usage缺失和KeyboardInterrupt；盲评/汇总保留所有分母并拒绝截断前缀。
- 最终聚焦命令：`uv run --offline pytest tests/unit/models/test_model_profiles.py tests/integration/api/test_model_profiles.py tests/unit/knowledge/test_evaluation.py tests/unit/knowledge/test_retrieval.py tests/unit/workbench/test_turn_service.py tests/integration/api/test_workbench_knowledge.py tests/integration/api/test_knowledge_retrieval.py -q -p no:cacheprovider --basetemp data/task42/final-verified --tb=short`，118 passed in25.65s。
- 明确暂存27个任务文件后，`uv run --offline pre-commit run --all-files` **8 hooks全通过**；`git diff --cached --check`退出0。用户renv哈希未变且未暂存，不含数据/文献/索引/权重/Key/运行报告；提交后只保留用户已有renv改动，停止并交父会话验收。
