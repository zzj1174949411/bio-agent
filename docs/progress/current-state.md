# Bio-Agent 当前状态

**最后更新：** 2026-09-08

**当前分支：** `agent/bio-agent-mvp`

**开发 worktree：** `.worktrees/bio-agent-mvp`

**当前阶段：** Task 15 本地流程已接通；用户于 2026-09-08 决定先跳过真实模型 API 实验，后续自行接入。以 Mock Planner 验证本地完整流程；远端发布与剩余手工演示尚未关闭。

## 恢复工作时先做什么

1. 进入 `.worktrees/bio-agent-mvp`。
2. 阅读根目录 `AGENTS.md`、已批准设计、实施计划和本文件。
3. 运行 `git status --short --branch` 和 `git log -5 --oneline`。
4. 保留 Task 15 当前工作，先查看本文件末尾的范围调整与发布状态。
5. Task 15 故障修复单独收尾；用户新增工作台需求正在设计，按下文已确认的 Web/GEO 方向继续，不混入当前修复提交。自动模型测试仍使用 Mock；真实调用仅在用户联调任务范围内进行。剩余发布检查通过前不标记 Ready for review。

## 已完成

- 已批准 Bio-Agent MVP 架构设计；设计提交为 `c996ca2`。
- 已创建包含 15 个编号任务的实施计划；计划提交为 `5d59be6`。
- 已忽略 `.worktrees/` 和本地文件 `BIO_AGENT_ARCHITECTURE_MEMORY.md`。
- 已创建分支 `agent/bio-agent-mvp` 及项目本地隔离 worktree。
- 已通过 `AGENTS.md` 固化跨会话读取、执行、验证和交接协议。
- 已把 Task 0 登记到实施计划并标记完成。
- 已安装 `uv` 和 uv 管理的 Python 3.12，并将项目固定到 Python 3.12。
- 已建立 `src/bioagent` 包、项目依赖、开发工具配置和 `uv.lock`。
- 已通过先失败后通过的包版本测试验证 `bioagent.__version__ == "0.1.0"`。
- 已启用 pytest、ruff 和 mypy 质量门禁，并补齐本地环境、缓存和运行产物忽略规则。
- 已定义只允许 bulk RNA-seq/DESeq2 的 `AnalysisPlan`、比较方向和分析选项契约。
- 已定义运行状态枚举和显式转换表，阻止 `DRAFT` 绕过队列直接进入 `RUNNING`。
- 已将运行状态与 `PASS / WARN / FAIL` 科学 QC 状态分离，并为 QC issue 保留结构化证据。
- 已集中定义 DeepSeek/Ollama、API、运行目录、checkpoint 和 Rscript 环境配置。
- 已实现按 `.csv` / `.tsv` 扩展名选择分隔符的显式 Dataset 解析契约。
- 已保真解析 feature ID、sample ID 和 metadata 文本，并严格拒绝字段数与表头不一致的数据行。
- 已实现基于 UUID4、固定内部文件名、后缀白名单和解析后路径边界检查的 `DatasetRepository`。
- Dataset 写入后会计算并持久化 counts 与 metadata 的 SHA-256，供后续 provenance 使用。
- 已实现浅层不可变 `DatasetValidation`，返回清洗后的整数 counts、按 counts 顺序重排的 metadata、结构化 QC 和全零 feature 数量；冻结容器不代表内部 DataFrame 深度不可变。
- 已用稳定错误码覆盖重复 ID、负数、非整数、非有限值、R integer 越界、样本集合不匹配、factor/level 错误、低重复数和零文库。
- metadata 确定性重排会记录 `METADATA_REORDERED` 审计事件；全零 feature 会记录 `ZERO_FEATURE_REMOVED`。
- 已完成任务 1–3 整体复盘：实现仍遵循 LLM 与确定性计算分离、强类型契约、安全路径和 provenance 边界，未引入任务 4 或多 Agent 运行时逻辑。
- Task 3.1 已拒绝重复 metadata 列名并返回稳定 `DUPLICATE_METADATA_COLUMN`，selected factor 重复不再泄漏 pandas 裸 `ValueError`。
- `DatasetRepository.paths()` 与 `hashes()` 现在每次读取都复算 counts 和 metadata 的 SHA-256，篡改时抛出 `DatasetIntegrityError`。
- `QCReport` 现在按 issues 最高严重级别强制聚合 status；report、issue 与 issues tuple 均冻结，构造后不能破坏该不变量。
- `.coverage` 已加入 `.gitignore`；后续 Execution Controller 的计划验收条件已明确要求重新核对仓库哈希、从磁盘解析并重新运行 validator，不信任旧 `DatasetValidation` 快照。
- 已实现使用 UUID4 的 `ArtifactManager`，为每个 run 创建 `input/`、`plans/`、`attempts/` 和 `report/` 受控目录。
- artifact ID 统一使用 POSIX 相对路径，拒绝绝对路径、Windows drive、反斜杠、空路径、`.`、`..` 和解析后越界路径。
- `write_bytes()` 与确定性 `write_json()` 返回实际写入字节的 SHA-256 和相对路径，manifest 不保存主机绝对路径。
- 已定义冻结且复制时重新校验的 `ArtifactRecord`、`ApprovalRecord`、`AttemptRecord` 和 `RunManifest`；manifest 覆盖输入哈希、软件版本、Git commit、计划/审批、比较参数、时间、状态、QC、attempt 和产物哈希。
- manifest 先完整写入同目录 `manifest.json.tmp`，再通过 `Path.replace()` 原子替换；替换失败时旧 manifest 保持不变且临时文件被清理。
- Task 4.1 将 POSIX 相对路径、路径穿越和 Windows 文件名规则集中到同一校验器；`ArtifactManager` 与 `ArtifactRecord` 统一拒绝保留设备名、NTFS ADS、非法/控制字符及尾随空格或点。
- `RunManifest` 的 input hashes、software versions 与 comparison 现在保存为不可原位修改的验证后快照；写 manifest 前会从全部字段重建模型并重新验证。
- 顶层 `status`、`qc` 和 `ended_at` 必须与 `attempt_id` 指向的 attempt 一致，构造和写盘边界均覆盖冲突回归测试。
- Task 5 已建立隔离的 R 4.5.2 / Bioconductor 3.22 renv 环境，锁定 DESeq2 1.50.2、apeglm 1.32.0、jsonlite、pheatmap 和 testthat。
- Task 5 的 R 输入校验覆盖样本集合/重复 ID、feature ID、非整数/负数/非有限 counts、零文库、缺失 factor、两水平限制和比较方向，并使用稳定错误码。
- Task 5 已实现确定性的 `run_deseq2()`、`write_deseq2_outputs()` 和固定 200 基因 fixture；metadata 会按 counts 列顺序重排，比较方向覆盖 AD/Control 与 Control/AD。
- Task 5 的设计公式使用固定内部列名，不把用户提供的 factor 字符串交给 R formula 解析；回归测试覆盖带表达式字符的恶意列名。
- Task 5 已实现仅接受一个 JSON 参数文件的 `r/deseq2/run.R`，严格白名单、不执行 JSON 中的代码或路径表达式，并登记 15 个 CSV/JSON/PNG/PDF/TXT 产物。
- Task 6 已实现严格、冻结且复制时重新校验的版本化 `ToolSpec`；Registry 只加载 DESeq2，拒绝未知字段、非固定参数、重复输入、不安全入口和不安全产物路径。
- Task 6 已实现 `shell=False`、参数向量调用的 `RRunner`；入口、参数和 attempt 均在项目根内解析，stdout/stderr 写入 attempt 独立日志，超时、取消、启动失败和非零退出使用稳定错误类型。
- Task 6 的 Runner 只继承 R/Windows 运行所需环境变量，并仅允许显式 R/renv 环境覆盖，避免把 DeepSeek 等应用 Secret 传入 R 子进程。
- Task 6 已实现受控 DESeq2 参数 JSON 适配和确定性输出 QC；检查 15 个必需产物、固定 CSV 字段、feature/sample 身份、结果/样本行数、数值范围、PCA、size factor、显著结果与 execution summary，`padj = NA` 按比例记录 WARN。
- 已完成任务 4–6 整体复盘：artifact/provenance、固定 R 工具、Registry/Runner/QC 三层边界可独立测试，LLM 仍未进入执行边界，也未实现任务 7 或任务 9 的编排逻辑。
- Task 7 已实现 DeepSeek/Ollama 模型工厂；DeepSeek 缺少、为空或仅含空白的 API Key 时使用稳定错误拒绝，校验后仍把原 `SecretStr` 传给构造器，测试通过 Mock 构造器保证无网络访问。
- Task 7 已定义最小 `PlanningDatasetSummary`，只包含 dataset ID、feature/sample 数量与经过约束的分类水平，不接受上传文件自由文本或额外字段；分类水平保存为可正常 JSON 序列化的深层不可变快照。
- Task 7 已实现 `AnalysisPlanner`：系统提示固定 bulk RNA-seq 双组 DESeq2 范围和 numerator 相对 denominator 方向，禁止任意代码、formula、跳过审批或自动更换统计方法。
- Planner 使用 `with_structured_output(AnalysisPlan)`；模型返回 Pydantic 实例时先转成 Python round-trip payload，再执行 `AnalysisPlan` 校验，防止同类实例跳过重验。首次 schema 失败只追加不含原始 input/context/url 的清洗错误并重试 1 次，第二次失败向调用方抛出 `ValidationError`。
- Planner 在调用模型前从完整 dump 重建并重新验证可信 summary，阻止 `model_copy(update=...)` 绕过；模型返回后确定性核对 dataset ID、factor、恰好两个观测 levels 和比较集合，语义错误不向模型重试，也不会把模型或用户任意代码传入执行层。
- Task 8 已实现严格的 UUID4 `WorkflowInput` 与受约束审批恢复命令；初始输入不能注入 status、plan、approval、attempt 或输出字段，同一 thread 不能被第二份初始输入覆盖，thread ID 与 run ID 必须一致。
- Task 8 已实现显式 LangGraph 节点与路由：可信摘要加载、计划生成与重验、人工审批 interrupt、受控执行、QC 重验、报告和完成；验证错误进入 `await_user`，执行错误进入 `failed`，拒绝与取消不会调用 executor。
- 审批支持 approve、revise/modify、reject 和 cancel；计划修订递增 `plan_revision`、清除旧审批并再次 interrupt，非法修订保持 `AWAITING_APPROVAL`，旧 revision 不能批准新计划。
- executor 只接收 JSON 深复制的隔离状态，只能返回 QC；不能原位或通过返回值覆盖计划、审批、状态、attempt 或报告。缺失、非法或 `FAIL` QC 进入 `FAILED`，仅 PASS/WARN 在确定性报告完成后转为 `COMPLETED`。
- 获批时 checkpoint 当前 plan revision、规范化 plan hash、可信 actor 与带时区的决定时间；`attempt_id` 只由 Task 9 的执行边界在真正开始 attempt 时生成。
- Task 8 已实现独立 SQLite checkpoint context manager，以及 UUID4、解析后边界、payload 身份、状态、唯一临时文件、fsync、原子替换和失败清理保护的 `RunRepository`；run.json 仅作为 API 查询索引，科研证据仍由 manifest/artifact 保存。
- Task 9 已实现规范化 plan hash 与包含 run、plan 和输入哈希的 execution key；Controller 在任何执行副作用前重新验证审批 action、revision、hash、actor 和决定时间。
- Execution Controller 每次从 DatasetRepository 重新核对 SHA-256、从磁盘解析并运行确定性 validator；已有 manifest 会先绑定 dataset 与输入哈希，任何不一致均在覆盖 input snapshot 前拒绝。
- 每个执行 attempt 使用独立 UUID4 目录，持久化 parameters、attempt、QC、stdout/stderr 和工具产物哈希；R 失败或取消也返回带 attempt_id 的结构化终态，并保留旧 attempt 证据。
- 完整且语义一致的已完成 attempt 可复用且不会再次调用 R；缺失、篡改或参数不一致的证据会创建新 attempt。损坏 manifest 被稳定拒绝且不会覆盖，遗留 RUNNING attempt 会恢复为带 `EXECUTION_INTERRUPTED` QC 的 FAILED 记录并进入下一份 manifest。
- Task 9 已实现进程内 `ThreadPoolExecutor(max_workers=1)` 队列、execution key 在途去重、立即返回 job ID、确定性状态、排队取消和协作式运行中取消；关闭队列会把尚未开始的 job 标记为 CANCELLED。
- 工作流执行节点只接受可信 `ExecutionResult`，普通 mapping 即使包含合法 UUID4 也不能伪造 attempt/QC；FAILED/CANCELLED 结果会保留 attempt_id 与稳定错误码。
- 已完成任务 7–9 整体复盘：LLM 只生成受约束计划，LangGraph 只负责编排与审批，Controller/Registry/RRunner/QC 负责确定性执行和 provenance；边界仍符合已批准 MVP，未进入任务 10 API 或多 Agent 运行时范围。
- Task 10 已实现 FastAPI 应用工厂和集中依赖装配；测试可注入 repository、graph、controller、job runner 与 readiness，不读取真实模型密钥。
- 已实现 dataset 上传/校验、run 创建/查询/计划、审批/取消、artifact 列表/下载以及 health/ready 全部 MVP 路由；批准立即返回 202 并交由单 worker 队列执行。
- 上传边界会在 multipart 解析前检查请求长度，并限制单文件字节、表格行列数；完整 pandas 解析与确定性校验在可超时强制终止的独立进程中执行。
- artifact 下载只接受由 manifest 相对路径和哈希派生的不透明 ID，重新解析受控路径并复算 SHA-256；未完成运行、未登记产物、路径穿越与篡改均返回稳定错误。
- API 以 per-run 锁保护审批、排队、注册和取消竞争；worker 持久化 RUNNING，关闭时持久化取消状态，进程重启时会先验证完成态 manifest 及全部已登记产物哈希，再决定恢复 COMPLETED 或标记 FAILED。
- Task 11 已实现离线可用的确定性 HTML 报告，固定展示 DESeq2 方法、比较方向、样本与 feature 数、阈值、QC、软件版本、前 10 个结果、当前 attempt 图表和相对下载链接；Jinja2 自动转义用户可控文本。
- `ReportSummary.from_artifacts()` 只从当前 manifest 登记的 `execution_summary.json` 与 `all_results.csv` 原始字节构造 summary；每次渲染或生成摘要前都会重新核对 SHA-256、解析内容并逐字段比较，拒绝跨 run、跨 attempt、手工构造、复制或构造后篡改。
- 可选 LLM 只接收比较方向、样本数、显著基因数、QC issue 和前 10 个结果的白名单 JSON；模型输出只能逐行选择由这些字段确定性派生的带角色、带 JSON 引号事实句，无法注入新统计数字、未执行方法、因果或临床结论。
- LLM 不可用或输出违反约束时生成稳定 WARN，并保留完整确定性报告；模型错误详情不会写入报告。报告只链接当前成功 attempt 的产物，不混入失败重试残留。
- Task 12 已实现纯 HTTP 的 Streamlit 客户端，固定使用 `httpx.Client(base_url=settings.api_base_url, timeout=30)` 调用既有 dataset、run、approval、cancel 和 artifact API；界面不导入 workflow、execution 或 R Runner。
- Streamlit Session State 只保存 dataset ID、当前 run ID、plan revision 和页面选择，不保存运行历史、DataFrame、API Key、HTTP client、模型或执行对象。
- 已实现 New Analysis、Plan Review、Run Monitor、Results 和 Run History 五个 MVP 页面；计划页明确显示 numerator 相对 denominator，并支持批准、修改和拒绝，监控页每次刷新从 API 轮询并支持取消。
- Results 会从完成态 run 获取 QC，通过不透明 artifact ID 下载并展示 PNG 与确定性 HTML 报告，同时为全部产物提供下载；下载文件名拒绝路径分隔符。
- Task 12.1 已新增只读 `GET /api/v1/runs` 项目级历史端点，可按合法 `RunStatus` 精确筛选全部分析运行；非法状态返回 422。
- `RunRepository.list_entries()` 只枚举直接 UUID4 子目录，重用现有读取与路径边界校验，按 `run.json` 修改时间降序返回摘要，并以 `RUN_INDEX_INVALID` 隔离损坏项。
- 完成态列表会重验 `RunManifest` 并核对 run、dataset、attempt、plan revision、状态和完整 QC；一致时返回 `VERIFIED` 与 manifest 完成时间，缺失或不一致时保留 run、标记 `INVALID` 并返回 `RUN_MANIFEST_INVALID`。
- 状态筛选只影响合法 runs，不隐藏任何完整性 issues；API 响应不包含用户目标、完整计划、主机路径、manifest 全文或原始异常。
- Run History 每次通过 HTTP 获取项目级摘要，显示 dataset、状态、QC、revision、attempt、证据强度和时间，并可把一个历史 run 选为当前 run；不再依赖或缓存浏览器会话 run ID 列表。
- Task 13 已新增 8 个具名固定 eval cases，覆盖正常比较、方向歧义、未知分组、多因素、自动换工具、跳过审批、非法 JSON 单次修复和文件内提示注入；每个案例都声明 `plan`、`reject` 或 `clarify` 结果以及 executor/model 调用次数。
- 参数化 Agent eval 使用脚本化 ChatModel 驱动真实 `AnalysisPlanner` 的 schema 重试和 metadata 语义校验，并使用真实 LangGraph 审批门与受信任 `ExecutionResult`；未审批和不支持请求的 executor 调用次数均为 0。
- Task 13 端到端测试使用固定 200 基因数据、FakeChatModel、真实 LangGraph、真实 SQLite、真实 `ExecutionController`/`RRunner` 和临时 artifact 目录；审批前暂停，批准后实际运行 DESeq2，并核对 AD 相对 Control 方向、15 个必需产物、全部 manifest artifact/input 哈希和相同计划幂等复用。
- Task 13 恢复测试在 attempt 与日志创建后注入进程级崩溃，再以同一 SQLite/thread ID 和新 graph/controller 实例恢复；旧 RUNNING attempt 被封存为 FAILED，新 attempt 使用不同 UUID 并成为成功 manifest 当前 attempt，旧 stdout/stderr 保持原字节不变。

