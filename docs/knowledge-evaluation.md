# 模型诊断与文献三组评测

任务 42 提供诊断与原文 RAG 评测；任务 43 提供有界、带回源的 Wiki；任务 44 将 `rag`、`wiki`、`hybrid` 接入同一评测契约。工程测试与 Mock 只验证路由、边界和审计，不能证明语义正确或 hybrid 更准。真实试跑及独立评分状态见 `docs/progress/current-state.md` 与 `docs/reviews/2026-10-15-tasks42-44.md`。

## 安全诊断

聊天、Ask 和显式探测区分连接、超时、401/403 认证、402 计费请求、404 模型/路由、429 限流、400/422 协议、5xx 服务端和输出/动作校验。402 不证明余额不足；404 不证明模型名就是根因。历史 `MODEL_UNAVAILABLE` 没有原异常证据，不能回填原因或宣称已修复。

可空 diagnostic 只保存阶段、允许列表类别、HTTP status 和固定格式 opaque request ID；不保存原异常消息、响应体、URL、Key、提示词、traceback 或本机路径。旧 JSON 缺字段仍可读。前端展示统一安全解释。

## 锁定协议

`EvaluationDataset` 保留 `literature-eval.v1`，支持以下数据集：

- `formal`：严格 60 题、六类各 10 题、development 15 / heldout 45；六类是单篇事实、表格数值、跨论文、方法归纳、条件/冲突和无答案。
- `pilot`：严格 10 题，全部 development；小试验不能称正式保留集结果。
- `synthetic_example`：合成示例，只验证工具，不报告真实准确率。

每题锁定问题、answerable、参考事实、原文证据和 rubric；引用必须匹配语料 base/document/hash/parse/index revision。重复 ID、重复问题、跨 split 泄漏和失效参考直接拒绝。生成请求只含问题与冻结语料，参考答案不会送入模型。Wiki 构建输入只含语料，不看问题、参考答案或评分；评分后不自动写回 Wiki。

同一三组比较使用同一份 JSON：同语料 hash、模型 snapshot、题目/split、generation 和上下文上限。新增 `wiki_snapshots` 为每库 `{base_id,generation,page_ids}`，Wiki/hybrid 必须锁定非空 generation；纯 RAG 可无 Wiki 运行。`wiki_build` 可存构建完成的 WikiJob 数组，记录来源快照、coverage、调用数、usage 完整性、生成模型、prompt/schema/input hash 和构建限制。成本记录缺失时为 null，不把缺失算零；它是一次共享构建成本，不在三组结果中重复累计。WikiJob 必须对应同库 generation 和协议语料。

任务 44 的实现 SHA256 包含 runner、Ask、检索契约、模型适配/限额、hybrid 及所有 Wiki Python 源码；另记答案 schema hash、依赖版本及 WikiJob 自身 prompt/schema hash。比较前须完成代码更改，三组间不修改实现或协议。

## 三种真实路由

`rag` 保留原文检索；`wiki` 是消融组，只检索 CURRENT Wiki 并回源其引用，不额外调用原文语义搜索；`hybrid` 同时检索问题原文和 CURRENT Wiki，再沿 Wiki 来源链接补找原文、去重与分配预算。最终事实引用只能来自实际送入模型、仍有效的原文，Wiki 是 AI 派生导航，不能算独立研究。

普通 hybrid 缺 Wiki 可记录回退 RAG；评测禁止静默回退。server 控制严格路由，runner 还核对 actual_mode/fallback_reason，任何回退记 FAILED/EVALUATION_MODE_MISMATCH 并停止后续题目。每题记录 requested/actual mode、Wiki 快照、两路 retrieved/sent 数量、实际上下文字节、chunk/page ID、真实原文证据、最终引用和 nullable usage。

## 默认 dry-run

在开发 worktree 运行，Python 一律 `uv run`：

```powershell
uv run --offline python scripts/evaluate_literature.py --dataset evals/literature/example.json --dry-run --split all --output data/task44/rag-dry-run
uv run --offline python scripts/evaluate_literature.py --dataset data/task44/locked-pilot.json --mode hybrid --dry-run --split all --output data/task44/hybrid-dry-run
```

不写 `--live` 也默认 dry-run。合成示例未配置 Wiki 快照，因此只适合 RAG；Wiki/hybrid dry-run 要提供已锁定快照的协议。dry-run 不连接 API，不读 Key，所有题为 NOT_RUN/DRY_RUN，没有分数或真实用量。

## 有界 live runner