- Task 14 已提供 `scripts/check.ps1`：从脚本位置解析项目根目录，frozen 同步 Python 环境，显式检查全部原生命令退出码；默认跑全部，`-Suite Python` / `-Suite R` 与 CI 共用。
- Task 14 已固定 Ruff 0.16.3 与 pre-commit-hooks 6.0.0，启用 YAML/TOML/JSON、冲突、大小、文件名大小写和私钥检查；Ruff 不自动修复。pre-commit 已安装到仓库共享 `.git/hooks/pre-commit`。
- Task 14 CI 配置 Windows/Ubuntu Python 3.12 矩阵及独立 Ubuntu R 4.5.2/DESeq2/e2e job，使用 lockfile 缓存、只读仓库权限和 Mock LLM；R job 将恢复的库通过 `R_LIBS` 暴露给独立 attempt 中的 RRunner。
- Task 14 修复严格 renv 状态检查暴露的依赖记录问题：为动态 apeglm 增加静态依赖声明，锁定已有 renv 1.2.4，Hash 与实际安装包及既有 bootstrap 一致；统计包版本均保持原值。

## 当前环境

- 系统 Python：`3.10.11`。
- `uv`：`0.12.5`，通过 Astral 官方 Windows 独立安装器安装；Task 14 shell 已能通过 PATH 调用。
- uv 管理的 Python：`3.12.14`。
- 项目虚拟环境：`.venv`，已按 `uv.lock` 同步开发依赖。
- Rscript：`R 4.5.2`。
- DeepSeek：用户有 API，但测试必须使用 Mock，不依赖真实密钥。
- Ollama：保留接入边界，本地没有模型不影响 MVP 测试。

## 最近验证

- `uv python find 3.12` 返回 uv 管理的 Python 3.12.14 路径；`.python-version` 内容为 `3.12`。
- 红灯测试使用临时 pytest 环境运行，因 `ModuleNotFoundError: No module named 'bioagent'` 按预期失败。
- `uv lock` 成功解析 108 个包，`uv sync --dev` 成功安装项目及 107 个依赖包。
- `uv run pytest tests/unit/test_package.py -v`：1 passed，0 warnings。
- `uv run ruff check .`：All checks passed。
- `uv run mypy src`：Success，1 个源文件无问题。
- `pyproject.toml` 显式设置 `tool.uv.build-backend.module-name = "bioagent"`，避免发行名 `bio-agent` 默认映射到不存在的 `src/bio_agent`。
- Task 2 计划模型红灯：`ModuleNotFoundError: No module named 'bioagent.domain'`，符合预期。
- Task 2 运行状态红灯：`ModuleNotFoundError: No module named 'bioagent.domain.runs'`，符合预期。
- Task 2 QC 红灯：`ModuleNotFoundError: No module named 'bioagent.domain.qc'`，符合预期。
- Task 2 配置红灯：`ModuleNotFoundError: No module named 'bioagent.config'`，符合预期。
- `uv run pytest tests/unit/domain -v -p no:cacheprovider`：5 passed，0 warnings。
- `uv run ruff check src/bioagent/domain src/bioagent/config.py tests/unit/domain`：All checks passed。
- `uv run mypy src`：Success，6 个源文件无问题。
- 提交前完整回归 `uv run pytest -v -p no:cacheprovider`：6 passed，0 warnings。
- 提交前 `uv run ruff check .`：All checks passed。
- 当前环境中 pytest 缓存目录 ACL 不允许写入；验证命令禁用 cacheprovider，不影响测试收集和断言。
- Task 3 parser 红灯：`ModuleNotFoundError: No module named 'bioagent.datasets'`，符合预期。
- Task 3 validator 红灯：`ModuleNotFoundError: No module named 'bioagent.datasets.validator'`，符合预期。
- Task 3 repository 红灯：`ModuleNotFoundError: No module named 'bioagent.datasets.repository'`，符合预期。
- 代码审查回归红灯确认了 4 个问题：文本 ID 被类型推断改写、畸形行宽被静默重解释、超大 count 溢出和 metadata 重排事件缺失；均先补失败测试后修复。
- `uv run pytest tests/unit/datasets -v -p no:cacheprovider`：38 passed，0 warnings。
- `uv run pytest tests/unit/datasets --cov=bioagent.datasets --cov-report=term-missing -p no:cacheprovider`：38 passed，datasets coverage 94%。
- `uv run ruff check src/bioagent/datasets tests/unit/datasets`：All checks passed。
- `uv run mypy src`：Success，10 个源文件无问题。
- 提交前完整回归 `uv run pytest -v -p no:cacheprovider`：44 passed，0 warnings。
- 提交前 `uv run ruff check .`：All checks passed；`git diff --check` 退出码为 0。
- 独立代码审查复核：4 个 Important 全部关闭，无 Critical、Important 或 Minor，结论为可以提交。
- 当前 shell 仍需使用 `[local path omitted]` 绝对路径；沙盒内将 `UV_CACHE_DIR` 指向任务专用临时目录以避开全局缓存 ACL。
- Task 3.1 重复 metadata 列红灯：selected factor 重复触发 pandas `ValueError: The truth value of a Series is ambiguous`，非 factor 列重复未产生 FAIL；修复后的参数化测试 2 passed。
- Task 3.1 文件完整性红灯：测试收集因缺少 `DatasetIntegrityError` 失败；加入读取时 SHA-256 复核后 repository 测试 9 passed。
- Task 3.1 QC 一致性红灯：4 种 status/issues 不一致输入均未抛异常，且构造后可改写 status；加入聚合 validator 与冻结结构后，又由独立审查发现 `model_copy(update=...)` 绕过，补充 2 个 RED 测试并强制复制路径重新校验。合法复制的 serializer warning 与 shallow/deep 语义也以 RED 测试复现并修复；domain 测试最终 11 passed。
- Task 3.1 repository 测试最终 11 passed，篡改 counts/metadata 时 `paths()` 与 `hashes()` 两个公共入口均被覆盖。
- Task 3.1 定向回归 `uv run pytest tests/unit/datasets/test_validator.py tests/unit/datasets/test_repository.py tests/unit/domain/test_runs.py -v -p no:cacheprovider`：46 passed。
- Task 3.1 完整回归 `uv run pytest -v -p no:cacheprovider`：58 passed；`uv run ruff check .`：All checks passed；`uv run mypy src`：Success，10 个源文件无问题；`git diff --check` 退出码为 0。
- Task 3.1 独立代码审查的 QC copy 绕过与 repository 回归缺口均已关闭；复核提出的进度证据与 copy 语义收尾也已修正。
- Task 4 manager 红灯：`ModuleNotFoundError: No module named 'bioagent.artifacts'`，符合路径与哈希功能尚不存在的预期。
- Task 4 manifest 红灯：缺少 `ApprovalRecord` 等 provenance 模型导致测试收集失败，符合预期。
- `uv run pytest tests/unit/artifacts -v -p no:cacheprovider`：16 passed；覆盖运行目录、路径穿越、确定性 JSON、SHA-256、完整 provenance、原子替换和替换故障保护。
- Task 4 完整回归 `uv run pytest -v -p no:cacheprovider`：74 passed；`uv run ruff check .`：All checks passed；`uv run mypy src`：Success，13 个源文件无问题；`git diff --check` 退出码为 0。
- Task 4.1 Windows 特殊路径红灯：42 个参数化用例失败，仅 4 个合法路径用例通过；其中嵌入 NUL 泄漏了 pathlib 异常，其余危险名称被错误接受。共享路径校验修复后该组 46 passed。
- Task 4.1 深层修改与写盘重验红灯：input hashes、software versions 和 comparison 均可被原位修改或通过低层属性替换绕过；加入不可变快照及完整 payload 重验后 4 passed。
- Task 4.1 顶层/current attempt 一致性红灯：status、QC 和 ended_at 的构造冲突与写盘冲突共 6 个用例均未被拒绝；加入跨字段不变量后 6 passed。
- Task 4.1 定向回归 `uv run pytest tests/unit/artifacts -v -p no:cacheprovider`：73 passed；额外覆盖顶层与 attempt 共享的嵌套 QC 被低层污染时仍会在写盘前拒绝。
- Task 4.1 完整回归 `uv run pytest -p no:cacheprovider`：131 passed；`uv run ruff check .`：All checks passed；`uv run mypy src`：Success，14 个源文件无问题；`git diff --check` 退出码为 0。
- Task 5 R 定向测试：`testthat::test_dir('r/tests/testthat')` 为 31 passed、0 failed；覆盖 factor 表达式注入与 PCA 因子列名冲突回归；保留 testthat 使用 R 4.5.3 构建的兼容性警告。
- Task 5 CLI 烟雾测试：`Rscript --vanilla r/deseq2/run.R tests/fixtures/deseq2_parameters.json` 退出码 0，15 个必需产物全部存在；DESeq2 的 dispersion/局部拟合警告不影响产物生成。
- Task 5 Python 回归：`uv run pytest -p no:cacheprovider` 为 131 passed；`uv run ruff check .` 和 `uv run mypy src` 均通过。
- Task 5 R 源码解析与固定入口审计通过；runner 只 source 固定的 `functions.R`，未发现 `eval`、`system` 或 `shell` 任意执行路径。
- Task 5 按默认 implicit snapshot 重新核验 renv 时，沙盒可写缓存路径已验证有效，但 Bioconductor/CRAN 仓库网络不可达导致 preflight 拒绝；随后仅以明确的 5 个直接依赖包（DESeq2、apeglm、jsonlite、pheatmap、testthat）整理 lockfile，未把全局 R 库中的 Seurat/WGCNA 等无关包带入。
- 在 Codex 沙盒中，正常 `.Rprofile` 激活 renv 时会因 `AppData/Local/R/cache/R/renv` ACL 失败；验证使用项目 renv library 配合 `Rscript --vanilla`，未关闭 renv 重要检查。
- Task 6 初始红灯：Registry、Runner 与 DESeq2 Python 适配模块均不存在，pytest 收集得到 3 个 `ModuleNotFoundError`，符合预期。
- Task 6 审查回归红灯覆盖 ToolSpec 嵌套参数映射可修改、`model_copy()` 可绕过入口校验、额外参数/重复输入声明，以及 significant/normalized/size-factor CSV 和损坏数值/PCA 因子值未校验；均已修复并转绿。
- Task 6 定向单元测试：`uv run pytest tests/unit/tools tests/unit/execution -v -p no:cacheprovider` 为 19 passed。
- Task 6 独立审查确认无 Critical；启动文件隔离、产物实体身份和 significant results 一致性 3 个 Important 已用回归测试关闭。运行中强制终止建议与批准的 `subprocess.run()` 及 Task 9 的 preflight `Future.cancel()` 边界冲突，本任务保持执行前后取消映射，不改为 `Popen`。
- Task 6 真实 R 集成：`uv run pytest tests/integration/test_deseq2_runner.py -v -p no:cacheprovider` 为 17 passed；固定 fixture 的 `GENE_001` 在 AD/Control 比较中 log2 fold change 为正，15 个必需产物通过 Python QC。
- Task 6 完整 Python 回归：`uv run pytest -v -p no:cacheprovider` 为 167 passed；`uv run ruff check .` 和 `uv run mypy src` 均通过。
- 任务 4–6 检查点复跑 R testthat：31 passed、0 failed；仅保留已记录的 testthat 使用 R 4.5.3 构建警告。
- Task 7 初始红灯：`uv run --offline pytest tests/unit/llm -v -p no:cacheprovider` 因 `bioagent.llm` 尚不存在产生 2 个预期 `ModuleNotFoundError`，退出码为 1。
- Task 7 定向单元测试：`uv run --offline pytest tests/unit/llm -v -p no:cacheprovider` 为 16 passed；工厂构造器全部使用 Mock，无网络请求。
- Task 7 静态检查：`uv run --offline ruff check src/bioagent/llm tests/unit/llm` 为 `All checks passed!`；`uv run --offline mypy src` 为 22 个源文件无问题。
- Task 7 review 修复 A 的 RED：空 key 由 provider 抛出错误消息不符，纯空白 key 未抛异常，参数化用例 2 failed；最小校验修复后 factory 测试 5 passed，错误消息固定为 `DeepSeek API key is required`。
- Task 7 review 修复 B 的 RED：summary 嵌套 dict 可修改，copy 绕过会在模型调用后才失败，定向用例 2 failed；加入只读映射、字段 serializer 和 `plan()` 边界重验后 2 passed。
- Task 7 review 修复 C 的 RED：被 `model_copy(update=...)` 篡改为 `alpha = 2.0` 的 `AnalysisPlan` 实例被直接返回，新用例 1 failed；将 Pydantic 返回值先完整 dump 为 Python payload 再校验后 1 passed。
- Task 7 独立规格审查通过；独立代码质量审查发现的 3 个 Important 均已用回归测试关闭，最终复审无 Critical 或 Important。
- Task 7 最终门禁：llm 定向测试 16 passed；完整 Python 回归 183 passed；Task 7 定向 ruff、全仓 ruff 与 mypy 均退出 0；`git diff --check` 和 `git diff --cached --check` 均退出 0。
- Task 8 初始红灯：workflow 与 storage 模块尚不存在，定向 pytest 收集得到 2 个预期 `ModuleNotFoundError`，退出码为 1。
- Task 8 审查回归先后复现并关闭：预置 `QUEUED` 绕过审批、非 JSON 对象进入 SQLite、缺失/FAIL QC 被误报完成、executor 覆盖或原位污染状态、非法计划语义进入审批、非法 revision 错误取消、run/thread/repository 身份不一致和 Windows 路径别名等问题。
- Task 8 定向测试 `uv run --offline pytest tests/unit/workflow tests/integration/test_checkpoint_resume.py -v -p no:cacheprovider`：28 passed；覆盖审批前零执行、批准后一次执行、修订重新审批、拒绝/取消、错误路由、QC、状态隔离、RunRepository 与跨 graph SQLite 恢复。
- Task 8 完整 Python 回归 `uv run --offline pytest -v -p no:cacheprovider`：211 passed；`uv run --offline ruff check .`：All checks passed；`uv run --offline mypy src`：Success，29 个源文件无问题；`git diff --check` 退出码为 0。
- Task 8 独立规格审查与代码质量审查的全部 Critical/Important 均已用回归测试关闭；两位审查者最终复审均为 Critical 0、Important 0，未修改项目文件。
- Task 9 初始 TDD 覆盖未审批/过期审批、规范 plan hash、磁盘数据重验、幂等复用、产物篡改、失败重试隔离、execution key 去重和单 worker 取消；实现后定向测试曾达到 58 passed。
- Task 9 第一轮独立审查发现 2 个 Critical 与 6 个 Important；新增回归测试得到 12 failed、46 passed，证明输入绑定顺序、损坏 manifest、可信 executor 输出、取消/关闭语义、孤儿 attempt 恢复、失败 attempt 关联和审批审计字段均可被测试捕获。
- Task 9 第二轮复审继续发现并关闭 2 个 Important：foreign manifest 的 run ID 身份错位，以及 Controller 返回 FAILED/CANCELLED 时 Job Runner 错报 COMPLETED；对应 RED 为 3 failed，修复后 3 passed。
- Task 9 审查修复后定向回归 `uv run --offline pytest -p no:cacheprovider tests/unit/execution/test_controller.py tests/unit/execution/test_job_runner.py tests/unit/workflow/test_graph.py tests/integration/test_checkpoint_resume.py -q`：61 passed。
- Task 9 最终完整 Python 回归 `uv run --offline pytest -p no:cacheprovider -q`：244 passed；`uv run --offline ruff check src tests`：All checks passed；`uv run --offline mypy src`：Success，31 个源文件无问题。
- Task 9 最终独立复审确认全部 Critical/Important 已关闭，无新增高优先级问题，结论为可以提交；审查代理未修改项目文件。
- Task 10 初始 API 红灯：`uv run --offline pytest tests/integration/api -v -p no:cacheprovider` 收集后 10 项均因 `ModuleNotFoundError: No module named 'bioagent.api'` 失败，符合预期。
- Task 10 首轮审查发现 artifact 路径型 ID、上传资源限制、运行状态恢复和并发竞争 4 个 Important；均先补失败测试，再以不透明 ID、请求/表格限制、持久化状态与 per-run 锁关闭。
- Task 10 第二轮审查的 2 个 Important 回归红灯为 2 failed：完整解析未受超时约束，以及 stale run index 覆盖有效 COMPLETED manifest；独立解析进程和 manifest/产物哈希恢复修复后 3 项定向测试全部通过。
- Task 10 API 集成回归 `uv run --offline pytest tests/integration/api -v -p no:cacheprovider`：22 passed；OpenAPI 冒烟检查包含 `/api/v1/runs`，并由集成测试核对全部 MVP 路径。
- Task 10 最终完整 Python 回归 `uv run --offline pytest -q -p no:cacheprovider`：266 passed；`uv run --offline ruff check .`：All checks passed；`uv run --offline mypy src`：Success，35 个源文件无问题。
- Task 10 最终独立复审为 Critical 0、Important 0，可以提交；3 项 Minor（按 ToolSpec 核验恢复产物全集、补齐恢复态字段、增强 readiness 写入探针）记录为后续防御性增强，不扩大本任务范围。
- Task 11 初始红灯：`uv run --offline pytest tests/unit/reporting/test_generator.py -v -p no:cacheprovider` 因 `ModuleNotFoundError: No module named 'bioagent.reporting'` 在收集阶段失败，符合预期。
- Task 11 重试产物回归先红后绿：旧失败 attempt 的图表最初进入当前报告，新增过滤后只保留 manifest 当前 attempt 的产物链接。
- Task 11 独立审查先后复现直接 `NarrativeResult` 注入、数字角色错配、未执行方法/多语言临床结论、跨 run/hash summary、自报 attestation 和恶意 comparison/feature 标签绕过；均以失败测试复现后改为 artifact 字节重验和抽取式确定性句子约束。
- Task 11 source-hash 回归通过移除校验确认测试确实失败，恢复校验后转绿；私有 attestation 伪造测试也先以 99/199 统计篡改稳定失败，再通过原始 artifact 字节重验修复。
- Task 11 定向回归 `uv run --offline pytest tests/unit/reporting -v -p no:cacheprovider`：28 passed；定向 ruff 与 `uv run --offline mypy src` 均通过。
- Task 11 最终独立复审为 Critical 0、Important 0；审查者未修改项目文件。
- Task 11 最终完整 Python 回归 `uv run --offline pytest -q -p no:cacheprovider`：294 passed；`uv run --offline ruff check .`：All checks passed；`uv run --offline mypy src`：Success，37 个源文件无问题；`git diff --check` 退出码为 0。
- Task 12 初始烟雾红灯：`uv run --offline pytest tests/unit/ui/test_streamlit_app.py -v -p no:cacheprovider` 的 2 项测试均因 `ui/streamlit_app.py` 不存在而失败，符合预期。
- Task 12 HTTP 客户端红灯在修正测试模块装载方式后稳定为 2 failed、2 passed，失败原因为缺少 `ApiClient`；最小客户端实现后 4 passed。
- Task 12 五页行为红灯为 5 failed、4 passed，分别覆盖轻量 Session State、计划方向与审批、状态轮询与取消、QC/PNG/HTML/下载和会话 run 历史；实现后 UI 定向测试为 9 passed。
- Task 12 headless 烟雾验收使用 `uv run --offline streamlit run ui/streamlit_app.py --server.headless true --server.port 8512 --browser.gatherUsageStats false` 启动成功，`/_stcore/health` 返回 HTTP 200 和 `ok`，随后测试服务器已终止。
- Task 12 最终完整 Python 回归 `uv run --offline pytest -q -p no:cacheprovider`：303 passed；`uv run --offline ruff check .`：All checks passed；`uv run --offline mypy src`：Success，37 个源文件无问题。
- Task 12.1 Repository 红灯：`tests/unit/storage/test_runs.py` 为 3 failed、1 skipped，3 项均因 `RunRepository.list_entries()` 尚不存在失败；实现后为 3 passed、1 skipped，跳过项仅因当前 Windows 用户无创建目录 symlink 权限。
- Task 12.1 API 红灯：新增项目历史测试为 5 failed、原有 10 passed，失败均为列表 GET 尚不存在而返回 405；实现与边界补强后 `tests/integration/api/test_runs.py` 为 16 passed。
- Task 12.1 UI 红灯：`tests/unit/ui/test_streamlit_app.py` 为 5 failed、6 passed，准确捕获 `ApiClient.list_runs()` 缺失、`run_ids` Session State 残留和会话级历史；实现后为 11 passed。
- Task 12.1 issue 筛选回归先稳定复现 `RUN_MANIFEST_INVALID` 被非匹配状态过滤隐藏，再将 manifest 核验提前到 runs 筛选之前；缺失 manifest、身份不一致和筛选边界 3 项测试均通过。
- Task 12.1 定向验收：Repository、API 和 UI 合计 30 passed、1 skipped；定向 Ruff、mypy、OpenAPI GET 检查均退出 0，headless Streamlit `/_stcore/health` 返回 HTTP 200 和 `ok`。
- Task 12.1 首轮全量 pytest 因新增 `tests/unit/storage/test_runs.py` 与既有 domain 同名测试模块产生收集冲突；为 storage 测试目录增加包命名空间后完整回归为 314 passed、1 skipped。
- Task 12.1 最终 `uv run --offline ruff check .`、`uv run --offline mypy src` 和 `git diff --check` 均退出 0。
- Task 13 Agent eval 初始红灯：`tests/evals/test_planner_cases.py` 在收集阶段因 loader/harness 未实现产生预期 `NotImplementedError`；最小实现后 `uv run --offline pytest tests/evals -v -p no:cacheprovider` 为 8 passed。
- Task 13 真实端到端初始红灯：`tests/e2e/test_bulk_workflow.py` 因 real end-to-end harness 未实现产生预期 `NotImplementedError`；接入真实 SQLite、Controller、RRunner 与 DESeq2 后为 1 passed，并确认 R 只调用 1 次。
- Task 13 恢复初始红灯：`tests/e2e/test_recovery.py` 因 crash recovery harness 未实现产生预期 `NotImplementedError`；实现 attempt 后崩溃与跨 graph 恢复后为 1 passed。
- Task 13 e2e 验收 `uv run --offline pytest tests/e2e -v -p no:cacheprovider`：2 passed，包含一次真实 DESeq2 执行和一次确定性崩溃恢复。
- Task 13 完整 coverage 验收使用沙盒可写的显式 `--basetemp`：324 passed、1 skipped，总代码覆盖率 88%；跳过项仍仅为当前 Windows 用户无目录 symlink 权限。