CLI 只接受 profile ID，不接受 Key。只连接本机 HTTP API，可用 `--api-url` 指定隔离端口；不启动、停止或重启后端。公开 profile metadata 冻结成 ModelSnapshot，凭据由后端正常解析。只发送有界文本/表格/图注；不上传原始 PDF 或图像。

官方 OpenAI endpoint 的两个固定文本模型 `gpt-4o-2024-08-06` / `gpt-4.1-2025-04-14` 保留原有保守输入 token 上界：实际消息内容 UTF-8 字节数 + 1024 framing 余量，要求 `input_tokens_per_question` 和 `--max-input-tokens`。这不是实际 tokenizer 计数。

任务 44 增加官方 DeepSeek endpoint `https://api.deepseek.com[/v1]` 的明确模型 ID：当前文档 `deepseek-flash` / `deepseek-v4-pro` 与旧官方 `deepseek-v4-flash`。配置 ID 原样发送；旧别名是否仍可用不能由文档保证，也不会自动改名。snapshot 必须已标记 thinking=disabled。控制要求如下：

- generation 中 `input_tokens_per_question: null`、`input_bytes_per_question: 32000`（可更低）和 `output_tokens_per_question: 2000`（可更低）。
- 使用 `--max-input-bytes`，不使用输入 token 预算；系统消息与 HumanMessage 的实际 UTF-8 内容总长在发送前受限，包含问题、原文和 Wiki JSON。这是应用消息内容字节，非 HTTP 整包字节。
- 真实请求绑定 `thinking:{type:disabled}`、`max_tokens<=2000`，SDK 自动重试为 0。DeepSeek 不支持的 seed 不发送；generation 中 seed=42 是协议/抽样种子，不能承诺供应商确定性。
- DeepSeek input_token_upper_bound 为 null；输入 tokenizer、隐藏计费规则和金额上界没有得到证明，不能把应用字节或输出参数冒充这些保证。实际 usage 缺失保持 null。