## 阻塞项

Task 15 的具体手工审批、DeepSeek 安全配置及远端 CI 状态见末尾；Task 14 记录保留为历史证据。

Task 14 验证记录：

- 初始 TDD 为 13 failed，均准确指向脚本、CI 或 pre-commit 文件缺失；修正测试包装器的退出码传递后 13 passed。新增 renv 锁定测试先因缺少 renv 记录失败，再通过；CI 的 R 库导出断言也先失败再通过。最终定向测试为 14 passed。
- `powershell -ExecutionPolicy Bypass -File scripts/check.ps1` 退出 0：frozen sync 成功，Ruff 全部通过，mypy 37 个源文件通过；Python suite 为 335 passed、1 skipped、1 deselected；renv restore/status 通过；testthat 为 31 passed；真实 DESeq2 集成及 e2e 为 3 passed。两组 Python 检查合计 338 passed、1 skipped，唯一 deselected 项在 R suite 实际运行通过。
- 最终 CI 库路径配置修改后，14 项定向测试和全仓库 Ruff 再次通过；renv Hash 补齐后 restore/status 再次退出 0。
- `uv run pre-commit install` 成功；`uv run pre-commit run --all-files` 八个 hook 全部通过。首次下载 hooks 和写入共享 Git hooks 使用已授权工具提权；本地缓存放在任务临时目录。
- 新增文件暂存后再次执行全文件 pre-commit，八个 hook 全部通过；`git diff --cached --check` 和 `git diff --check` 均退出 0。暂存仅包含任务 14 的八个明确文件，未夹带分析数据或产物。
- 沙盒检查使用 `$env:TEMP/bio-agent-uv-cache`、`bio-agent-renv-task14`、`bio-agent-renv-sandbox-task14` 和 `bio-agent-pre-commit-task14` 分别设置 `UV_CACHE_DIR`、`RENV_PATHS_ROOT`、`RENV_PATHS_SANDBOX`、`PRE_COMMIT_HOME`；`PYTEST_ADDOPTS='-p no:cacheprovider --basetemp=runs/task14-full'` 绕开既有缓存/临时目录 ACL，不关闭任何测试断言。
- Windows symlink 权限导致原有一项测试跳过；R 保留本机 BiocManager 预加载、locale 和 testthat 构建于 R 4.5.3 的提示。严格 renv 状态和全部统计测试通过。
- renv 激活会重新生成 `renv/activate.R` 的上游空白格式；该自动改动已在验收后清除，不纳入提交。未修改 Task 15 文档、推送分支或创建 PR。

## Task 15 发布验证与阻塞

用户随后报告 run `cdb41503-c4af-4b33-99c6-923c418b3465` 质检列不匹配；只读核验两份 CSV 均缺 stat，获批参数为 `lfc_shrink=true`。原因是 apeglm 返回后验效应量时省略原始 Wald stat，而旧实现直接替换整张表。R 列/原始统计量回归先 2 failed/35 passed，真实 API shrink=true 回归先复现 INVALID_RESULT_COLUMNS。修复保留 raw results 的 stat/pvalue/padj，只替换收缩后的 log2FoldChange/lfcSE；传入批准 alpha 的 raw results，并验证 feature 对齐。README 与 HTML 明确区分后验效应量和原始检验，未修改旧 run 产物或放宽 QC。API 端到端新增 shrink 开/关两种路径。

收缩修复后完整 `scripts/check.ps1` 退出 0：Python suite 354 passed/1 skipped/1 deselected，R/端到端 5 passed，合计 359 passed/1 skipped；R testthat 37 passed，renv restore/严格 status、Ruff、mypy 均通过。真实 API 在 shrink=false/true 两种情况下均完成 QC、报告、manifest 与全文件哈希校验。独立科学/契约复核无 Important。用户需重启后端并新建运行、重新审阅审批；旧失败 run 保留审计证据。