依据为 [DeepSeek Chat Completions 官方协议](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [官方 Codex 集成说明中的旧 ID 迁移记录](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)。本地 SDK 的 ChatOpenAI 会把 `max_tokens` 改为 `max_completion_tokens`；受控 DeepSeek 使用 SDK extra_body 顶层合并保留官方 max_tokens，HTTP Mock 测试检查真实序列化请求。未知模型/endpoint/协议仍在调用前返回 EVALUATION_LIMITS_UNSUPPORTED。普通聊天配置不被改写。

以下是一个已授权 pilot 的单组命令模板：

```powershell
uv run --offline python scripts/evaluate_literature.py --dataset data/task44/locked-pilot.json --mode rag --live --model-profile-id <UUID> --max-calls 10 --max-input-bytes 320000 --max-output-tokens 20000 --api-url http://127.0.0.1:4185 --split all --output data/task44/pilot/rag
```

Wiki/hybrid 使用同一协议、profile、限额，分别改变 `--mode` 和输出目录。每个 CLI 命令的预算独立；它不能替代跨构建、探测和三组的全局持久台账。不得循环重启命令绕过用户总预算。当前已授权小试验总上限为 50 次（包含探测、构建、问答、失败/超时/重试），每次输出最多 2000，应用消息内容累计最多 1,600,000 字节；至少预留 30 次用于三组 10 题。完整 60 题未获授权。

每次 Ask 提交前预留 1 次及完整每题输入/输出限额；失败、取消、无证据与未知 usage 不退预算。实际 usage 另记。供应商连接/认证/限流/协议/服务端失败和传输/轮询超时后停止，不自动重试；有 Ask ID 时尝试取消。参考答案、评分、Wiki 内容、PDF、索引和运行产物保留在 ignored data 目录，不进入 Git。

## 完整分母与人工盲评

bootstrap 前 checkpoint 就包含全部锁定题目；提交前持久预留及当题 FAILED/EVALUATION_INTERRUPTED_UNKNOWN，随后保存 Ask ID 并原位更新。FAILED、CANCELLED、NO_EVIDENCE、NOT_RUN 全保留；runner_finished 区分正常结束和中断。传输未知不表示未计费，须先核查本地任务。

```powershell
uv run --offline python scripts/evaluate_literature.py blind --dataset data/task44/locked-pilot.json --reports data/task44/pilot/rag/results.json data/task44/pilot/wiki/results.json data/task44/pilot/hybrid/results.json --output data/task44/pilot/blind
uv run --offline python scripts/evaluate_literature.py score --reports data/task44/pilot/rag/results.json --scores data/task44/pilot/blind/scores.csv --key data/task44/pilot/blind/manager-key.json --output data/task44/pilot/scored-rag
uv run --offline python scripts/evaluate_literature.py pair --reports data/task44/pilot/rag/results.json data/task44/pilot/hybrid/results.json --scores data/task44/pilot/blind/scores.csv --key data/task44/pilot/blind/manager-key.json --output data/task44/pilot/paired
```

blind-packet 随机打乱，仅含随机 blind ID、问题、答案、状态与原文引用/证据；移除模型/模式、检索分数、路由 audit 和 Wiki 元数据。reference-sheet 按 blind ID 提供参考事实、证据和 rubric。manager-key 单独由评测管理员保管，评分员不看模式/运行映射。答案自身可能透露方法，工具不会改写答案以遮掩事实。

人工填六指标：correct、claim_coverage、numeric_units、citation_support、unsupported_claims（越低越好）、correct_abstention。空分数是 null，不当 0；非适用说明 notes。失败/取消 correct 只能 0 或待评；NOT_RUN 不可评分但留在总分母，NO_EVIDENCE 需人工判断拒答是否正确。合法引用 ID 不是语义支持证明。

pair 检查完整题集及同协议、实现/依赖/答案 schema、模型、generation、split、Wiki snapshot/build。截取成功前缀会拒绝。输出总对数、已评/未评、胜平负和逐类分母；不齐评分标 provisional，mean_difference_all 为 null，已评均值/bootstrap 仅描述已评对。不能把它解读成完整准确率或正式质量结论；小 pilot 不能代表完整六类保留集。

## 本次有限真实试跑（2026-10-16）

故障修复后，用户再次明确授权沿用原50次总预算继续。`scripts/run_literature_pilot.py --live --resume-after-fix` 是人工授权后的恢复入口；沿用同一输出目录，追加恢复事件，保留所有旧调用和未知usage，不清零计数。有在途 `RESERVED_UNKNOWN` 时拒绝恢复。默认仍拒绝非空目录，未知传输失败立即停止，没有自动重试或模型切换。

探测与后端 Wiki/Ask 共用 TestClient 的后端事件循环，避免 SDK 缓存的异步 keep-alive 连接跨已关闭事件循环复用。本地 HTTP/1.1 假服务器与假Key可复现旧错误，新回归连续两次调用成功；旧真实失败未保存底层异常，因此不能追溯断言其唯一原因。

Wiki 的 DeepSeek 请求使用 JSON object 输出模式、简短声明提示词和原2000输出token上限，`finish_reason=length` 明确报 `WIKI_OUTPUT_TRUNCATED`，不发布残缺JSON。模型导航链接仅为候选，服务端丢弃未提供链接并计数；引用仍必须逐条匹配实际输入的chunk ID、hash和精确quote。成功响应的有界文本与finish_reason保存在ignored目录用于诊断，不保存原始供应商错误体或凭据。

本次构建显式设置 `min_context_chars=80`，跳过短于80字符的非表格片段，保留完整表格；不改变原文索引或RAG输入。`filtered_short_chunks` 记录每篇过滤数量，coverage仍以全部原文为分母；这是有限子集构建，不能称全论文覆盖。脚本按剩余全局额度缩减构建段数，始终预留30次问答。

最终恢复运行退出0：Wiki成功构建，三组30问均已运行，RAG10完成、Wiki9完成/1失败、hybrid10完成。Wiki失败题因数据缺失而拒答并返回空引用，不满足当前答案契约，保留为FAILED，不重跑。全局49次、584607输入bytes，最大单次23975；48次已知usage小计188926 token，旧第2次仍未知，总费用未知。恢复后没有新连接失败。盲评材料位于ignored `data/task44/real-pilot/blind`，HUMAN_BLIND_REVIEW_PENDING，无准确率或提升结论。三组平均每题6.62/101.94/74.89秒，包含本地检索和证据校验，不能视为供应商延迟。

初次试跑记录（修复前）：三篇真实论文48页重新解析/索引和10题人工参考已锁定。全局台账2次：最小DeepSeek探测成功，首个Wiki构建请求MODEL_CONNECTION_FAILED，usage/是否计费未知；总输入消息23454 bytes，停止后未自动重试。该次Wiki没有发布，三组各10题NOT_RUN，完整30分母保留。此记录保留为历史，不覆盖后续已授权恢复结果。完整60题仍未授权，不可换目录或重置台账重跑。

尚无Wiki时dry-run可验证计划并返回完整NOT_RUN与wiki_snapshot_status=MISSING；这不会调用模型或正文检索，也不伪造generation。live Wiki/hybrid仍要求真实冻结generation并拒绝缺失/回退。