用户新增下一阶段需求：类似 Codex 的工作台、数据库编号下载分析、可配置 Skills/MCP/多模型。已明确选择本地 Web 工作台优先、GEO GSE counts 与样本信息优先。属于下一阶段待确认设计，尚未实现；现有 Task 15 故障修复继续独立收尾。

用户启动正式后端后报告 `/plan` 返回 409。只读核验 run `d93e5f71-6ace-4e68-b179-fd5cdb26d15b` 为 `VALIDATION_FAILED/PLANNER_FAILED`；409 是尚无计划的结果。针对该故障，使用固定合成摘要手工诊断，未传用户上传内容：真实 DeepSeek 先返回 400 `This response_format type is unavailable now`，显式 function calling 后返回 400 `Thinking mode does not support this tool_choice`。规划器选择 function calling、DeepSeek 工厂关闭 thinking 后，同一合成摘要通过生产规划器得到合法 AD/Control 计划。没有打印/保存 Key，没有审批或执行该用户 run；这次定向故障诊断不等于关闭完整真实模型 UI 验收。

对应 MockTransport 回归先复现相同 400，再转绿；工厂 thinking 参数断言先失败再通过。测试仅使用虚拟凭据与 Mock HTTP，规划/策略定向回归 25 passed，Ruff 与 mypy 38 文件通过。既有 schema、数据语义、修正次数和人工审批约束保留。启动未带 reload 的旧后端需 Ctrl+C 后重新启动；原失败 run 保留历史，新建 run 生成计划。

兼容性修复后 `scripts/check.ps1` 完整退出 0：Python suite 354 passed/1 skipped/1 deselected，R 集成/e2e 4 passed，合计 358 passed/1 skipped；R testthat 31 passed，renv restore/严格 status、Ruff、mypy、8 项 hooks 均通过。独立复核无 Important，确认现有 Ollama 客户端支持 function_calling；远端发布状态仍沿用此前记录，未推送本轮修复。

2026-09-08 用户调整范围：先跳过真实模型 API 实验，把本地流程搭完整，模型接入由用户后续完成。调整后重新运行 `scripts/check.ps1` 全部门禁，退出 0：Python suite 353 passed/1 skipped/1 deselected，真实 R 集成与端到端 4 passed，合计 357 passed/1 skipped；R testthat 31 passed，renv restore/严格 status、Ruff、mypy 38 文件均通过。唯一跳过仍为 Windows symlink 权限。端到端包括审批前零执行、真实 DESeq2、HTML/manifest/全部下载哈希及崩溃恢复；未调用外部模型 API。

- 已补齐 README、Windows/Linux 启动、架构、SECURITY、MIT LICENSE、固定 Mock 演示工厂、下载核验脚本及真实浏览器 GIF。GIF 当前仅含上传、计划、待审批、历史和断连错误，明确不是完整获批运行录屏。
- 真实 API 失败测试先复现 HTML 缺失；manifest 下载测试先复现列表无相应 ID。接入 ArtifactReporter 后，真实 API/R 测试确认审批前零 attempt、审批后 DESeq2、HTML、manifest 和全部登记 artifact/input 哈希。
- 报告节点验证当前 run/dataset/attempt/revision/plan hash/QC 及全部登记产物字节；失败返回 REPORT_FAILED。manifest 的 COMPLETED 是统计 attempt 的结果，完整 API 运行还须报告发布成功；报告失败时 API 为 FAILED，保留原始统计证据。
- 恢复回归先红 7 failed/2 passed，再转绿：Controller 创建/复用执行 manifest 时清除旧报告登记但保留文件；API 重启只在当前计划与已登记 HTML/全部哈希一致时恢复 COMPLETED。所属两测试文件 45 passed。
- 报告失败、attempt/plan 错配、产物篡改与幂等发布 5 项测试通过。旧历史产物损坏仍阻止报告发布；保留证据和原哈希，必要时从原始输入创建新 run，不伪造可验证的完整包。
- 发布验收首次以 0.1 秒 GET 轮询时观察到 QUEUED 未推进；故障注入确认 RUNNING 写入异常在错误处理之外，并确认 Windows 读文件与原子替换竞争。新增 3 项失败测试后将后台状态转换纳入 try，并用 RunRepository 实例内 RLock 串行读写。单进程本地服务边界不变。
- `scripts/check.ps1` 完整退出 0：Ruff 通过、mypy 38 源文件通过、Python 349 passed/1 skipped/1 deselected，R testthat 31 passed，R/端到端 4 passed，合计 Python 353 passed/1 skipped。索引修复后 `uv run --offline pytest -q -p no:cacheprovider --basetemp=runs/task15-review-full` 为 356 passed/1 skipped（97.51 秒）；全仓 Ruff、mypy 38 源文件再次通过。
- 固定版本 pre-commit 8 个 hook 通过；旧缓存 ACL 不可读，新缓存为 `$env:TEMP/bio-agent-pre-commit-task15`，首次初始化与检查使用工具提权，未禁用检查。
- 延续 Task 14 的 UV/renv 缓存环境；R 保留已记录的 locale、BiocManager 与 testthat 构建版本提示。唯一 skip 为 Windows 目录 symlink 权限。R 激活生成的 activate.R 上游空白改动不提交。

| 真实手工验收 | 结果与证据 |
| --- | --- |
| 无 Key Mock 完整演示 | 未完成：真实浏览器已上传 fixture、生成并审阅 AD/Control 计划；run `c705a436-dad3-446a-9bf9-3b4f8421c06f`，dataset `24139df0-437e-47e2-8609-10a82a8813ee`。审批前 attempts=0。点击 Approve plan 被自动审批审查拒绝，理由是需要对这次具体审批明确授权；已向用户请求，未通过其他接口绕过。 |
| 真实 DeepSeek 结构化计划 | 按用户 2026-09-08 最新指令延后，交由用户后续接入；不再作为本阶段阻塞，不要求配置 Key。既有 Mock 接口测试保留，不声称已完成真实模型联调。 |
| 关闭 API 后 UI 可操作错误 | 已通过：实际停止 API，Results 页面显示 Cannot reach the Bio-Agent API. Check that the backend is running.；重启后 Run Monitor 恢复 AWAITING_APPROVAL，运行仍未执行。 |
| 新临时目录下载与全部 SHA-256 | 手工未完成：文档下载脚本已语法核验；真实 API 自动测试已逐个核对，但不能代替手工场景。待具体演示审批后用该 run 下载并核验。 |

已提交 `e81d007` 并推送 `agent/bio-agent-mvp`；[Draft PR #1](https://github.com/zzj1174949411/bio-agent/pull/1) 面向 main，保持 Draft，不合并。origin 已只读核验为当前登录用户自有私有仓库，权限 ADMIN；首次推送自动审查因未核验归属拒绝，补充该证据后获准。

真实首轮 CI：[push run 34184498159](https://github.com/zzj1174949411/bio-agent/actions/runs/34184498159) 的 Ubuntu Python 通过，Windows Python 失败；日志定位 `test_renv_bootstrap_is_recorded_in_lockfile` 默认 cp1252 读取 UTF-8 renv.lock 导致 UnicodeDecodeError（1 failed/352 passed）。显式指定 UTF-8 后本地14项相关测试与Ruff通过。提交 `9c27b72` 的 push run `34184798111` 和 PR run `34184801048` 已分别通过 Windows/Ubuntu Python 检查，确认编码修复有效。

首轮 R job 的真实日志随后确认环境恢复失败：DESeq2 1.50.2、apeglm 1.32.0 编译成功，但 fs 2.1.0 缺少系统 libuv，导致 fs/pkgload/testthat 安装失败。新增CI依赖断言先1 failed，再在 Ubuntu apt依赖与Linux启动文档补 `libuv1-dev`；14项门禁测试与Ruff通过。未改变renv.lock包版本，后续新提交须继续核验远端R完整结果，不能宣称全部CI通过。

最终实现的真实 API 高频HTTP轮询（0.1秒）测试再次通过，确认RUNNING索引并发修复有效。手工验收未完成，即使 CI 通过也不标记 Ready。

`c4f0960` 的 push Windows/Ubuntu Python 均通过，PR Windows job 则在后台完成测试的 `wait(timeout=2)` 超时（1 failed、352 passed），没有执行异常证据。对 Mock executor 注入 2.2 秒延迟后，旧断言稳定超时，但原任务无需重试即达到 COMPLETED；说明功能测试错误地绑定了两秒完成预算。仅将该用例的有界等待改为 30 秒，保留 HTTP 202/QUEUED 与最终 COMPLETED 断言。相同延迟实验通过；API runs 回归 23 passed，全仓 Ruff 与 mypy 38 个源文件通过。远端最新结果仍须复核。

同轮 R 恢复已通过，但严格状态检查暴露锁文件来源字段不一致：16 个 `Source=Bioconductor` 的记录残留 `Repository=https://bioc-release.r-universe.dev`，Linux 官方源安装后报告 repo 不匹配。新增来源一致性断言先 1 failed/14 passed；将这 16 个 Repository 字段规范为锁定的 `Bioconductor 3.22` 后 15 passed，未修改任何包版本或放宽 synchronized 断言。本地 Windows `renv::restore()` 与严格 `renv::status()` 均再次通过；最终远端 CI 待该修复推送后核验。

本地修复提交为 `5ffc51d`（CI 等待预算）和 `caeb339`（Bioconductor 来源）。全部 8 项 hooks 与暂存 diff 检查通过；独立复核支持只改 Repository，保留现有 Remote 回退字段。远端仍为 `c4f0960`，对应 push CI `34185874339` 已失败于上述严格 R 状态检查，不能宣称 CI 全绿。

新增阻塞：本轮推送被自动审批审查拒绝。重新只读核验当前登录为 `zzj1174949411`、origin 为同名自有私有仓库且 ADMIN 后，同一 push 仍被拒绝，理由为当前可信用户内容未明确授权目的地和 payload。未改用其他接口外发。需用户明确授权把任务 15 待推送提交发送至 `https://github.com/zzj1174949411/bio-agent.git` 的 `agent/bio-agent-mvp` 分支，再核验最新 CI；Draft PR #1 尚未包含这两项修复。R 自动生成的 activate.R 仅有空白差异，核验后获准清除。

## 任务 13–15 整体复盘（进行中）

Task 13 的路由/统计/恢复测试和 Task 14 的统一门禁提供了基线；Task 15 的真实 API 接线验收揭示“独立模块通过”不能证明最终产品流程完整，尤其报告发布和下载、崩溃恢复窗口及 Windows 文件共享。新增用例覆盖这些边界，没有改变 bulk 双组 DESeq2、人工审批、固定工具和单 Agent 架构。

手工审批仍是实际边界：代理执行手工演示需要明确授权，Mock 自动测试不是对真实用户审批的替代。真实模型能力与 Mock 策略 eval 也必须分开陈述。用户已将真实模型联调移至后续；当前本地流程包含上传校验、结构化计划、审批门、DESeq2、QC/图表/HTML、manifest 下载及恢复。远端 CI 和剩余手工演示状态独立保留，不影响这一范围决定。

## 下一任务

当前交付聚焦已搭建的 Mock 本地完整流程，真实模型 API 由用户后续接入；不再等待 Key。发布收尾仍属 Task 15：推送需前述明确授权，之后核验最新 CI；具体 UI 演示审批获准后补录结果/GIF及手工下载核验。保留 Draft PR，不直接合并。

## 新会话启动提示词

```text
继续 Bio-Agent 的任务 15 收尾。进入既有 .worktrees/bio-agent-mvp，确认
agent/bio-agent-mvp 分支，按 AGENTS.md 读取设计/计划/进度及 Git 状态。
用户已决定跳过真实模型 API 实验，后续自行接入；不要再要求配置 Key。
检查 Mock 本地完整流程；按已有授权边界收尾 UI 演示、下载 SHA-256、GIF、远端 CI，
更新进度与任务 13–15 复盘并提交。保持 Draft，不合并、不新建 worktree。
```
