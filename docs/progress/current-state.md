# Bio-Agent 当前状态

**最后更新：** 2026-10-23

**当前分支：** `agent/bio-agent-mvp`

**开发 worktree：** `.worktrees/bio-agent-mvp`

**当前阶段：** Task49通过父窗口独立工程验收。单矩阵上传与真实公开矩阵GSE60450均可经来源/分组确认、人工审批到真实DESeq2、四图、QC、报告及摘要；不再要求用户额外提供metadata文件。三路并行审查的七项问题已修复，父最终串行边界回归22项通过；公开数据每组2只独立小鼠的WARN及展示限制保留。完整独立证据和失败复验见docs/reviews/2026-10-23-task49-parent.md，使用见docs/public-matrix.md。模型测试仍Mock，不等于真实模型效果验收；本轮完成后删除自动跟进，不进入50。

**任务44历史验收：** 44实现46a0b59、故障修复3a27695、初评记录7e6eb58；父会话新跑35项聚焦回归及真实本地链路通过，复核真实三组三十题与台账。原预算共49/50次、584607输入bytes，RAG10完成、Wiki9完成/1失败、hybrid10完成；混合未显示稳定优势且更慢，继续保留RAG默认。正式专家盲评仍HUMAN_BLIND_REVIEW_PENDING，不能宣称准确率提升或历史MODEL_UNAVAILABLE唯一根因已确定。真实GEO公网验收与Task15发布收尾独立保留。

## 恢复工作时先做什么

**2026-10-23 验收收尾：** 用户授权逐项完成、父窗口检查，并明确要求增加并行聊天。三路按文件互斥修复，父窗口是唯一Git索引/提交者；现均已停写。48/49父验收完成，已达到本轮批准的表达矩阵链路，收尾提交后删除bio-agent自动跟进。保留renv、旧49/50台账、用户8000与根runs，不自动新增编号。

1. 进入 `.worktrees/bio-agent-mvp`。
2. 阅读根目录 `AGENTS.md`、已批准设计、实施计划和本文件。
3. 运行 `git status --short --branch` 和 `git log -5 --oneline`。
4. 当前48/49均已验收；先阅读49父验收及来源说明，不重复认领或恢复已关闭执行session。后续按用户新要求制定下一任务；真实provider仍独立保留，不能消耗旧额度，不并发提交。
5. 自动模型测试使用 Mock，不读取或调用真实 Key。旧 PR 保持 Draft，本地测试通过不代表远端 CI 已通过；保留 Task 15 的历史发布记录。

## Task49 真实公开矩阵完整链路（2026-10-23）

- 父窗口独立验收：基线d366d24，真实GEO/单文件双路径各审批后1次R、批准前0次，输出20,047行、上2,794/下2,953及登记产物hash一致；独立115项基线与R21tests/44断言通过。三路修复上传替换/转置、阈值等号/NA描述、GEO正文异常/上传并发/取消发布竞态。修复后父138项通过，另1项解析超时隔离通过；随后串行21项通过/1项故障测试前置失败，增强注入命中断言与仅测试fixture预算后最终22项/174.57s全通过。前端9组件、build/typecheck、矩阵3项及公开数据2项浏览器通过。真实缓存R再跑结果SHA不变，NA证据padj3887/pvalue0。原始失败、根因未锁定部分及限制如实保留，不冒称所有历史集合最终全绿。最终全仓Ruff/mypy114与8hooks通过，详见49-parent记录。
- 起点5a03065，先编写`docs/superpowers/plans/2026-10-23-public-matrix.md`后实施唯一49；来源/命令见`docs/public-matrix.md`，完整红绿、失败尝试和限制见`docs/reviews/2026-10-23-task49.md`。仅既有worktree/agent分支，无真实LLM/Key/付费额度、依赖升级、用户8000/根runs操作或push/merge。
- 官方GSE60450作者featureCounts read counts，SOFT核实mm10/Subread、完整列名/组织/平台/阶段。GSM1480297/298 Virgin与GSM1480301/302 Lactating，均基底细胞、不同阶段独立小鼠，每组2，非同鼠基底/腔面配对比较。原矩阵27179基因/12样本及Length保留；确认排除8个其他细胞/阶段样本及Length。gzip 513592 bytes，SHA256 906b6ec4c33e95ca0ba454a3e0d07ad74e9cb7528ee38b89a9b122f5674a5f0d，URL/UTC下载审计及SOFT hash见使用说明。
- 真实暴露的兼容问题均先红灯：stream.content/超限未关闭、来源targ=self缺样本、可选目录真实空响应、gzip临时名丢内部后缀、32KiB聊天限额误拦矩阵、R未遵循Python全零去除、最终QC覆盖输入WARN、报告未显示证据数量。仅multipart矩阵上传沿既有限额；普通JSON32KiB、owner/CSRF、DNS固定/allowlist不变。R只移除本次4样本全零行，不增加低表达/方差过滤；小fixture剩余基因log2FC/p/padj与无零基线1e-10一致。
- 最终真实命令`uv --cache-dir data/task48/uv-cache run --no-sync --offline python scripts/verify_public_matrix.py --download --output data/task49/final-verification`退出0：搜索/选择/来源/下载/映射API到原READY待审批run 80198855-2d40-499d-a979-97d85b67f330，单矩阵API到7a279485-d68b-456a-9ccb-80b1fdc69d99；不额外创建第三个GEO run。Mock Planner，审批前0次R，明确批准后各1次真实R，两路径20047行log2FC/pvalue/padj在rtol1e-8/atol1e-10一致。全部产物/源映射/输入hash/报告与四图校验通过。独立缓存默认模式`--output data/task49/offline-final`也退出0，真实R1次、结果hash相同，不冒称当次GEO联网通过。
- 27179输入行中全零7132，结果20047行，16160有效padj，上调2794/下调2953（alpha0.05/no shrink/seed42/Lactating相对Virgin）；QC WARN保留全零数量/每组2样本/3887个NA padj，manifest、R日志、HTML报告及摘要可查。CSV SHA256 8127103408e0512880265c06e2d1f599326890ff1eaedc2693f67ca541fd319f。没有从结果挑选样本或基因，也不将工程数值一致当原论文全部结论复现。
- 最终pytest执行/GEO/报告/transport/矩阵/聊天集合 **187 passed in102.90s**；上次152 passed/1 WinError5文件替换失败，原单项复验1 passed in6.47s，随后整套通过。全R/testthat **21 tests/44 passed expectations/0 failed/0 errors**，保留Windows locale和包构建版本warning。专用真实数据route-fixture浏览器1280/390px **2 passed in5.0s**，不冒充现场模型/R浏览器测试；截图已看。Ruff、mypy114文件和前端typecheck通过。8hooks/cached门禁见收尾记录。
- 局限：每组仅2独立重复/正式分析宜更多；NCBI-generated counts目录、任意GEO格式、TPM/配对/FASTQ和真实模型未验收。四图已目视并与最终PNG hash一致；现有PCA长原始标签可裁切，完整ID/坐标在pca.csv，窄列CSV数值换行，未宣称投稿级排版。所有原始数据/产物/截图在ignored data/task49。renv原SHA256仍为A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A，仅留用户原改动。
- 收尾：8项pre-commit全部Passed，明确暂存计划列出的20份49文件；`git diff --cached --check`退出0后以任务49 message本地提交，提交号及提交后状态以Git为准。renv/数据/SQLite/图表/.env均不入暂存。提交后停止写入，等待父会话独立验收，不进入50。

## Task48 单表达矩阵完整链路（2026-10-23）

- 审查修复：父会话发现`dd58288`的Planner异常后矩阵仍为PLANNING；finally的UPDATE被外层事务回滚。正式红灯先跑出 **3 failed, 11 deselected in48.47s**。改为独立事务持久化FAILED/MATRIX_PLANNING_FAILED；启动将遗留PLANNING及对应turn稳定结束为FAILED/MATRIX_PLANNING_INTERRUPTED，不自动规划或新建run；失败记录重复确认409。确认JSON排序对象键后生成SHA256，键重排幂等且兼容旧确认记录。修复验证与提交结果见下条收尾记录。
- 修复验证：`uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/integration/api/test_matrices.py tests/integration/api/test_workbench.py -q -p no:cacheprovider --basetemp data/task48/fix-regression --tb=short`为 **24 passed in86.46s**；全仓Ruff通过，mypy **114 source files**通过。本轮全部Planner为Mock，未重复真实R或前端检查，统计实现及前端未变。父会话仍需独立验收，本聊天不开始49；提交门禁见下条收尾记录。
- 修复收尾：8项pre-commit全通过，仅暂存3份后端、1份测试和3份文档；`git diff --cached --check`退出0后以任务48修复message本地提交，提交号以Git为准。renv SHA256仍为A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A，留作用户原有未提交改动；不push/merge、不操作根runs或用户8000。
- 计划`2026-10-23-single-matrix.md`，使用说明`docs/single-matrix.md`，实际复核`docs/reviews/2026-10-23-task48.md`。owner/CSRF受控上传、持久化原始hash与确认、有限worker解析/转置；数值/ID/分组由确定性代码检查，raw类型和来源必须明确。确认自动生成标准数据并直接进入原Planner/AnalysisService待审批，模型方向不符拒绝。
- 前端加号单文件入口和对话表单，不需用户提供第二文件。旧pair/GEO/知识库保留；科学映射替换重置、请求代际隔离、确认不可改写，已确认dataset/turn/run可跨重启恢复。实际完成run提供哈希核验的结果摘要和继续追问草稿入口。
- 真实R+矩阵/产物API **17 passed in94.51s**，额外原聊天/知识API **18 passed in11.67s**；未批准R调用0，批准后新旧各1次，200基因log2FC/p/padj在1e-8/1e-10容差一致，四图/QC/报告/manifest SHA核验通过。完整ignored记录`data/task48/final-verification/`。
- 前端 **51 passed/23 files (11.29s)**、typecheck/build通过；默认浏览器 **16 passed/3 skipped (26.2s)**，新增矩阵结果阅读后专项 **3 passed (7.2s)**，1280/390/320px。截图`data/task48/matrix-final/`已查看。浏览器fixture与真实R分开报告，不冒称三项Docling/Wiki/hybrid服务用例已重跑。Ruff/mypy114 source files通过、8hooks/cached检查通过；提交门禁见计划。
- 限制：只支持UTF-8 CSV/TSV raw counts非配对双组，不含TPM方法/自动设计猜测/FASTQ/通用附件；未确认编辑未持久化。来源原始bytes与确认在独立SQLite，manifest绑定规范数据hash，尚无跨机来源导出。无真实模型、公网来源或任意任务效果声明。
- 保留renv SHA256 A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A，不读Key、不使用付费额度、不操作用户8000/根runs，不push/merge。48提交后停止，交父会话独立验收。

## Task47 聊天主界面与按需文件（2026-10-22）

- 起点`b5aa262`，父会话明确释放写入后先写`docs/superpowers/plans/2026-10-22-chat-workspace.md`，TDD实施唯一47。使用说明`docs/workbench.md`；不复用原型模拟回复/统计结果到生产。
- App保留项目/设置，ChatWorkspace按conversation挂载，草稿/pair文件/数据选择独立内存缓存，导航与异步代际阻止旧响应写入新聊天。迟到history与SSE合并，已完成分析不会因后来普通聊天而丢失文件；run/plan/产物从原API恢复，关闭预览不终止运行。
- 默认中心聊天无常驻右栏；左下知识库/设置，输入框选库/原有RAG-hybrid模式。加号只提供真实counts+metadata导入和明确知识库入口，不假装支持普通PDF附件或自动metadata。GEO、Wiki、Skills/MCP及模型配置能力保留。
- 真实计划参数和确认/批准、拒绝、运行状态/QC/文件链接留在对话；run cancel复用原接口，服务端revision/hash/人工审批不变。产物列表仅新增basename和固定media_type，下载仍不透明ID+hash核验。文本/CSV转义，有界读取、PNG/JPEG和sandbox HTML按需预览；原文证据侧栏撤销沿用原服务。
- 前端 **50 tests / 22 files (10.02s)**，typecheck/build通过；定向产物/工作台/分析API **23 passed (106.25s)**，模型均Mock。全部默认浏览器 **13 passed / 3 skipped (21.8s)**，真实HTTP route fixtures，含320/390px、深色、multipart导入、草稿/数据/文件隔离、审批取消恢复和100PDF批处理。三项需独立真实Docling/Wiki/hybrid服务的旧测试按既有开关跳过，不宣称已重跑真实文献链路。
- Ruff通过、mypy112 source files通过、八项pre-commit和cached diff检查通过；提交范围及记录见任务计划。截图ignored `data/task47/playwright-final2/`，已实际查看桌面、报告预览、320/390px、深色。没有真实Key/模型/R调用、依赖更新、数据库重建或根runs/用户8000服务操作。
- 限制：刷新清空本地草稿/未发送文件；历史恢复沿用现有单页窗口与最近分析，没有全历史分页/跨聊天文件汇总。预览8MiB、CSV100行/50列，未支持格式提供下载；HTML的外部资源受限，完整版本可下载。单矩阵识别、自动metadata、通用聊天附件后端和新统计均留待后续独立编号。
- 45–47工程自查已记录，父会话尚需独立验收和整体复盘；47提交后停止，不自动实施48。renv原SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`，仅作保留，不格式化/暂存。

## Task45 文献分块与证据选择（2026-10-21，2026-10-22恢复收尾）

- 起点e5da324，既有worktree/agent分支。按用户“先改看看”的授权实施唯一45，取代旧停止45说明；恢复时核验HEAD=f99bada，只保留并提交原45改动，没有回退Task46设计/进度，也没有实施47。计划 `2026-10-21-literature-chunking.md`，逐题与限制见 `docs/reviews/2026-10-21-task45.md`。
- 保留Docling解析，正文按同页同节/句子/token计数合并，目标400、正文上限450；表格完整行重复已关联元数据。新块逐元素/字段/字符区间/页码/哈希归属，模型输入用紧凑映射；不跨页合并误导旧预览。算法版本显式区分，旧索引哈希兼容；只有显式重建才迁移并撤销旧Wiki/历史答案，失败不复活。图注/OCR仍有13个超窗块、最大3239 token，沿用窗口池化，不宣称视觉理解或全部证据单窗。
- 混合原文排名优先，再在24000字节预算内补充去重Wiki来源，Wiki导航≤1/4；新增实际原文路径/仅Wiki引入/重复候选审计。A保留旧索引与真实旧Wiki，仅改合并，60/60原文候选保留（包括06第六条、09第四条），仅Wiki引入58块；没有把新分块映射到旧Wiki冒充新构建。
- 真实本地E5/Qdrant前后对照只在ignored `data/task45/comparison`，同三篇/原十道development题、同source/解析SHA与版本、同top6及24000预算。旧基线在改生产代码前锁定；评分由精确来源区间重算原payload，29/29参考可映射、未映射0、解析失败0。每组十题全部保留，无答案题不按检索命中计正确拒答。
- 锁定整段参考覆盖：旧RAG7/29→新RAG15/29，旧混合9/29→A仅合并11/29；实现代理未盲的原24项事实支持复核依次8/24、16/24、9/24、12/24，均非答案准确率或正式专家评分。新索引4217→316块，短非表块3550→16。04均值±仍未召回、06缺QC度量/3 MAD，07/08仍不完整；A观测更慢，旧混合32.59s→A43.73s/题，旧/新RAG2.20/2.17s，单轮且非受控速度基准。实际输入更多，不能脱离字节量解释提升；保留RAG默认。
- 原红灯同节合并1 failed、Git旧合并函数1 failed；沙盒asyncio卡在本机socketpair而中止，改用获准本地执行。中断前最终受影响回归113 passed in37.57s；**恢复后新跑**同集合（`--basetemp data/task45/resume-final-20261022`）为 **113 passed in58.06s**，Ruff All checks passed，mypy112 source files通过，前端typecheck退出0。模型均Mock；无UI改动，不跑全浏览器或无关R统计套件。pre-commit/cached收尾结果见下条记录。
- 本轮供应商调用0，没有读取Key/新建付费台账/消耗旧49/50额度；原台账SHA256保持A867AE72BA9D4403DA7E927341CBDBF3BF3C86658F2D6F4157BC2034D65E6BED。新答案/新Wiki真实质量比较仍需独立授权，不因此阻塞工程收尾。renv原SHA256保持A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A；根runs与用户8000服务未操作，不push/merge。下一实施任务47按上方已批准方向由父会话安排，45聊天提交后停止写入。
- 收尾明确暂存18个任务45文件，`uv run --no-sync --offline pre-commit run --all-files`八项hooks全部通过，`git diff --cached --check`退出0。计划与本记录随任务45实现提交，提交号以Git为准；未暂存renv、PDF/Wiki/索引/模型权重/答案或评测数据，预期提交后唯一遗留为用户renv改动。

## Task46 表达矩阵工作台设计与原型（2026-10-22）

- 最新审阅反馈优先：用户要求普通聊天为主，不拆分步骤页或常驻AI/结果栏。当前原型为本聊天持久目录下`chat-workspace.html`，取代首轮布局。分组、审批、运行和结果文件链接留在对话，点击文件才在右侧查看；关闭后回到完整聊天。当前只迭代任务46设计，不自动开始正式实现。
- 新版`render.py`退出0，`node verify-chat-workspace.mjs`退出0：13项检查通过，errors=[]；覆盖普通聊天/草稿/发送、附件、本地文件预览、文件标签与关闭、示例分组与审批门禁、取消和完成、新建项目/聊天、项目文件隔离、390/320px无横向溢出及深色模式。已查看桌面、文件预览、窄屏和深色截图。初次检查断言大小写/列名不符已纠正，不是原型运行错误；所有分析结果均为合成示例，无真实检索/模型/统计。
- 以下首轮布局和14项检查作为历史记录保留，不能视为用户已接受；正式方向以上述反馈和更新后的规格/计划为准。
- 用户最初要求全流程，随后明确从表达矩阵开始、不做FASTQ比对/定量，并要求先设计和看原型。试作的FASTQ模块/测试/旧文档已撤回；现有生产API、R、React没有本聊天新增实现。Task45工作区文件、renv和根runs保留。
- 设计见`docs/superpowers/specs/2026-10-22-expression-workbench-design.md`，唯一任务计划见`docs/superpowers/plans/2026-10-22-expression-prototype.md`。两种布局“分析工作台”和“对话工作台”共用上传矩阵/查找公开矩阵、样本确认、方案批准、模拟运行和结果工作区。Raw counts与TPM/log分支明确区分；后者只演示探索分析，不进入DESeq2。
- 原型位于本聊天持久目录`[local path omitted]`。本地render退出0，Chromium检查脚本`verify-expression-workbench.mjs`最终退出0：14项交互检查通过、pageErrors=[]。390px浏览器内容视口358px、scrollWidth358px；已查看桌面、来源选择、对话布局与窄屏截图。所有研究、矩阵、图表和问答都是合成演示，无下载、Key或真实计算。
- 中间原型缺陷和修复见计划记录；曾忘记render的`--force`导致退出2，纠正后重建成功。未运行无关生产统计/模型测试。下一步先收集用户对原型布局和操作的反馈，再写矩阵入口/自动metadata的正式实施计划；不自动启动FASTQ或新增统计方法。文档hooks、cached检查和提交结果以本任务Git收尾为准。
- 收尾仅暂存设计、原型计划和本进度三个文件。`pre-commit run --all-files`八项hooks全部通过；默认缓存SQLite只读失败属于环境问题，已使用授权本地执行取得真实通过结果。`git diff --cached --check`退出0，提交号以Git为准；保留Task45与renv未提交状态，不push/merge。

## Task 44 父会话独立验收与收尾（2026-10-16）

- 独立审阅46a0b59/3a27695/7e6eb58及混合上下文筛选、快照/source epoch撤销、工作台动作所属、模型调用上限与评测分母。未发现阻止工程交付的新缺陷；质量与性能限制保留，工程通过不等于效果达标。
- 新跑 `uv run --offline pytest tests/unit/knowledge/test_hybrid.py tests/unit/knowledge/test_evaluation.py tests/unit/knowledge/test_pilot_budget.py tests/integration/api/test_workbench_knowledge.py -q -p no:cacheprovider --basetemp data/task44/parent-check-20261016-b --tb=short`：**35 passed in19.42s**。首次误填不存在test_pilot.py为0 tests，纠正路径后采用上述有效结果。
- 新跑 `uv run --extra rag --offline python scripts/verify_literature_hybrid.py --output data/task44/parent-local-20261016-b` 退出0：3份自制PDF真实Docling/E5/Qdrant/Wiki存储，纯Wiki无正文search、取消、Wiki单独撤销、原文重建/删除通过；LLM仅Mock，不作语义质量证据。查看既有真实生产UI验收result.json及原文PNG/390px撤销截图，恢复、取消、撤销和SSE回放撤销均true；本次未重跑浏览器，不冒称新UI测试。
- 父会话通读三组30条答案与锁定参考，另核对06/09实际原文及sent_chunk_ids：混合确实排除了RAG第6条3000 HVGs/Harmony上下文和第4条13.5小时段落，实际6350/8175 bytes均未达24000上限。支持固定top6交替合并挤出相关原文这一局部诊断；不把所有缺答归于它。超图事实有改善，QC/GLMM耗时退步，表格±三组均缺答，跨论文解释不等于引用充分；无稳定整体优势。此为父会话工程代理复核，知道模式和开发过程，不是独立专家盲评，不填写正式scores或准确率。
- 只读核验三组protocol/implementation/model/generation/corpus/question_ids一致，完整30题且无回退。台账49次保留1次旧未知传输；48笔已知usage合计188926 token，未知项不按零计，总费用未知。父会话未调用供应商，不消耗剩余1次。正式60题/保留集/专家盲评未完成；仅获授权的小样本运行完成。
- 42–44整体复盘见 `docs/reviews/2026-10-15-tasks42-44.md`，使用见 `docs/knowledge-hybrid.md`。保留默认RAG；后续优化需另有任务，不扩展45。`git show --check`检查三个44提交通过，`uv run --offline pre-commit run --all-files`八项hooks通过，三个文档diff检查通过。提交仅本次三个文档，保留renv既有SHA256及根runs，不push/merge；最终暂存检查与提交号以Git为准。

## Task 44 故障修复跟进（2026-10-16）

- 基于46a0b59，保持原分支/worktree，仅处理用户“为什么、怎么办、怎么解决”及明确继续授权，不领取45。使用systematic-debugging，所有新守卫先本地红灯后实现；没有新的子代理或产品多Agent功能。
- 本地HTTP/1.1 keep-alive假服务器复现：asyncio.run首探测成功，随后TestClient后端使用SDK按endpoint/timeout缓存的异步客户端时报Event loop is closed。探测改走现有backend portal，同一循环连续调用回归成功。真实第2次未记录底层异常，不能回填唯一根因。
- 人工恢复追加事件，保留旧calls/bytes/usage未知；存在RESERVED_UNKNOWN拒绝恢复。所有调用前持久预留，仍50次、单次32000/累计1600000消息bytes、输出2000token、未知传输停止、无自动重试/换模型。用户答“继续，沿用原50次总预算”。
- 恢复后连接正常，但先遇输出JSON校验、未提供导航链接、短标签混引。第4次输出2000token，截断仅为推断（旧响应缺finish_reason）；现增加DeepSeek JSON object、简短声明提示词和明确length拒绝发布。导航只接受服务端已提供候选，丢弃计数，不影响原文引用约束。第11次ID/hash匹配而两条quote不匹配实际text，严格拒绝未发布。
- Wiki输入新增可选min_context_chars，默认0兼容；本次80，跳过非表格短标签、完整保留表格，不改RAG原文索引。coverage以全部原文为分母并记录filtered_short_chunks。剩余额度动态缩段并预留30问，成功响应有界内容/finish_reason写ignored，原始异常体和Key不落日志。
- 本地相关回归114 passed in39.42s；过滤专项先1 failed/14 passed，后38 passed in19.95s。Ruff通过，mypy112 source files通过，8项pre-commit通过。初次广回归误用不存在路径为0 tests/退出1，纠正后取得有效114通过；全工作区diff检查包含用户renv既有空白，最终以明确任务文件的cached检查为准，不修改renv。
- 真实恢复已退出0，同一data/task44/real-pilot。成功Wiki用7次、54530输入/4017输出token；coverage分别30/508、30/2331、29/1378 chunks，过滤307/2141/1102短块，均truncated。综合输入17/89 chunks，导航丢弃0；有限覆盖不代表全篇结论。
- 最终台账49/50次、584607消息输入bytes，最大单次23975 bytes，输出限额始终≤2000。48响应/1旧MODEL_CONNECTION_FAILED；48次已知usage小计173271输入/15655输出/188926总token，旧第2次usage和总费用仍未知，不按零计。无新的传输故障、无在途预留；stopped=false表示本次正常结束，默认非空目录仍拒绝重跑，不追加剩余1次。
- 三组同题、同语料/模型/Wiki快照、实现与schema hash已只读核验；均live且没有fallback，完整30分母：rag10 COMPLETED，wiki9 COMPLETED/1 FAILED，hybrid10 COMPLETED。Wiki pilot_04模型拒绝从缺失Table2摘录编造数字，返回空citations，违反当前ModelAnswer至少一条引用契约而报MODEL_OUTPUT_INVALID；不重试、不删题、不当正确答案计入。blind-packet/reference-sheet/scores/manager-key已生成，评分仍空，HUMAN_BLIND_REVIEW_PENDING。
- 实测每题平均耗时rag6.62s、wiki101.94s、hybrid74.89s（含检索/校验，非仅供应商延迟），Wiki/混合本地链路明显慢；本轮不扩大到性能改造。只读审计与简要结果保存在ignored operator-audit.json/operator-summary.md。最终文档和提交检查见本任务fix提交；不push/merge，不改用户8000服务或renv。
- 用户追问“效果呢”后只读复核30条答案及锁定参考，初评见ignored `data/task44/real-pilot/preliminary-effect-review.md`，没有新增调用，正式scores仍空。混合补全超图基础事实，但QC参数及GLMM耗时反而漏答，尚无稳定优势；表格±三组均未答出，无答案剂量题三组均拒答。实际audit证明固定top6交替合并将RAG第06题第6条QC流程片段、09题第4条13.5小时段落挤出，context分别6350/8175 bytes，未耗尽24000预算。跨文献综合更流畅也不代表引用充分（缺MASLD支持段）。这是参与实现的代理初评，非独立专家盲评；不生成准确率/显著性，不修改实现或启动下一任务。

## Task 44 Wiki+原文混合检索与评测（2026-10-16，初次记录）

- 起点a33685b，指定worktree/agent分支；先writing-plans、再executing-plans执行唯一44。子代理分别负责工作台UI、评测和语料准备，未增加产品多Agent编排。初始红灯缺hybrid模块；不重复42/43、不push/merge、不开始45。
- CURRENT Wiki用BM25/本地E5独立检索，页面/同库链接补找原文，与原文检索轮流合并去重；纯wiki不调用正文search。上下文独立原文/派生预算，完整chunk和声明选入，按实际原文筛掉无法回源的Wiki陈述，记录retrieved/sent数量、字节及chunk/page IDs。正常无Wiki显式回退原文，实验禁止回退；rag默认，Wiki不算独立研究，引用合法不当语义正确。
- 对话持久rag/hybrid模式；提交冻结模式、库、原文revision、Wiki generation/page集合和模型。模型action无mode/scope/path权限；新增来源不扩展在途轮次。读取/生成/预览/SSE重新校验。source epoch让失败/取消重建也永久撤销旧答案，补红灯1 failed/4 passed后修复；重启中断清空原文与派生上下文。旧记录字段默认兼容，普通聊天/GEO/分析审批保留。
- 独立审查修复两处：Wiki未随实际原文裁剪声明（红灯1 failed/3 passed），普通回退仍保留Wiki引入原文（改为重新仅用原文候选）。DeepSeek SDK真实HTTP Mock先复现None字段仍被序列化，再去掉seed/max_completion_tokens字段，保留官方extra_body.max_tokens及thinking disabled；不改用户配置、不承诺未知token/费用上界。实现hash含混合、Wiki、快照契约和受控供应商源码。
- 三模式评测保持相同hash/模型/上下文/题目；增加10题pilot（全development），保留正式60题六类各10与15/45隔离。Wiki成本/覆盖/版本记录；参考不进入构建/生成，评价不写回Wiki。盲评移除模式/检索分数，未填评分null，失败/取消/NOT_RUN全分母，配对拒绝成功前缀。无Wiki的dry-run仍保留分母并标MISSING，live失败关闭。
- 最终真实离线API命令 `uv run --extra rag --offline python scripts/verify_literature_hybrid.py --output data/task44/acceptance-final` 退出0：三份自制PDF真实Docling/E5/Qdrant/Wiki存储，LLM仅内存Mock。三种上下文实际不同、纯wiki无正文search、回源、取消、Wiki单独撤销、原文重建/删除与SSE撤销全部通过。产物仅ignored。
- 后端最终命令含hybrid/pilot预算/retrieval/wiki/evaluation、三个API专项及turn_service：**99 passed in43.45s**。前端最终 **19 files/42 tests passed in53.01s**，typecheck/build退出0。Ruff All checks passed，mypy112 source files通过，pre-commit全仓8 hooks通过；最终暂存检查见本任务提交记录。未跑无关Python/R统计套件。
- 真实生产UI+独立4184服务第一次及最终均 **1 passed(1.5m)**，验证三PDF/Wiki初建、rag/hybrid、回源PNG、切换/刷新/取消、重建后历史/预览/SSE撤销与1280/390px布局；已查看最终原文/窄屏截图。中间复跑遇默认5s图像等待失败，trace显示PNG请求尚未完成而非已返回错误；等待对齐renderer15s+校验启动边界，仍要求真实PNG完整加载且可见。随后遥测监听在刷新后读取已销毁response body使测试提前退出，修正监听导航竞态后最终成功；产品代码不因这两项测试修正改变。自建4184验收服务收尾关闭，用户8000未操作。
- 用户已直接确认向DeepSeek发送三篇选定论文（HDCTI、单细胞差异分析假发现、MASLD→MASH，48页）的有界摘录，10题/三组/全局50次、输出2000、消息输入单次32000/累计1600000 bytes。独立隔离库重新解析索引；人工参考含19元素/29支持子串，两表格题查看PDF。跨chunk参考先红灯再精确完整覆盖重映射；不使用Mock替代真实论文。
- 真实结果：`data/task44/real-pilot/global-ledger.json` 为 **2次、23454输入bytes、stopped=true**。第1次最小探测成功（14输入/5输出/19总token）；第2次Wiki首段23426 bytes、输出限额2000，MODEL_CONNECTION_FAILED，diagnostic=connection、HTTP/request ID均null、usage未知。此笔按可能计费保留，不退款、不重试。Wiki发布失败，无真实答案；rag/wiki/hybrid均10个NOT_RUN，共30完整分母。REAL_COMPARISON_PENDING，无准确率、无独立盲评结果；最小探测不能证明大输入/完整协议或历史故障根因已修复。
- 构建预检原需13调用（探测+构建最多20，预留30问）：三篇覆盖90/508、92/2331、104/1378 chunks，均truncated，页面输入范围分别1–4、1–6、1–3；因第1构建请求失败，这些只是计划覆盖，不能说已完成摘要。所有原文、Wiki输入/索引/台账/答案/参考均ignored，无Key入Git。
- 使用/启动/API见 `docs/knowledge-hybrid.md`，三组工具见 `docs/knowledge-evaluation.md`，整体复盘见 `docs/reviews/2026-10-15-tasks42-44.md`。唯一应保留的未提交用户文件是renv/activate.R，SHA256仍A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A；根runs未操作。
- 收尾明确暂存37个任务44文件，`git diff --cached --check`退出0，暂存后 `uv run --offline pre-commit run --all-files` 8 hooks再次全部通过。未暂存renv、PDF、Wiki内容、权重、索引、台账/参考/答案、运行数据或Key。任务44提交后停止，实际commit及最终状态以Git记录为准。

## Task 43 文献 Wiki（2026-10-15）

- 父会话独立工程验收（`a940ccb`）：审阅来源quote/hash匹配、原文/模型快照、输入覆盖、调用预留、原子发布/复用、source epoch及SQL触发器级联撤销、跨库API和UI卸载隔离。新跑Wiki单元与API专项 **13 passed in17.88s**；独立真实Docling/E5/Qdrant脚本输出 ignored `data/task43/parent-acceptance-20261015`，退出0，三份自制PDF、首次5次Mock/增量2次、重启一致、重建及删除级联撤销通过。查看子会话真实浏览器记录和PDF原文/390px页面截图，layout-390为scrollWidth390/overflow空；未重复整个浏览器套件，未宣称本轮重跑该UI。`git show a940ccb --check`退出0。工程验收通过可进入44；真实供应商协议/费用/Wiki语义均仍未验证，不能把Mock摘要当效果。
- 起点 `ee974ed`，既有 `.worktrees/bio-agent-mvp` / `agent/bio-agent-mvp`；按已批准 Wiki 设计使用 writing-plans 制定单编号任务计划，并按 executing-plans 在本聊天实现。不重复42，不开始44，不新开聊天/产品多Agent编排，不 push/merge。用户 `renv/activate.R` SHA256保持 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`，根 runs未操作。
- 新增独立Wiki强类型契约、SQLite任务/输入/实际调用/页面版本/依赖/head记录。显式preflight/build冻结READY原文source/parse/index及source epoch、模型/profile、提示词/schema/input hash。上传不调用模型；预检不读凭据。每条生成陈述回指实际发送主chunk的quote/hash及库/document/element/页码；归属和匹配不作为语义蕴含保证。
- 完整chunk分段，长论文保留覆盖率和跳过/截断信息；论文页合并分段，综合按文献轮流选有界原文，页面/导出携带实际覆盖。每次系统+JSON输入有字节上限，冻结输入与发布页面各8MiB；输出返回后按字节拒收超限内容。调用前持久化预留，无隐式重试或自动模型切换；缺失usage为null/部分未知。沿用用户模型协议绑定max_tokens/num_predict，但Wiki profile协议尚未真实验证，不能承诺供应商token/费用上界，预检/UI/说明明确提示。
- 无变化SKIPPED零调用；新未READY文献只标待更新，不重复重建相同READY内容。未受影响论文页复用，受影响论文与聚合页重建；模型/profile/提示词/schema变化全量重建，避免混合快照。完整验证后事务切换generation；中途/发布失败保留旧有效版本，不生成失败占位摘要。
- 原始来源删除、parse/current/index/source/status变化与显式索引重建请求，在原事务内递归撤销当前/历史页面及聚合链接；在途索引排除出Wiki来源。source epoch阻止迟到构建发布；物理hash篡改在读取时持久撤销，恢复原始bytes也不复活旧陈述。STALE列表不返回陈述/引用/链接，页面/导出/预览拒绝。取消/重试/关闭/重启均有持久终态，重启不自动模型调用。
- 新API和管理页提供预检、开始/停止/重试、状态、论文/概念方法/主题页面、链接、固定Markdown导出及原文结构/静态PNG/PDF下载。沿用本机Host/Origin/CSRF、进程owner lease和库/UUID归属；本机知识库仍共享，未新增多用户权限系统。模型内容不生成可执行指令、路径、HTML或任意链接，不改AGENTS.md、原RAG/普通聊天、统计/GEO审批。
- 红灯：最初因Wiki模块不存在收集失败；长输入发布coverage缺失为1 failed，补齐页面/导出覆盖后通过。收尾专项先证明在途索引旧READY仍被选入（1 failed）及提示词变化仍复用旧论文页（1 failed），最小修正后最终聚焦全部通过。测试fixture导入/缺父临时目录属于环境/测试设置错误，未计为功能结果；默认uv缓存ACL失败使用已授权本地离线执行。
- 最终命令 `uv run --offline pytest tests/unit/knowledge/test_wiki.py tests/unit/knowledge/test_retrieval.py tests/unit/knowledge/test_store.py tests/integration/api/test_wiki.py tests/integration/api/test_knowledge_retrieval.py -q -p no:cacheprovider --basetemp data/task43/final-verified --tb=short` 为 **48 passed in28.90s**。Ruff **All checks passed**（既有ACL warning），mypy **109 source files通过**。KnowledgeManager Vitest **4 passed**，前端typecheck/production build退出0；不跑无关Python/R统计套件。
- 真实离线API验收 `uv run --extra rag --offline python scripts/verify_literature_wiki.py --output data/task43/acceptance-final-verified` 退出0：三份自制PDF真实Docling→E5→Qdrant，生成5页、首次5次Mock调用，选中短论文重建仅2次（长论文重建为3次，取决于实际分段），另两篇复用；原文quote核验、跨库拒绝、PNG、Markdown、SKIPPED、Mock原RAG、重启一致、索引重建和删除级联撤销均通过。产物仅ignored data，无用户PDF或Key/供应商调用。
- 真实Chromium专项 **1 passed (32.3s)**，使用独立4183 API及生产静态UI，模型均内存Mock：预检零调用→显式构建→主题/论文链接→原文PNG→导出→重建级联失效→取消。首次窄屏断言误把既有流式布局当回归，已按任务41契约修正；随后实测390px出现403px横向溢出，定位长模型名选择框，约束父label后390px/scrollWidth390且overflow空，桌面独立滚动保持。验收截图/布局JSON在ignored data/task43/ui-acceptance；自建4183服务已关闭，用户8000未停止/重启。
- 使用说明见 `docs/knowledge-wiki.md`。工程无未解决阻塞；真实语料、付费调用预算、Wiki语义质量、真实供应商协议/成本和RAG真实基线仍待验收，不能把Mock或合法引用当事实准确性。下一步仅父会话独立验收43，再安排44混合检索/聊天模式与三组真实质量比较。
- 收尾明确暂存20个任务43文件；`uv run --offline pre-commit run --all-files` **8 hooks全通过**，`git diff --cached --check`退出0。未暂存renv、PDF、权重、Wiki内容、索引、数据、报告或Key。任务43实现提交后停止，不开始44；预期唯一未提交改动仍为用户renv/activate.R（上述SHA256）。提交号与最终Git状态见本任务最后commit及交接报告。

## Task 42 模型诊断与文献评测基线（2026-10-15）

- 父会话独立工程验收（`34c5c6e`）：审阅错误分类/诊断脱敏、旧记录默认字段、Ask语料与模型快照、预算预留/未知调用停止、保留集隔离、盲评/失败分母与配对一致性。新运行 `uv run --offline pytest tests/unit/models/test_model_profiles.py tests/unit/knowledge/test_evaluation.py tests/unit/knowledge/test_retrieval.py -q -p no:cacheprovider --basetemp data/task42/parent-20261015 --tb=short` 为 **71 passed in13.35s**；独立CLI dry-run输出 ignored `data/task42/parent-dry-run`，NOT_RUN=1/REAL_BASELINE_PENDING且无API调用；`git show 34c5c6e --check`退出0，renv哈希保持。工程验收通过，可进入43；历史真实供应商故障仍未定位，实际语义基线未跑。受控live目前仅支持两款固定官方OpenAI模型，用户现有DeepSeek不能使用此评测路径；后续实际评测前必须明确支持能力/预算，不能静默换模型或假装该路径已联调。
- 起点b139e60，既有worktree/agent/bio-agent-mvp。未重复验收41；保留用户renv原改动和根runs，不push/merge、不调用真实Key/模型/用户PDF，不停止或重启用户8000服务。原始四次DeepSeek失败没有异常证据，仍不能判断余额、模型名、网络或动作解析；只修复代码已证明的语义折叠。
- 统一错误码区分连接/超时/认证/402/404/限流/协议/5xx/内部与动作/输出校验；精确固定MODEL_ACTION_INVALID保持动作语义，任意异常字符串不能成为错误码。新增diagnostic默认None兼容旧turn/Ask/probe，仅阶段、允许列表类别、HTTP status与受限opaque ID；不存原始消息、响应体、Key、URL、提示词、聊天正文、traceback或路径。前端共享解释不猜测历史原因。
- literature-eval.v1冻结语料source SHA256与parse/index、题目split/category/人工参考证据、生成配置。正式60题六类各10，开发15/保留45；重复ID/文本、跨split重复、证据所属/revision不符拒绝。示例仅两题合成契约，UUID/hash占位，不是专家标注。生成请求无参考答案，wiki_build_input仅corpus无任何题目；wiki/hybrid明确MODE_NOT_IMPLEMENTED。
- CLI默认dry-run零API访问。live显式profile及三项预算，通过本机bootstrap/cookie/Origin/CSRF复用Ask。Ask可选evaluation参数在提交/检索/生成/发布/历史核验冻结来源与模型，统计审批不变。仅两个官方固定OpenAI文本模型可约束预算，DeepSeek/Ollama/自定义兼容配置评测live以EVALUATION_LIMITS_UNSUPPORTED在模型调用前拒绝；不修改它们的普通聊天配置。固定temp0/seed42/prompt版本，完整evidence JSON字节上限，实际消息UTF8 bytes+1024作为保守token上界，绑定max_tokens且无SDK自动重试；每题完整预算预留、失败/超时/usage缺失不退还，usage未知不算零。
- 输出模式/快照/版本/实现hash、逐题状态/答案/证据/耗时/usage，完整分母在bootstrap前持久化；提交前保存中断未知状态及预算，不自动恢复重试。盲评packet与参考sheet无模型模式，manager-key单独保管；空CSV评分不当0，未跑题禁止评分，失败正确率不能为1。汇总逐类分子/分母，配对胜平负/差值/固定seed bootstrap区间，未配齐明确provisional。
- 红灯：首次新增分类/脱敏/契约为7 failed（另23沙盒临时目录权限error，不能算功能结果）；转为可用离线执行后37 passed/2 missing-contract failed。Ask预算/快照红灯4 failed/1 passed；runner暴露checkpoint停止分母漏写；自检完整上下文JSON红灯1 failed。独立只读审查发现本机API拒绝误分类与中断checkpoint丢分母两个P2，分别红灯1 failed和2 failed后最小修复；复核确认两个P2关闭，无新问题。
- 最终定向命令覆盖models profiles、API profiles、evaluation、retrieval/Ask、turn service、workbench knowledge与knowledge retrieval API：**118 passed in25.65s**。最终Ruff **All checks passed**；mypy **105 source files通过**。Vitest **19 files/40 tests passed（2.53s）**，typecheck/production build退出0。沙盒Vitest初次TEMP ENOENT属于环境失败，重跑取得上述有效结果；uv默认缓存/pytest临时目录权限失败也单独记录，最终测试使用可用权限且全为离线Mock。
- 示例dry-run：**NOT_RUN=1、REAL_BASELINE_PENDING**（默认development），未访问API；hybrid CLI明确MODE_NOT_IMPLEMENTED并非零退出。所有Mock分数仅测工具，不作为语义准确率。使用说明docs/knowledge-evaluation.md，人工协议evals/literature/README.md。真实基线阻塞项只为用户尚未指定授权语料和调用/token预算、供应商实际可用性尚未验证；不阻止后续独立Wiki工程，但44效果验收不能跳过。
- 收尾明确暂存27个任务文件后，pre-commit **8 hooks全通过**，`git diff --cached --check`退出0（完整聚焦命令见任务42计划执行记录）。用户renv SHA256仍为A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A且未暂存；未提交数据、PDF、索引、模型权重、Key或运行报告。任务42提交后停止，下一步仅父会话独立验收与安排43。

## Task 41 交接（2026-10-12）

- 父会话独立验收（2026-10-15，`4643fd1`）：`uv run --offline pytest tests/unit/knowledge tests/integration/api/test_knowledge.py -q -p no:cacheprovider` **32 passed in 31.78s**；真实 Chromium usability 专项 **3 passed (8.6s)**，覆盖聊天/左右列独立滚动、设置/知识库可达、100份自动上传/失败重试与390/1000宽度。数据输出 ignored `data/task41/parent-20261015`，浏览器使用固定 API fixture，无供应商/用户文献调用。审阅共享限制、上传循环冻结目标/卸载隔离和桌面/窄屏布局；`git show 4643fd1 --check` 退出0，用户renv哈希未变。任务41验收通过；此结果不等于100篇真实解析或供应商模型质量验收。
- 用户在 RAG 收尾后新报告整体滚动和 PDF 上传无原因禁用，明确授权本任务，并追加“单份 50 MiB，一次可选择 1–100 份”的需求。起点 `cb7ccba`，既有 worktree / `agent/bio-agent-mvp`；没有重新实施任务 38–40，不启动 42、不 push/merge。
- 桌面 grid/flex 视口及收缩轨道约束使聊天、项目和结果各自滚动，标题/输入区保持可用；设置与知识库独立滚动。小于 1200px 恢复页面流，390/1000px 下资源、底部设置与文献按钮可达。基础知识库控件沿用现有样式，长文件名/消息换行。
- 统一 `knowledge/limits.py`：单份 50 MiB、HTTP 每请求最多 4 份、总请求 201 MiB（含 multipart 余量）、UI 每次最多 100 份。上传路由、Store、Docling `max_file_size` 与请求中间件共享常量；前端读取 `/api/v1/knowledge/limits`，旧后端缺此接口时明确提示更新，不猜测上限。
- 一次点击自动逐份串行上传，显示文件大小、已上传/总数及每份状态；失败继续，超限跳过，其余可传，仅重试失败项。上传目标库冻结，上传期间禁切库；停止/卸载阻止后续请求并忽略迟到回调。已发请求允许结束，已成功导入文献保留，解析取消沿原机制。页面关闭后未上传/失败列表不持久化，重新选择时服务端同库 SHA256 去重。
- readiness 的解析/检索独立读取，一项失败不会遮蔽另一项；等待、操作中、文件数量与大小均给可见原因。解析仍串行、200 页、600 秒、4 GiB RSS、100 MiB 输出；文件大小不保证解析内存或质量。
- 红灯：组件 **4 failed**；后端边界 **2 failed (6.53s)**（旧 Store 10 MiB 与请求 41 MiB）；修正浏览器 fixture/工具 buffer 传输后 **2 failed, 1 passed**，捕获 timeline 无独立滚动与提示缺失。
- 验证：知识库后端单元及上传 API **32 passed (12.50s)**；前端 **18 files / 39 passed (2.57s)**，最终上传专项 **4 passed (1.38s)**；默认 Playwright **8 passed, 1 skipped (12.3s)**，最终三项专项 **3 passed (6.9s)**。新用例真实 Chromium 检查 scrollTop、window.scrollY=0、各列坐标/标题输入可见、设置/文献底部与390/1000px无横溢出；100 份合成 File 自动发送、失败继续及仅失败重试通过。截图 ignored `data/task41/final`，已实际查看。
- `npm run typecheck` / 最终 `npm run build`、Ruff、mypy **103 source files** 通过。默认沙盒 uv 访问拒绝与 Vitest worker 临时文件 ENOENT 使用已授权执行环境解决；Ruff 测试行长已修正。八项 `uv run --offline pre-commit run --all-files` 全通过，17 个任务文件明确暂存后 `git diff --cached --check` 退出 0，renv 未暂存。默认沙盒不能写 worktree index.lock，使用已有 Git 提交授权完成暂存和提交。
- 限制：100 份浏览器上传使用 API fixture，合成 4×11 MiB/50 MiB 后端测试禁止解析；本次不声称100篇真实解析/检索质量，不调用真实供应商或使用用户 PDF。用户8000服务未停止/重启；新 dist 已构建，必须由用户重启后端并刷新才可应用新限制。根 main runs 未动；renv 用户哈希保持 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。

## Task 40 交接（2026-10-12）

- 父会话独立验收（`6d799ce`）：审阅每对话选库、固定库/索引/模型快照、动作及读取归属、取消/切换隔离、可信引用与撤销、PDF/图表预览及既有审批边界。新运行 `uv run --extra rag --offline pytest tests/integration/api/test_workbench_knowledge.py -q -p no:cacheprovider` 为 **7 passed in 8.73s**；`git show 6d799ce --check` 退出 0。独立服务数据目录为 ignored `data/task40/parent-ui-20261012`，真实本地 UI 用例 **1 passed (1.1m)**：三份合成 PDF 使用真实 Docling/E5/Qdrant，问答仅内存 Mock；2026-10-12 UTC 12:42:17.092 开始、12:43:08.389 三份 READY、12:43:21.869 完成。六条检索命中、验证后分段、PDF/表格/图片、选择切换/刷新、重建/删除撤销三轮答案、旧资源 409、失效 SSE、窄屏通过；实际查看 PDF 页、图片和撤销窄屏截图。38–40 整体复盘通过，无阻止本轮收尾的问题；测试服务已停止，未调用真实供应商。
- 实施计划 `docs/superpowers/plans/2026-10-12-literature-workbench.md`；使用、准备、失效规则与真实 UI 重跑命令见 `docs/knowledge-workbench.md`。仅任务 40，不 push/merge/PR，根 runs 未改动。
- 工作台接入库管理、批量 PDF、解析/索引独立 readiness 与阶段、取消/重试/重建/删除；按对话保存库选择，切换/刷新恢复，安装文档可直接打开。缺可选依赖不阻塞既有聊天/分析。
- 强类型 `knowledge_ask(question)` 不允许模型选库；提交时保存服务端 READY 索引集合及模型快照，复用当轮临时客户端。新增文献不扩展本轮范围；排队/生成/历史读取时原版本失效稳定拒绝。工作台只保存 ask 引用和操作状态，不复制已验证答案或未经验证知识前言，撤销后 SSE 不重放旧答案。
- 新读取路由核对 owner、conversation/turn/ask 和实际引用，重验磁盘哈希。静态 PDF 页固定无网络子进程渲染，有时间/内存/输出限制，避免浏览器 PDF 插件被 sandbox 阻止；原 PDF 作附件下载。表格结构/图注/脚注及图片裁剪有受控预览。页面转义内容、忽略模型链接，每两秒及聚焦时撤销失效答案/打开预览。
- 定向后端 **140 passed (109.79s)**，随后仅增加旧 JSON 默认字段兼容测试，最终任务定向 **7 passed (9.27s)**；前端 **35 passed / 17 files (8.54s)**。全部浏览器 **6 passed (1.2m)**，其中真实 Docling/E5/Qdrant 与 Mock 问答流程约 1.1m，五项既有 fixture 回归覆盖模型、GEO/确认/审批及扩展。typecheck/build、Ruff、mypy **102 source files**、八项 pre-commit、暂存 diff 检查通过，详细命令与真实结果见计划。
- 真实 UI 记录与实际查看的截图：ignored `data/task40/ui-acceptance/`。三份短合成 PDF 解析/索引 READY、检索六条命中、生成与验证事件、分段答案、PDF 页像素/表格/真实 picture 裁剪、选择切换/刷新、重建/删除撤销三轮答案、旧 PDF 409 与失效 SSE 不重放、窄屏通过。模型与凭据为内存 Mock；未读取真实 Key，未做真实供应商问答验收。
- 38–40 复盘依据：解析→独立 READY→固定范围/模型→可信答案→核验预览→撤销在实际 UI 连通，统计执行仍在原人工审批边界。旧 JSON 新字段提供默认值，无破坏性迁移。剩余限制为短合成英文语料、OCR/双栏/跨页表格缺陷、图像检索措辞敏感、无视觉推理、无真实问答语义质量验收；引用归属不等于语义正确。父会话独立验收和整体复盘已完成，详细记录见整体复盘文档。
- 已保留 `renv/activate.R` 用户改动，SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。Git/Ruff 的 `.pytest-reg-final30/` 访问警告是既有 ACL，检查退出 0。提交门禁完成后只应剩该用户修改。

## Task 39 交接（2026-10-12）

- 父会话独立验收（`7fc0c02`）：审阅索引比较发布、重启/删除清理、问答指定 profile 快照、引用归属/存活核验及答案重放撤销。运行 `uv run --extra rag --offline pytest tests/unit/knowledge/test_retrieval.py tests/integration/api/test_knowledge_retrieval.py -q -p no:cacheprovider` 为 **22 passed in 15.70s**；`git show 7fc0c02 --check` 退出 0。独立真实脚本输出至 ignored `data/task39/parent-acceptance-20261012/`，退出 0：三份 PDF 解析/建索引 **44.453s**，中文正文/表格 rank 1、图片 rank 4；重启结果一致，重建/删除撤销旧证据，Mock 问答一次且 SSE 验证通过。应用末尾 RSS 943,230,976 bytes，不是峰值。用户 renv 哈希未变；未发现阻止进入任务 40 的问题。问答仍仅 Mock，不能把引用合法视为语义正确或宣称已完成真实供应商联调。
- 实施计划及完成记录：`docs/superpowers/plans/2026-10-12-literature-retrieval-api.md`；API、准备命令和调用示例：`docs/knowledge-retrieval.md`。
- 已固定 multilingual-e5-small revision/384 维/MIT/五个文件哈希与 optional 依赖；模型仅显式下载，运行时纯本地。分块保留原文、位置、完整表头/单位/脚注及有界相邻上下文；BM25 + dense RRF 仅检索指定库的当前 READY revision。
- SQLite 事务发布独立索引；构建失败保留旧版本，取消/删除/parse 变更拒绝发布。进程 lease 在恢复前获取；Qdrant 反序列化前检查物理存储哈希，重启清理残留 collection。READY 继续支持 parsed/assets API。独立 LocalEvidence v2 不改变旧 HTTPS/Null 检索契约。
- ask 提交时冻结指定配置，有限文本与系统规则分离；无证据不调用模型，引用必须属于实际检索集合且仍存活。答案通过完整引用验证后才分段 SSE；重建/删除使旧答案及重放失效。取消、超时和重启保留稳定终态。测试只用 Mock/内存凭据，不读取真实 Key。
- 红灯已覆盖缺失实现、真实 Qdrant 非平凡向量持久化、长表表头/上下文边界、模型伪造文件 URL、重启残留 collection；随后修复并通过。最终定向回归 **80 passed (18.73 s)**，完整 API **89 passed (173.22 s)**；Ruff 通过，mypy **100 source files** 通过。pre-commit、暂存 diff 和提交后状态见实施计划执行记录。
- 真实 API 验收：`uv run --extra rag --offline python scripts/verify_literature_retrieval.py --output data/task39/acceptance-final3` 成功。三份自制 PDF 真实 Docling→E5→Qdrant；中文正文/表格目标 rank 1，图片 rank 4（独立 caption rank 1）；重启所有命中一致，跨库隔离、重建/删除失效、Mock 问答与 SSE 通过。数据/模型/索引均 ignored，未提交。
- 限制：仅三份短合成英文 PDF，图像命中对措辞敏感；跨页表格、双栏顺序和 OCR 继承 Task 38 限制。没有视觉推理、通用语义阈值或真实供应商问答质量验收。RSS 约 899 MiB 是验收末尾采样，不是峰值。详见实验记录，不把引用合法视为答案语义正确。
- 保留用户唯一既有改动 `renv/activate.R`，SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`；不动根 runs，不 push/merge/PR，不启动 Task 40。既有 `.pytest-reg-final30/` ACL 使 Ruff/Git 扫描有访问警告，相关检查退出码为 0。

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

用户新增下一阶段需求：类似 Codex 的工作台、数据库编号下载分析、可配置 Skills/MCP/多模型。已明确选择本地 Web 工作台优先、GEO GSE counts 与样本信息优先，并于 2026-09-08 确认阶段顺序；规格与实施计划见“下一阶段设计与计划”。尚未实现新功能，Task 15 修复保留独立提交。

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

## Task 16 项目、对话和事务存储

- 工作目录为 `.worktrees/bio-agent-mvp`，分支 `agent/bio-agent-mvp`，起点 `b4724e1`；开始时工作区干净，分支领先 origin 7 个提交。
- 新增冻结且拒绝未知字段的 Project、Conversation、Message、Turn、Event；记录带 `updated_at`，消息保留 `turn_id`、dataset UUID 与 `partial`。`TurnModelSnapshot` 仅是任务 16 持久化所需的非凭据字段契约；任务 17 应复用或整合该契约，尚无 profile 管理、凭据或模型客户端实现。
- `Settings.workbench_db` 默认为 `data/workbench.sqlite`（位于现有忽略目录），与 checkpoint、run 索引和 manifest 独立。版本 0 向前迁移到 1；拒绝较新版本、未标版本的非空库、缺失关键表/索引及损坏外键，迁移失败整笔回滚，不重建旧数据库。
- `BEGIN IMMEDIATE` 同事务先检查 request 重复及 payload hash，再检查 active turn，最后写 turn、用户消息及事件；唯一索引同时保证请求幂等、单 conversation 非终态 turn 和事件序号。不同 payload 返回 `REQUEST_ID_CONFLICT`，不同请求竞争返回 `TURN_BUSY`，`WAITING_USER` 继续占用对话。
- 项目/对话支持创建、重命名和归档，不提供删除证据；消息与事件同事务保存。列表按更新时间/UUID 降序，默认 50、上限 100，游标绑定资源范围；事件按 conversation 内 seq 升序重放。新事件更新项目/对话活动时间。
- 初始红灯：定向 pytest 因 `ModuleNotFoundError: No module named 'bioagent.workbench'` 收集失败。实现后首轮发现泛型 Page 的运行时类型绑定问题，修正后 11 passed。补充回归先复现活动排序未更新和缺失唯一索引未拒绝（2 failed/13 passed），修复后 15 passed。
- 定向验收：`uv run --offline pytest tests/unit/workbench/test_workbench_store.py -v -p no:cacheprovider --basetemp=runs/task16-final` 为 **15 passed**。包含 6 连接同请求/异请求竞争、单实例跨线程、写事件故障注入回滚、20 次并发事件写入、分页同时间戳、外键所属、旧库重开、迁移原子性及 UTF-8 消息 16 KiB 边界。
- `uv run --offline ruff check .` 通过；`uv run --offline mypy src` 通过（41 个源文件）。开始时既有 storage/domain 基线为 18 passed/1 skipped，唯一跳过为本机 Windows symlink 权限。
- 既有 Python 回归：`uv run --offline pytest tests/unit tests/integration tests/evals -k 'not test_real_deseq2_runner_preserves_ad_vs_control_direction' -q -p no:cacheprovider --basetemp=runs/task16-regression` 为 **369 passed、1 skipped、1 deselected**（74.22 秒）。跳过项为原有 Windows symlink 权限；排除项是本次未改动的真实 R 集成，未重跑真实 R/testthat/e2e，不把本轮回归表述为完整统计验收。
- 公共门禁：全仓 Ruff、mypy 41 源文件、`uv run --offline pre-commit run --all-files` 的 8 项 hooks、`git diff --check` 与 `git diff --cached --check` 均通过。缓存使用 `$env:TEMP/bio-agent-uv-cache` 和 `bio-agent-pre-commit-task15`；pytest 临时文件位于被忽略的 `runs/task16-*`。Git 索引写入与旧 hook 缓存读取遇到沙盒权限后，使用获准提权完成，未关闭 hooks。
- 提交范围仅 7 个任务文件（3 个新包文件、1 个测试文件、config、计划与进度）；本地提交信息为 `feat(任务16): 建立工作台项目对话与事务事件存储`。提交后检查工作区状态；下一会话以 Git 实际状态为准。
- 范围：仅任务 16；未接 API/SSE、队列、模型配置、真实模型、GEO、Skills 或 MCP。未更改 R/统计实现，未推送、合并或修改 Draft PR；任务 18 的整体复盘尚未到达。

## Task 17 多模型配置、凭据和探针

- 起点 `1542bf4`（任务 16），worktree 为 `.worktrees/bio-agent-mvp`，分支 `agent/bio-agent-mvp`；开始时干净，领先 origin 8 个提交。使用 executing-plans、TDD 和完成前验证流程，仅领取任务 17。
- 新增 `models/{profiles,store,secrets,adapters}.py`：`ModelSnapshot` 复用任务 16 的 `TurnModelSnapshot`；profile 冻结、复制重验、公开字段白名单，URL 禁止 userinfo/query/fragment。配置进入同一个 workbench DB 的 `model_profiles` 表和独立 `model_schema_version`，不改 checkpoint 或历史 turn。
- 配置更新要求 `expected_revision`，并发覆盖返回 `PROFILE_REVISION_CONFLICT`；删除后禁止用于新请求，已保存 turn 快照保持原值。DeepSeek/Ollama 环境配置投影为固定 ID、只读 profile，不经 API 写 `.env`。
- 新增并锁定 keyring 25.7.0。`SecretStore.set/get/delete` 使用 `SecretStr`；系统后端限定 OS 凭据存储，拒绝未知、文件和链式 fallback，返回 `SECRET_STORE_UNAVAILABLE`，允许继续使用环境 profile。无凭据配置不访问 keyring；写入后 DB 仅保存内部引用，删除 profile 同时清除对应凭据。测试使用内存 SecretStore 和假 OS 后端，未访问真实系统凭据。[keyring API 依据](https://keyring.readthedocs.io/en/stable/)
- 新 `ModelAdapter` 每次请求解析配置/凭据并创建客户端，无跨 revision 或凭据缓存；DeepSeek 固定 function calling + thinking disabled，Ollama 原生 function calling，兼容服务支持 function calling/json_schema。旧工厂签名及 DeepSeek/Ollama 参数契约保留，共用 DeepSeek 参数函数。
- 固定探针仅由 `POST /api/v1/model-profiles/{id}/test` 触发，要求 `{"ok":true}`，60 秒总超时及请求超时，无自动重试/fallback，不发送用户数据。错误映射仅返回稳定白名单 code，不返回 provider body 或异常文本。
- 新 `model_routes.py` 提供分页列表、创建/修改/删除、凭据写入/清除与探针；`GET /api/v1/workbench/bootstrap` 返回随机 CSRF token，`Cache-Control: no-store`。新端点和带 Origin 的浏览器请求检查 Host/Origin；旧 API 无 Origin 客户端保持原兼容行为。新写请求只认 `X-CSRF-Token`，实际请求体最大 32 KiB，422 不回显输入。生产同源；开发需显式设置 `BIOAGENT_LOCAL_DEV_ORIGIN=http://localhost:5173` 或对应 127.0.0.1:5173 origin，精确匹配，不增加任意来源 CORS。
- TDD 红灯：两份新测试因 `ModuleNotFoundError: No module named 'bioagent.models'` 收集失败。实现后兼容 provider 的空 DeepSeek 参数触发 2 failed/33 passed，去掉该字段后通过。凭据补充回归先发现无凭据配置提前持有引用，调整为写凭据时登记、删除 profile 清理后通过。超时测试改为在 Mock 调用开始后推进可注入截止时间，避免用 10 ms 线程调度时间判断功能正确性。
- 最终定向命令为 `uv run --offline pytest tests/unit/models/test_model_profiles.py tests/integration/api/test_model_profiles.py -v -p task17_isolation -p no:cacheprovider --basetemp=runs/task17-final`，**42 passed**。覆盖 profile/快照与凭据生命周期、并发 revision、环境只读、provider 参数、401/429/超时、无自动 fallback、CSRF/Host/Origin、分页和 API/日志/DB/快照脱敏；4 项使用真实 SDK + MockTransport 验证合法/非法 function calling 和 json_schema 输出。
- 计划要求的 `tests/unit/llm tests/integration/api` 回归 **65 passed**（55.25 秒）；更广回归 `uv run --offline pytest tests/unit tests/integration tests/evals -k 'not test_real_deseq2_runner_preserves_ad_vs_control_direction' -q -p task17_isolation -p no:cacheprovider --basetemp=runs/task17-full-regression` 为 **411 passed、1 skipped、1 deselected**（73.76 秒）。跳过项为原有 Windows symlink 权限，排除项为真实 R 集成，不表述为完整统计验收。
- 全仓 Ruff 通过，mypy **48 个源文件**通过，`uv run --offline pre-commit run --all-files` 的 **8 项 hooks 全部通过**；`git diff --check`、`git diff --cached --check` 通过。UV/PRE_COMMIT 缓存沿用任务 16 的临时目录；公开 keyring 依赖下载、Git 索引和旧 hook 缓存读取使用获准提权，未关闭 hooks。
- 本地提交信息为 `feat(任务17): 增加多模型配置与系统凭据存储`，范围仅计划列出的 18 个实现、测试、依赖和状态文件；提交后核验 Git 状态，下一会话以实际 Git 为准。
- 测试隔离：仅检查到 worktree 中 `.env` 存在，未读取内容。临时插件 `runs/task17-tools/task17_isolation.py` 在测试导入前关闭 Settings dotenv、清除模型/追踪环境变量，并把旧 API 测试的 workbench DB 定位到其临时 data_dir；通过 `PYTHONPATH=runs/task17-tools` 与 `-p task17_isolation` 加载，不修改生产 dotenv 行为。首次基线插件改变默认 DB 路径导致 1 个默认值断言失败，修正隔离方式后基线 **32 passed**。临时插件与测试数据库全部位于忽略的 runs 目录。
- 本次不实现任务 18 的聊天队列/SSE/恢复，不接 GEO、Skills 或 MCP，不更改统计执行。未调用真实模型、读取真实 Key 或写真实 keyring；未重跑真实 R/testthat/e2e，不声称完成真实模型/系统凭据联调。任务 15 发布和 Draft PR 状态保留，不 push、不合并。

## Task 18 后台对话、SSE 和恢复

- 会话开始核对开发 worktree 与 `agent/bio-agent-mvp`；基线为任务 17 提交 `3bf578d`，工作区干净，未覆盖用户改动。
- 新 `TurnService` 使用独立 asyncio worker 与最多 32 个排队 turn，提交返回 202；同一请求 ID 复用原 turn，冲突请求拒绝。模型配置在入队前固定，后续切换配置不改变在途快照；消息关联 dataset ID，模型只接收有限的完整消息上下文。
- 新工作台路由提供项目/对话创建、修改/归档与分页、消息读取、turn 提交/查询/取消、澄清响应和 SSE，复用任务 17 的 Host/Origin/CSRF 保护。缺模型返回 `MODEL_NOT_CONFIGURED`，队列满 429，忙碌或旧澄清 request/revision 返回 409。
- SSE 从已提交的事件记录分批读取 100 条；`after`/`Last-Event-ID` 取较大合法值，非法游标 422，空闲 15 秒注释心跳。事件种类白名单与单行结构化 JSON 阻止正文注入控制行；断连只结束读取，不取消后台 turn。
- 部分消息与事件同事务写入；完成消息与完成 turn 同事务提交。取消先持久化终态/标记，迟到输出由存储边界拒绝。启动将未终止 turn 标为 `FAILED / TURN_INTERRUPTED`，保留部分消息，不自动重放模型请求；重复启动不重复失败事件。
- WAITING_USER 保留澄清 request/revision，只有匹配响应才能重新入队。当前 `Clarification` 仅来自可信内部 driver，普通模型文本不解析为动作；任务 19 的动作白名单、分析服务与审批衔接尚未实施。
- TDD 红灯：两份新测试因缺少 events/turns 模块收集失败。首次测试中的迟到片段同步标记放在 yield 后导致等待未结束，已中断该测试进程、前移标记并增加有界等待。复盘补充的流关闭测试先失败，随后用 `aclosing` 修复澄清提前退出时 driver 流未及时关闭的问题。
- 最终定向命令 `uv run --offline pytest tests/unit/workbench/test_turn_service.py tests/integration/api/test_workbench.py -v -p task17_isolation -p no:cacheprovider --basetemp=runs/task18-final --tb=short`：**29 passed**（3.69 秒）。覆盖慢模型与跨对话并发、幂等/快照、32 项队列上限、取消竞争、澄清版本、重启、SSE 游标/注入/分页/心跳/有界断连，以及完成事务故障回滚和 Mock driver 脱敏。
- 计划要求的 `tests/unit/workbench tests/integration/api` 回归：**92 passed**（54.85 秒）。更广命令 `uv run --offline pytest tests/unit tests/integration tests/evals -k 'not test_real_deseq2_runner_preserves_ad_vs_control_direction' -q -p task17_isolation -p no:cacheprovider --basetemp=runs/task18-full-regression --tb=short`：**440 passed、1 skipped、1 deselected**（73.31 秒）。跳过项为原有 Windows symlink 权限；排除项为真实 R 集成，不表述为完整统计验收。
- 全仓 Ruff 通过，mypy **51 个源文件**通过，`uv run --offline pre-commit run --all-files` 的 **8 项 hooks 全通过**。`git diff --check` 与 `git diff --cached --check` 通过；提交保留 hooks，下一会话以实际 Git 为准。
- 测试沿用任务 17 的忽略目录隔离插件，禁用 dotenv 读取并清除模型/追踪环境；未读取真实 `.env`/Key，未访问真实 keyring 或调用真实模型。临时数据库与插件不暂存。未重跑真实 R/testthat/e2e，未 push、合并或更改 PR。
- 本地提交信息为 `feat(任务18): 接通后台对话事件与重连恢复`，范围仅计划列出的 9 个实现/测试文件与 2 个计划/进度文件。下一任务 19 未开始。

## 任务 16–18 整体复盘

- 存储边界：工作台 SQLite 保存项目、对话、turn 与事件，模型 profile 使用独立版本表；LangGraph checkpoint 与 manifest/artifact 的科研证据职责保持独立。新增 turn JSON 字段有兼容默认值，原存储测试仍通过；请求去重、单会话非终态唯一约束和事务事件序号继续由确定性代码保证。
- 凭据边界：快照仅含非秘密配置；凭据通过系统后端/环境引用解析，聊天客户端与凭据只保留在请求内存中。任务 17 与 18 的 Mock 测试覆盖 API、日志、DB、快照不含虚拟秘密，当前改动未把凭据传入 checkpoint/manifest；未读取真实凭据验证。
- 执行边界：聊天队列独立于统计 JobRunner；API 测试显式监视并断言聊天不调用 R 队列 submit，既有队列/API Python 回归通过。本阶段未接分析动作，不会通过聊天创建统计 attempt 或代替人工批准；真实 R 运行未重验。
- 生命周期：持久化先于 SSE 投影，断连不拥有任务生命周期；取消与完成均由事务终态控制。重启仅封存中断，不重放付费调用；澄清以 request/revision 防止旧响应恢复新状态。复盘发现的提前退出流资源释放问题已按先失败后修复验证。
- 结论与限制：16–18 已达到本地单后端进程、Mock 模型及 ASGI 层验收条件，无未解决阻塞项。真实模型/系统凭据联调、前端浏览器、真实 R 的完整工作台验收留给后续计划；未将本地通过称为远端 CI 或产品全流程验收。按每三任务检查点规则暂停，不实施任务 19。

## Task 19 动作到原分析服务与审批

- TDD 红灯先确认动作模块缺失导致新集成测试收集失败；随后加入 `AssistantAction` 三分支联合类型（answer、clarify、plan_analysis），extra forbid，不接受 approve 或代码字段。动作预算限制为每轮最多 8 个结构化动作，普通文本片段不计为动作。
- `AnalysisService` 成为旧 runs API 与工作台动作共用的服务入口，保留原有 per-run 锁、审批校验、LocalJobRunner、ExecutionController、QC 和报告路径。工作台 `plan_analysis` 只接受当前会话消息中明确选择的 dataset，生成 run 后 turn 进入 WAITING_USER，统计 attempt 在人工审批前保持为零。
- 原审批端点仍是唯一启动统计执行的入口；审批完成、失败、拒绝或取消会通知关联 turn，旧 plan revision 不能批准新计划。模型输出中的“已批准”不会被解析为审批来源。
- 新增可选、向后兼容的 `AgentContext`，只保存 conversation/turn、非密钥 model snapshot、skill 名称与 SHA-256 hash、source ID；初始 run 索引和 manifest 均在受控写入边界绑定，Controller 重验已有 context，旧 manifest 缺少该字段仍可读取。skill 名称/hash 数量必须相等，hash 必须为小写 64 位十六进制。
- 任务 19 定向测试 `tests/integration/api/test_workbench_analysis.py`、工作台/turn 回归、旧 runs API、artifact/execution/workflow 回归合计 **193 passed**。覆盖模型不能批准、跨会话 dataset 拒绝、生成计划后零 attempt、原审批后 worker/QC 完成、context 快照和旧 manifest 兼容。
- Ruff 与 mypy 已通过；广泛 Python 回归 **446 passed、1 skipped、1 deselected**（85.58 秒）。跳过项为原有 Windows symlink 权限，排除项为真实 R 集成。未读取真实 Key、调用真实模型或用户数据，未执行真实 R 用户数据分析；合成 R/旧工作流验收沿用既有测试。

## 任务 16–19 整体复盘

- 工作台存储、模型 profile、聊天 turn、LangGraph checkpoint 和科研 manifest/artifact 仍各自负责，新增 AgentContext 只做非密钥关联，不把对话文本或凭据写入科研证据。
- 聊天队列与原统计 JobRunner 分离；动作只提交到旧 AnalysisService，真正的 R attempt 仍必须经过原审批和 ExecutionController。跨会话 dataset、伪造批准、旧 revision 和取消路径均由确定性校验阻断。
- 运行恢复继续依赖旧 run/attempt/manifest 完整性校验；turn 只反映分析 run 结果，不把 turn COMPLETED 当成统计完成。旧 manifest 无 AgentContext 时保持兼容。
- 本阶段完成本地单后端进程与 Mock 模型验收；真实 provider 联调、前端浏览器和完整用户数据 R 验收留给后续任务。任务 20 未开始，未 push、合并或修改 Draft PR。

## Task 20 React 工作台与模型设置

- Node 24.15.0 / npm 11.12.1 已确认满足 Node 22.12+ 要求。建立 Vite、React、TypeScript、Vitest、Testing Library 和 jsdom 项目，锁定 `package-lock.json`；`frontend/node_modules` 与 `frontend/dist` 已加入忽略规则。
- 前端 API 客户端先获取 no-store CSRF bootstrap，再发送 JSON/模型 profile 请求；SSE 使用 `AbortController`、`after` 游标、按 seq 去重和最多 30 秒指数退避。浏览器不保存 API Key，设置表单提交后清空输入。
- 客户端同时覆盖数据集上传、对话 turn/澄清响应、停止、原分析计划读取与 revision 审批，以及 profile 修改/删除、凭据清除和连接探针；204 响应不会被误解析为 JSON。
- 实现三栏响应式工作台：项目/对话侧栏支持创建、重命名和归档；消息时间线与 Composer 支持数据集选择、counts/metadata 上传、每轮模型选择、澄清卡和重复发送禁用；资源面板读取 run/artifact 客户端数据展示状态、QC、图表、sandbox 报告和逐个下载；报告 iframe 使用空 sandbox，不执行原始 HTML。
- 模型设置保留 provider/model/base URL/profile 保存与凭据写入边界，凭据只通过后端 API 发送；turn 进入等待用户状态后读取可信计划 revision，显示原分析审批卡，并提供停止入口和空状态。
- TDD 红灯：补充缺口测试首次得到 **6 个失败套件、4 个失败断言**，准确捕获项目/对话操作、数据集/模型选择、澄清卡、资源结果、模型 profile 操作和安全 Markdown 缺失；实现后最终 `npm run test -- --run` 为 **10 files / 14 passed**，`npm run typecheck` 和 `npm run build` 均通过。测试覆盖 IME/Shift Enter、重复发送禁用、旧 revision 请求映射、模型切换提示、Key 不进 localStorage/DOM、raw HTML/危险链接过滤、iframe sandbox 和 900/1200 响应式断点常量。
- 后端公共回归 `uv run --offline pytest tests/unit tests/integration tests/evals -k 'not test_real_deseq2_runner_preserves_ad_vs_control_direction' -q -p task17_isolation -p no:cacheprovider --basetemp=runs/task20-backend --tb=short`：**449 passed、1 skipped、1 deselected**（84.46 秒）。跳过项为原有 Windows symlink 权限，排除项为真实 R 集成。
- 客户端新增 run/artifact/QC 只读方法和项目/对话/profile 全部工作台操作；任务 21 的启动脚本、静态资源挂载、Playwright 和 CI 前端 job 尚未实现。未调用真实模型、读取真实 Key、执行用户数据 R 或 push/合并。

## 任务 16–20 整体复盘

- 工作台后端、原分析审批、React 客户端和模型凭据边界保持分层；前端只通过 REST/SSE 访问后端，不导入 Python、R Runner 或模型客户端。
- 事件 reducer 按 seq 去重，断线通过 after 游标恢复；Composer 的 IME/Shift 行为、数据集/模型选择、澄清 revision、模型凭据清空、安全 Markdown、报告 sandbox、结果下载和响应式断点均有自动测试证据。任务 21 又以 Playwright 验证了刷新、SSE 连接、模型切换、窄屏和键盘交互。
- 当前完成本地单后端进程、Mock 模型、前端构建、真实 R 合成工作流和 Python 回归验收；GEO/MCP 未接入。

## Task 21 启动、浏览器验收和门禁

- 会话开始基线为任务 20 提交 `3f6a77f`，worktree 干净，分支为 `agent/bio-agent-mvp`。遵循 TDD：静态/API 与启动脚本定向测试先因缺少静态挂载、dist 检查和启动入口而 **3 failed**；真实 R 工作台验收先以占位失败 **2 failed**，再替换为实际流程。
- FastAPI 先注册 API，再挂载 `frontend/dist`。SPA 前端路由回退到 `index.html`，未知 `/api/...` 保留结构化 JSON 404；HTML 与普通静态文件 `no-store`，带哈希的静态资源使用 immutable 缓存；缺少 dist 返回含 `npm run build` 的 503 提示。
- `scripts/start-workbench.ps1` 检查 Node 22.12+、uv、Rscript、dist 和监听端口，支持可选构建，使用前台 uvicorn，不终止其他进程。`scripts/check.ps1` 增加 npm ci、Vitest、typecheck、build 和 Playwright，并为 Python/R pytest 使用独立 basetemp 防止 Windows 临时目录冲突。
- Playwright 使用固定 API Mock 和独立 Vite global setup，不加载真实 provider；浏览器测试覆盖项目/对话入口、Composer Enter/Shift+Enter、模型切换、刷新、SSE 连接、窄屏。真实 Python e2e 使用合成 counts/metadata 和真实 DESeq2，验证批准前零 attempt、批准后完成、QC/报告及每个 artifact 的 SHA-256 下载，`lfc_shrink` 开/关均通过。
- 文档补充首次安装、生产构建、单命令启动、开发双终端、模型/Key 边界、日志定位和 R 前置条件；CI 新增 Node 22 前端 job，原 Python/R job 保持。Playwright 生成目录已加入 `.gitignore` 并清理。
- 定向验证：`npm ci` 完成；`npm run test -- --run` 为 **10 files / 14 passed**；typecheck、build 通过；`npm run e2e` 为 **1 passed**；静态/启动定向测试 **23 passed**；check 脚本单元测试 **20 passed**；真实工作台 e2e 参数化 shrink **2 passed**。完整真实 R 组合为 **7 passed**（含既有真实 runner、发布、bulk、recovery 与本工作台）。
- 统一 `powershell -ExecutionPolicy Bypass -File scripts/check.ps1` 全部通过：前端安装/测试/类型检查/构建/浏览器、R testthat **37 passed**、Python 公共回归 **457 passed、1 skipped、1 deselected**、真实 R/e2e **7 passed**，仅保留 pytest 缓存目录的 Windows 权限 warning。未执行远端 CI、未调用真实模型或读取真实 Key。
- 统一门禁运行 `renv::restore` 后产生了 `renv/activate.R` 的自动空白变更；该文件未暂存、未提交，其他任务 21 文件已明确暂存。任务 21 不接 GEO、Skills 或 MCP，不 push、不合并。

## Task 19–21 整体复盘

- A 工作台范围已闭环：任务 19 将结构化动作接入原分析服务和人工审批，任务 20 提供 React/模型配置界面，任务 21 提供同源静态托管、前台启动、浏览器验收和 CI/check 门禁。聊天仍通过 REST/SSE 访问后端，统计执行仍由原审批与 R worker 负责。
- 科研证据边界保持不变：模型不能伪造批准，审批前 attempt 为零；真实合成 R 运行证明批准后 QC、报告和 artifact hash 可复核。凭据仍在系统存储/环境引用边界，测试没有真实模型或 Key。
- 真实浏览器与真实 R 合成证据现已具备；远端 CI、provider 联调、GEO GSE、Skills/MCP 和多 Agent 编排仍属于后续阶段。

## Task 22 GSE 检索和候选分类

- 会话开始已确认 worktree 为 `.worktrees/bio-agent-mvp`、分支为 `agent/bio-agent-mvp`，并核对任务 21 实现提交 `6744161` 与文档更正提交 `6e3beb3`。既有的 `renv/activate.R` 自动空白改动保持未暂存、未修改。
- 新增严格冻结的 GEO source、sample、字段和候选模型；GSE 仅接受单一、去除首尾空白并大写的 `GSE[1-9][0-9]*`，URL、GSM、零号和多个编号均被稳定拒绝。
- `GeoClient` 仅检索 SOFT 元数据和 NCBI counts catalog 元数据，不下载候选文件。SOFT 保留 GSM、物种、平台、标题以及重复 characteristics 的原始列表并标注字段来源；10 MiB 元数据限制在该读取边界强制检查。候选 URL 只作为受控来源记录，任务 23 前不执行下载。
- 候选分类完全由确定性规则完成：明确 NCBI raw counts 为 `RAW_COUNTS`，TPM/normalized 为 `NORMALIZED`，FASTQ/SRA/annotation 与不支持后缀为 `UNSUPPORTED`，仅名称含 count 或提交者补充文件为 `UNKNOWN`，不自动放行给 DESeq2。排序固定为 raw、unknown、normalized、unsupported 后按文件名/URL；无可导入候选返回 `GEO_NO_SUPPORTED_COUNTS` 并保留原因。
- TDD 红灯：新增测试首次因 `ModuleNotFoundError: No module named 'bioagent.geo'` 在收集阶段失败。绿灯：`uv run --offline pytest tests/unit/geo/test_geo_client.py -v -p no:cacheprovider` 为 **9 passed**，全部 HTTP 使用 `httpx.MockTransport` 与明确标记为 synthetic 的本地 SOFT/catalog fixtures；未访问公开 GSE、真实模型或 Key。
- 相关回归 `uv run --offline pytest tests/unit/geo tests/unit/datasets -q -p no:cacheprovider --basetemp=runs/task22-regression --tb=short` 为 **53 passed**；全仓 Ruff、mypy（57 个源文件）及八项 pre-commit hooks 通过。临时 pre-commit 空缓存因受限网络无法获取 hook 环境，随后使用已有本地 hook 缓存完成门禁；未安装或更新依赖。
- `git diff --check` 已运行，唯一失败是任务 21 已登记且本次未触碰的 `renv/activate.R` 自动空白改动；任务 22 暂存文件的 `git diff --cached --check` 通过。
- 任务 22 提交时尚未实现下载、重定向、DNS/TLS、gzip、缓存或资源限制，也未接 API、对话动作、工作台、样本映射、Dataset 导入、统计执行、Skills/MCP、push 或 PR 操作；这些下载边界已在本次任务 23 完成。

## Task 23 受限下载与原始文件发布

- 会话开始已确认任务 22 提交 `0f5988d`、分支 `agent/bio-agent-mvp` 和既有 `renv/activate.R` 未暂存空白改动；后者全程未恢复、格式化、暂存或提交。
- TDD 红灯：新增测试首次因 `bioagent.geo.download` 与 `bioagent.geo.transport` 尚不存在而收集失败。首次绿化运行遇到 Windows 默认 pytest 临时目录权限错误，改用 worktree 内 `runs/task23-*` basetemp 后得到有效结果。
- `GeoTransport` 只接受 `www.ncbi.nlm.nih.gov` / `ftp.ncbi.nlm.nih.gov`，将官方 HTTP/FTP 规范化为 HTTPS 443；拒绝 userinfo、非默认端口、片段、跨允许主机重定向、超过 3 跳、私网/loopback/link-local/reserved IPv4/IPv6、DNS rebinding 和 TLS 证书错误。每跳重新解析并把连接绑定到已验证 IP，默认 socket connector 保持 TLS hostname 校验；测试通过注入 resolver/connector，不访问公网。
- `GeoDownloader` 使用服务器策略限额：单文件 100 MiB、实例累计 300 MiB、gzip 展开 200 MiB、压缩输入 100 MiB、磁盘预留 400 MiB、连接 10 秒、总计 300 秒、最多重试 2 次与 Retry-After 60 秒上限。流式 SHA-256、Content-Length 与实际字节双重检查、取消/超时/429/502/503/504 错误码、共享 2 请求/秒 limiter 均为确定性代码。
- 下载和 gzip 展开只写独占 UUID `.part`，检查路径边界、符号链接、特殊源文件和已存在目标；成功后 fsync 并以不覆盖的原子 hard-link 发布，失败只清理本次临时文件。哈希不匹配返回 `SOURCE_CHANGED`，损坏/超限 gzip 不发布目标。
- `GeoClient` 保留任务 22 的 MockTransport 兼容测试，同时允许生产调用方注入同一 `GeoTransport`；没有接 API/UI、样本映射、Dataset 导入、Skills/MCP 或统计执行。
- 有效定向测试：`tests/unit/geo/test_geo_download.py` + `tests/integration/test_geo_transport.py` + `tests/unit/geo/test_geo_client.py` 为 **35 passed**；任务 22–23 相关回归（含 Dataset parser/validator/API）为 **88 passed**。Ruff、mypy（59 个源文件）和八项 pre-commit hooks 均通过。
- 未执行真实公网下载；未读取真实模型 Key；未 push、合并或修改旧 Draft PR。下一任务为 24，需先做 22–24 整体复盘。

## Task 24 GEO 样本映射、标准化和共享 Dataset 入口

- 会话开始已确认提交 `c7ba02b`、分支 `agent/bio-agent-mvp` 和既有 `renv/activate.R` 未提交空白改动；后者全程未恢复、格式化、暂存或提交。
- TDD 红灯：新增 `test_geo_transform.py` 与 `test_geo_repository.py` 首次收集因 `bioagent.geo.transform` / `bioagent.geo.repository` 尚不存在而失败；实现后 GEO 定向测试转绿。
- `SourceSelection` 保存 source/candidate/raw hash、feature 列、列到 GSM 的一对一映射、分组/比较方向、修订号、UNKNOWN 的 raw-count 确认、排除样本和证据；模型校验 feature 不可兼作样本、两组各至少两个样本且比较方向确定。`selection_hash()` 对原始 hash 与排序后的 JSON 做 SHA-256，样本映射变化必然改变 hash。
- `transform_selection()` 使用受限 CSV/TSV/TXT（含 gzip）读取，保留前导零 gene ID 和原始字节；拒绝重复 gene、重复/未知 GSM、非整数/负数/TPM/未确认 UNKNOWN，并输出标准 `feature_id` counts 与 `sample_id` metadata。三组数据必须显式选择两组并登记排除样本，不静默删样本或推断归一化 counts。
- `GeoRepository` 为每份来源建立新的 UUID 受控目录，原始和标准化文件以固定路径原子发布，`source.json`/`metadata.json` 保存候选 URL、确认时间、转换版本、选择及各 SHA-256；读取与缓存命中复算 hash，同 URL 新内容不会覆盖旧 source，旧 revision/hash 返回冲突。
- 上传路由已委托共享 `DatasetImportService`；上传仍使用 10 MiB、原有解析子进程和 validator，GEO 标准化入口独立使用 100000 行/2000 样本列/30 秒配置，不通过上传 HTTP API 绕过边界。`DatasetRepository` 写入也改为新目录内原子发布。
- 有效定向回归 `tests/unit/geo tests/unit/datasets tests/integration/api/test_datasets.py`：**84 passed**；完整 Python 回归：**510 passed、1 skipped**（Windows 无目录 symlink 权限）。全仓 Ruff 与 mypy（62 个源文件）通过；八项 pre-commit hooks 在 worktree 内缓存初始化后全部通过。
- 22–24 整体复盘：GEO 22 的元数据/候选分类、23 的 allow-list/DNS/TLS/下载资源边界、24 的显式样本确认/数据校验/来源 hash 形成串联但独立的边界；UNKNOWN 不会自动放行，下载限额与上传限额未混用，未实现任务 25 API/对话动作、浏览器扩展、Skills/MCP 或多 Agent 编排。
- `git diff --check` 仅报告既有 `renv/activate.R` 空白改动；本任务文件的 staged diff 将单独执行 `git diff --cached --check`。未读取真实模型 Key、未访问公网 GSE、未 push、合并或修改旧 Draft PR。

## Task 25 GEO 后台任务与对话动作

- 会话在 `agent/bio-agent-mvp` 的既有 worktree 中继续；保留用户已有的 `renv/activate.R` 空白改动，未恢复、格式化、暂存或提交。Task25 实现只覆盖 GEO 后台/API/对话边界，不提前实现任务 26 的界面。
- 新增 `GeoImportService` 和 `/api/v1/geo` 全部规格端点。source 与 import 状态持久化分离，独立 I/O worker 限制为最多 2 个并发、16 个排队；固定状态转换、幂等 revision、重启/关闭/取消竞态、下载进度节流和失败码均由确定性代码保证。发布 provenance 失败时回收新建 Dataset，避免孤儿数据集。
- GEO API 经过本地 Host/Origin/CSRF 与请求体边界；普通 workbench 请求仍保持原 32 KiB 限制，GEO mapping 允许 2 MiB 以容纳 2000 个样本列。直接 API 请求创建明确的工作台事件 owner，事件复用现有 seq/EventStore，不把临时路径暴露给客户端。
- `geo_lookup`/`geo_import` 结构化动作绑定固定工具 schema，严格拒绝额外字段和模型伪造的 `kind`；流式工具调用按 index/id 重组续片。GSE 必须来自当前用户输入且只有一个，首轮多 GSE 会澄清，后续明确选择可继续 discovery；候选必须属于当前会话选择的 source，用户确认后才下载。READY 仅创建等待人工审批的原分析计划，统计 attempts 保持为 0。
- 定向 GEO service/API（`tests/unit/geo/test_geo_service.py`、`tests/integration/api/test_geo.py`）为 **33 passed**；`tests/integration/api tests/unit/workbench tests/unit/geo` 回归为 **171 passed**。全量 Python 回归为 **547 passed、1 skipped**，跳过项为 Windows 目录 symlink 权限。
- 全仓 Ruff、`mypy src` 和 8 项 pre-commit hooks 全通过；质量复审覆盖下载/取消线性化、mapping 请求体上限、后台任务关停、发布失败 dataset 补偿、受限 GEO action、事件持久化、恢复策略和错误映射。测试全部使用 Mock/本地 fixture，未访问公开 GEO、未调用真实模型或读取真实 Key，未执行真实 R 工作台验收。Task25 已本地提交，未 push、合并或修改 Draft PR。

## Task 26 候选选择、映射和分组界面

- TDD 红灯先创建 `GeoSourceCard` 与 `SampleMapping` 组件测试；首次 Vitest 因三个 GEO 组件文件尚不存在、Vite 无法 resolve import 而失败，未写生产组件前已记录该预期失败。
- 新增来源候选卡、下载进度、样本映射和分组组件。候选卡明确显示来源元数据、证据、文件名、已知/未知大小、100 MiB 单文件上限和官方记录；NORMALIZED/UNSUPPORTED 均不可下载，UNKNOWN 必须由用户确认 raw counts。进度只对已知大小计算百分比，取消后显示服务真实终态。
- 映射区显示矩阵列、GSM、原始 characteristics 与分组，允许改正映射、不自动删除行；要求一对一映射、显式两组、每组至少两个样本，并在提交前展示 numerator 相对 denominator、重复数与排除样本。source revision 或 raw SHA-256 改变时清空确认并要求再次确认；服务错误保留表单编辑并可取消回到候选列表。UNKNOWN 在页面刷新后仍需要在映射提交前再次确认类型。
- `ChatTimeline` 订阅既有 `geo.source` / `geo.updated` SSE 事件，并通过资源 GET 刷新 source/import 状态；选中含 `geo_source_id` 的对话时也会恢复来源卡，网络重连重放事件不会靠浏览器本地猜测进度。客户端将 revision 与 raw SHA-256 原样提交 selection。
- 前端验证：`npm --prefix frontend run test -- --run` 为 **12 files / 24 passed**；typecheck、production build 均退出 0。`uv run --offline pytest tests/integration/api tests/unit/workbench tests/unit/geo -q -p no:cacheprovider` 为 **171 passed**；Ruff、mypy 和 8 项 pre-commit hooks 均通过。所有 UI 测试使用 fixture/mock，未访问 GEO 网络、真实模型或 Key。`renv/activate.R` 的既有空白修改保持未暂存、未格式化。

## Task 27 GEO 来源绑定、真实统计端到端与文档

- TDD 红灯先写了参数化 `lfc_shrink=False/True` 的真实 R/GEO synthetic e2e；两种模式都先因 run 缺少 `source/` 副本而失败，随后转绿。模型使用固定 Mock，未访问公开 GEO 或读取真实 Key。
- `GeoRepository` 将 dataset ID 写入 source provenance；`AnalysisService` 在创建 run 前验证 source/dataset 绑定，并复制 raw、`source.json`、normalized counts/metadata 到受控 run 目录。审批前只生成来源副本和 AWAITING_APPROVAL 索引，`attempts/` 为空。
- `RunManifest` 增加可选 `source_id` / `source_artifacts`，旧 manifest 默认兼容；`ExecutionController` 在执行、复用和恢复前重新核对来源 payload 与四份副本 SHA-256，篡改、缺失、404、dataset 不匹配均拒绝。来源记录同时进入 `manifest.artifacts`，下载继续只接受系统生成的不透明 artifact ID。
- 浏览器 `frontend/e2e/geo.spec.ts` 覆盖“分析 GSE → 候选确认 → 样本映射 → 计划审批 → COMPLETED/PASS/下载”；网络全部由本地 Playwright fixture 响应。审批后的 React 状态保留 run 以展示最终 QC/报告。
- 新增 `docs/geo.md`，并更新 README、架构和安全说明，记录 counts 判断、UNKNOWN、NCBI 来源、资源上限、缓存、provenance 与不执行公网 GSE 的边界。
- 验证：`uv run --offline pytest tests/e2e/test_geo_workflow.py` 为 **3 passed**；真实 R/回归集合为 **10 passed**（含 `lfc_shrink` 两种路径、API release、恢复重试）；完整 Python 分项为 **540 passed、1 skipped、1 deselected**；R testthat **37 passed**；前端 Vitest **12 files / 24 passed**、typecheck、build、Playwright **2 passed**；Ruff 与 mypy 通过。`scripts/check.ps1` 已执行，但其固定 `runs/check-python` 目录在当前 sandbox 返回 WinError 5，等价分项已用新的可写 basetemp 完成。`renv/activate.R` 哈希保持原有 `A36F28F8…`，未暂存、未提交。
- 25–27 整体复盘：GEO 下载/转换、对话确认、UI 映射和分析审批仍是分离状态机；来源 hash 与输入 hash 分层记录；旧上传 run 不携带 source 字段仍可读取；未引入 Skills/MCP、多 Agent、公开网络下载或真实模型联调。

## Task 28 本地 Skill 发现、校验与快照

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、分支 `agent/bio-agent-mvp` 和 HEAD `ef45c1c`；唯一已有未提交项 `renv/activate.R` 是自动空白改动，全程未恢复、格式化、暂存或提交。
- TDD 红灯先新增路径逃逸用例；`uv run --offline pytest tests/unit/extensions/test_skills.py -v -p no:cacheprovider` 因 `ModuleNotFoundError: bioagent.extensions` 收集失败，符合新模块尚未创建的预期。
- 新增配置根 `.bioagent/skills`、一层目录发现、严格 UTF-8/64 KiB 文件与 128 KiB 每轮限制、安全 PyYAML frontmatter、仅本 Skill 内 Markdown/text 引用、深度/循环/符号链接拒绝及确定性组合 hash。Skill 文本和引用均以字面内容冻结，不执行 YAML tag、模板、脚本或凭据插值。
- 新增独立版本化 Skill SQLite 表，不改变既有 workbench/checkpoint 表。启用绑定 `expected_hash` 与快照；文件或引用改变会撤销新加载，禁用拒绝新加载，历史快照仍可按 hash 读取。`allowed_tools` 只收窄本地授权集合，未声明时也不扩大本地授权。
- 定向测试为 **11 passed、1 skipped**；相关 `extensions/workbench/models` 回归为 **82 passed、1 skipped**；skip 为本 Windows 主机不具目录符号链接创建权限，Linux CI 会执行该回归。全仓 Ruff、mypy 与 8 项 pre-commit hooks 已通过。`git diff --check` 仅因既有未暂存 `renv/activate.R` 空白改动失败，Task 28 暂存差异将单独检查。未实现 MCP transport、连接或工具调用，未读取真实 Key、访问网络、push、合并或修改旧 PR。

## Task 29 MCP 配置与两种 transport

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支与 Task28 提交 `59c9f1f`；保留用户已有的 `renv/activate.R` 自动空白改动，未恢复、格式化、暂存或提交。
- TDD 红灯先新增端点与适配器测试；在实现前运行单元测试于收集阶段得到 `ModuleNotFoundError: No module named 'bioagent.extensions.mcp_client'`，符合新客户端模块尚不存在的预期。
- 按官方 PyPI/GitHub 客户端文档核对并锁定 MCP Python SDK **2.2.0**（`mcp==2.2.0`，含 Streamable HTTP 与 stdio 公共客户端 API）到 `pyproject.toml`/`uv.lock`；SDK 类型仅封装在 `extensions/mcp_client.py`，对外保持 `connect`、`list_tools`、`call_tool`、`disconnect`、`close`。
- 新增冻结的 `StdioConfig`、`HttpConfig`、`McpServerConfig`、`McpConnection`、`McpTool`、`McpCallResult`，并在 SkillStore 同一 workbench DB 建立独立版本化 MCP 配置表；配置只保存 secret refs，不保存 secret 值。依赖容器注入 `SkillStore` 与 `McpClientAdapter`，解析模型 SecretStore 仅用于显式 MCP refs。
- stdio 使用 `shell=False`、绝对 executable/cwd、最小继承环境和显式 refs，父进程组退出清理本应用子进程树；连接/发现 10 秒、调用默认 60 秒/最高 300 秒并受 turn 剩余时间约束，最多 8 连接。HTTP 仅允许本地明文或远端 HTTPS，拒绝 userinfo/fragment/凭据 query，禁用重定向并通过 `trust_env=False` 与流式 2 MiB 响应限额隔离请求。
- 本地 MCP fixture 覆盖 echo、delay、isError、大结果、退出和派生子进程模式；真实 SDK stdio/Streamable HTTP round-trip、协议协商、超时/取消、2 MiB 消息/响应限额、模型 Key 不继承及子进程清理均有测试。有效结果：定向 MCP **24 passed**；`tests/unit/extensions tests/integration/test_mcp_transports.py` **35 passed、1 skipped**（Windows 目录 symlink 权限）。既有 `tests/unit/extensions tests/unit/workbench tests/unit/models tests/integration/api` 回归 **173 passed、1 skipped**。
- 静态检查：`mypy src`（69 个源文件）、全仓 Ruff 与 8 项 pre-commit hooks 均通过。全量 Python 回归为 **583 passed、2 skipped、2 failed**；失败仅为既有真实 R e2e 在当前 Windows 主机的 `ValueError/EXECUTION_FAILED`（`Rscript` 不在 PATH，且未修改相关执行代码），MCP 定向与扩展相关回归均通过。测试未访问公网 MCP/模型服务、未读取真实模型 Key、未执行任意用户命令；未实现 Task30 policy/schema/API、未 push、合并或修改旧 Draft PR。`git diff --check` 仅报告既有 `renv/activate.R`，本任务暂存差异单独检查。

## Task 30 工具 policy、schema 与一次性批准

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、分支 `agent/bio-agent-mvp` 和 Task29 提交 `7f5bfe1`；保留用户已有 `renv/activate.R` 空白修改，未恢复、格式化、暂存或提交。
- TDD 红灯先写只读 annotation policy 测试；按计划运行时集成测试文件尚不存在，随后单测收集得到 `ModuleNotFoundError: No module named 'bioagent.extensions.policy'`，符合策略模块尚不存在的预期红灯。
- 新增 `policy.py`、`gateway.py` 和 `extension_routes.py`。工具初始始终 `CONFIRM`；本地 JSON Schema 规范化/远程 `$ref` 拒绝、schema/capability revision、DENY/CONFIRM/ALLOW_READ、输出校验、2 MiB 限制和稳定错误码均在 gateway 统一执行。MCP 工具使用 `mcp.<server_id>.<tool>` 命名空间，`analysis.approve` 不进入目录。
- Skill 根目录、扫描/预览/启停、MCP server 配置版本控制、独立凭据引用、显式连接/断开、工具 policy、批准决定 API 均挂载 `/api/v1/extensions`，沿用 Host/Origin/CSRF 边界；根变更会禁用 Skill。批准表保存随机 ID、turn/call、参数 hash、capability revision、10 分钟过期和 `used_at`，SQLite 原子消费及 turn 撤销已实现。事件只写工具/hash/版本等脱敏字段，不写 secret 或原始参数。
- 定向测试：`uv run --offline pytest tests/unit/extensions/test_tool_policy.py tests/integration/api/test_extensions.py -q -p no:cacheprovider` 为 **16 passed**；相关回归 `tests/unit/extensions tests/unit/workbench tests/unit/models tests/integration/api` 为 **189 passed、1 skipped**（Windows 目录 symlink 权限）。此前一次超大结果断言误捕获已修正并复跑通过。
- 静态检查：全仓 `ruff check .`、`mypy src`、8 项 pre-commit hooks 均通过；pre-commit 首次因缓存目录权限/网络受限，改用工作区缓存并在获准的外部环境完成。未重跑 Task29 已知的两项真实 R e2e；当前主机仍因 `Rscript` 不在 PATH 而失败，保留该限制。未访问公网 MCP/模型服务、未读取真实 Key、未执行任意用户命令。
- 28–30 整体复盘：Skill 内容仍是本地只读快照，MCP transport 只负责协议适配；gateway 将用户 policy、schema、批准和预算边界集中执行，统计分析审批仍由原 AnalysisPlan 控制。配置/schema/revision 变化不会复用旧批准；凭据只经独立 SecretStore 引用注入，审计与结果不改变 run 状态。范围未扩展到 Task31 对话工具循环、多 Agent 或自动安装。

## Task 31 对话 Skill 选择与受控 MCP 工具循环

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支和 Task30 提交 `436ac6b`；保留用户已有的 `renv/activate.R` 空白改动，未恢复、格式化、暂存或提交。
- TDD 红灯先新增 `test_tool_loop.py` 与 `test_workbench_tools.py`；实现前运行定向测试在收集阶段得到 `ModuleNotFoundError: No module named 'bioagent.workbench.tool_loop'`，符合循环模块尚不存在的预期红灯。
- 新增 `ToolLoop` 与单调截止时间 `TurnBudget`：每轮最多 8 个 MCP/Skill 动作、120 秒活动时长，动作在调用前预留额度，失败/未知结果不重试；等待批准暂停预算，继续同一 turn 时沿用已落盘计数。工具结果以来源标签和 16 KiB UTF-8 上限摘要进入下一模型轮次，始终作为不可信数据。
- 新增 `mcp_call`、`load_skill` 动作。模型只收到当前非 DENY 工具和启用 Skill 的元数据；Skill 只从当前能力快照加载，最多三项，不做环境变量展开，授权/哈希变化会拒绝加载。MCP 调用继续统一经 ToolGateway，批准请求保存脱敏 call/参数 hash/capability revision；批准响应复用同一 turn，重复响应冲突，取消/重启撤销未使用批准。
- 保留 GEO 内置动作与原 `AnalysisService`/DESeq2 审批边界；计划动作的 `agent_context` 绑定 turn 的 model snapshot 及已加载 Skill 名称/hash。新增可查询的当前可用工具 API，不改变完整工具目录供设置页审阅。
- 定向验证 `tests/unit/workbench/test_tool_loop.py` + `tests/integration/api/test_workbench_tools.py` 为 **8 passed**；相关 `tests/unit/extensions tests/unit/workbench tests/integration/api` 为 **167 passed、1 skipped**，跳过项为 Windows 目录 symlink 权限。Ruff、`mypy src` 与 pre-commit hooks 全部通过。
- 未读取真实模型 Key、未调用公网 MCP/模型服务、未执行真实 R 分析；Task29 已知 Rscript PATH 限制未重跑。`git diff --check` 仍只报告既有 `renv/activate.R` 空白变更，本任务暂存差异将单独检查。未 push、合并或修改 Draft PR。

## Task 32 扩展设置和调用确认卡

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支与 Task31 提交 `7f93bb6`；保留用户已有 `renv/activate.R` 空白改动，未恢复、格式化、暂存或提交。
- TDD 红灯先只新增三个计划指定的组件测试；首次 `npm --prefix frontend run test -- --run` 有 3 个失败套件，均因 `SkillSettings`、`McpSettings`、`ToolApprovalCard` 尚不存在而无法解析导入，既有 12 个套件/24 项测试通过。
- Skills 设置页支持根目录、扫描、内容/引用安全预览、组合 hash、启停、扫描错误与文件变化后重新启用提示。MCP 设置页支持保存后的 stdio/HTTP 表单、仅凭据引用、精确命令/endpoint 预览、连接/断开、协议版本和工具目录；密码字段写入后清空，模型 Key 不复用为 MCP 凭据。
- Tool policy 页展示 schema、服务数据去向与 capability revision，默认 `CONFIRM`；调用卡仅由显式批准/拒绝触发，安全展示目标、规范化参数、hash/revision/过期状态，旧 revision、过期或重复点击均不可用。原始工具结果使用折叠文本节点显示，不注入 HTML；等待时仅更新当前 revision 状态，不改写已经展示的目标或参数快照。
- 验证：前端全量 Vitest **15 files / 27 passed**，`npm --prefix frontend run typecheck`、`npm --prefix frontend run build` 均通过。最小后端/API 静态检查 `uv run --offline --no-sync pytest tests/integration/api/test_extensions.py -q -p no:cacheprovider --basetemp .pytest-task32-api` 为 **3 passed**，`uv run --offline --no-sync ruff check .` 通过。未执行 R、全量 Python 或 Task33 e2e；未读取真实 Key、调用公网 MCP/模型服务、push 或合并。

## Task 33 扩展端到端、恢复和使用文档

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支与 Task32 提交 `b3a5b53`；保留用户已有 `renv/activate.R` 空白改动，未恢复、格式化、暂存或提交。
- TDD 红灯先新增计划指定的两个 e2e 文件。Python 首次运行在工作区 uv 缓存替代后收集为 3 项，其中 stdio/HTTP 2 项通过，跨重启未知结果断言因缺少 `action.failed` 审计而失败；Playwright 首次在等待不存在的“设置”入口超时。两项失败均对应真实缺口，未改写断言绕过。
- 修复 ToolGateway：工具连接断开、取消、未知结果、过大结果、MCP isError 和输出 schema 错误均写入脱敏 `action.failed` 事件；未知结果保持 `TOOL_OUTCOME_UNKNOWN`，不自动重试。新增 e2e 参数化验证任务 29 的真实 MCP SDK fixture stdio/HTTP；重启重新打开扩展数据库后撤销旧批准，call count 保持一次。
- 设置页演示入口统一为“设置”，提供 Skills/MCP 页签和“添加 MCP 服务”；无模型 Key 时仍可加载工作台。新增合成 [bulk-rnaseq-review Skill](../../examples/skills/bulk-rnaseq-review/SKILL.md) 与 [只读 MCP fixture](../../examples/mcp/readonly_server.py)，以及 [扩展配置指南](../extensions.md)，记录绝对 executable/argv/cwd、env/header refs、HTTP endpoint、连接/权限/禁用/清理、SDK 版本、限额和取消不能回滚远端的语义。
- CI/统一门禁将本地扩展 Python e2e 纳入 Python suite，Node 22.12、`mcp==2.2.0` 与 lockfile 继续固定；浏览器只走本地 route fixture，不执行自动批准或真实账户工具。README、工作台、架构和安全说明均补充 Skills/MCP 与统计证据边界。
- 验证：定向 Python `tests/e2e/test_extensions_workflow.py` **3 passed**；扩展 Playwright **1 passed**，完整前端 Playwright **3 passed**；Vitest **15 files / 27 passed**，typecheck/build 通过；统一 `scripts/check.ps1` **600 passed、2 skipped、1 deselected**，R testthat **37 passed**，R/DESeq2 e2e **13 passed**；pre-commit **8 hooks passed**。skip 为 Windows 目录 symlink 权限；pytest 有 Windows 缓存目录 WinError 5 警告。首次 sandbox 运行因 `.venv` 权限拒绝，获准外部环境重跑后门禁通过；未访问公网、真实 GEO/MCP/模型 Key，未 push、合并或改 PR。

## Task 33 完成后的全项目运行审计

- 先执行未修改代码的完整 `scripts/check.ps1`，结果为前端 Vitest **15 files / 27 passed**、Playwright **3 passed**、Python **600 passed、2 skipped、1 deselected**、R testthat **37 passed**、真实 R/DESeq2/e2e **13 passed**，Ruff、mypy、typecheck 和 build 全通过。skip 仍是 Windows 目录 symlink 权限。
- 真实启动 `scripts/start-workbench.ps1 -Port 8010` 后发现 Windows MIME 注册表让 Vite 的 ES module 以 `text/plain` 返回，浏览器因此显示空白页；新增静态集成断言后，服务端对 `.js`/`.mjs` 强制使用 `application/javascript`。生产构建已在实际浏览器确认渲染，根页面和哈希 JS 均为 200，浏览器控制台无 warn/error。
- 修复窄屏隐藏项目栏却没有入口的问题；顶部“项目与对话”现在打开可关闭抽屉。项目选择成为显式状态，新对话使用当前项目，切换项目会清理旧对话上下文。既有组件测试和窄屏 Playwright 用例覆盖该行为。
- Skills/MCP 改为真正互斥的页签；分析审批后会随 turn 状态变化重新读取 run 与 artifacts，因此 RUNNING 转为 COMPLETED 后能显示 QC 和下载。GEO 浏览器流程先复现这两个状态缺口，再验证修复。
- 已保存 MCP 服务现在会把当前配置与 revision 载入表单并调用 update API；stdio argv 改为每行一个完整参数，包含空格的 Windows 路径不会被空白拆分。现有 MCP 组件测试覆盖载入、更新和 argv 保真。
- 修复后重新执行完整 `scripts/check.ps1`：前端 Vitest **15 files / 28 passed**、Playwright **3 passed**、Python **600 passed、2 skipped、1 deselected**、扩展 e2e **3 passed**、R testthat **37 passed**、真实 R/DESeq2/e2e **13 passed**，Ruff、mypy、typecheck、production build 与 renv 同步检查均通过；限定于本次暂存文件的 pre-commit **8 hooks passed**。pytest 仅有当前工作区缓存 ACL 警告，skip 仍是 Windows 目录 symlink 权限。
- 保留用户已有的 `renv/activate.R` 空白修改，未恢复、格式化、暂存或提交。未访问真实模型/GEO/MCP 账户，未读取 Key，未 push、合并或修改旧 PR。

## Task 33 API 鉴权无响应修复

- 用户真实工作台中两次消息只有 user card、没有回复。只读查询本地 turn 记录确认两次均在约 0.15 秒内进入 `FAILED`，错误码都是 `MODEL_AUTH_FAILED`；随后调用内置 profile probe，同样得到 `ok=false / MODEL_AUTH_FAILED`。未读取或输出 API Key。
- 根因包含两个界面缺口：`Environment / deepseek` 是只在进程启动时读取 `BIOAGENT_DEEPSEEK_API_KEY` 的只读 profile，但旧界面仍允许填写 Key 和点击更新；同时 probe 忽略响应中的 `ok=false`，快速失败事件与提交响应存在竞态，页面既不显示错误又可能保留旧 QUEUED 状态。
- 环境 profile 现在禁用编辑并明确提示修改 `.env` 后重启，或选择“新模型”保存可编辑配置；切回新模型会清空旧环境字段。probe 根据真实 `ok/code` 显示结果。SSE 投影携带 `turn_id`，客户端按事件 seq 应用终态并显示稳定失败码，快速失败不会被稍后返回的 QUEUED 响应覆盖。
- DeepSeek 当前官方资料确认 `https://api.deepseek.com` 与 `deepseek-v4-flash` 仍是有效组合；当前失败是凭据鉴权，不是截图中的模型名或 Base URL。自动测试继续使用 Mock，未把真实 Key 写入日志、数据库、文档或 Git。
- 修复后完整 `scripts/check.ps1` 通过：前端 Vitest **15 files / 29 passed**、Playwright **3 passed**、Python **600 passed、2 skipped、1 deselected**、扩展 e2e **3 passed**、R testthat **37 passed**、真实 R/DESeq2/e2e **13 passed**，Ruff、mypy、typecheck、production build 与 renv 同步检查均通过；限定于本次暂存文件的 pre-commit **8 hooks passed**。skip 和 pytest cache 警告仍只来自 Windows 权限。

## Task 33 实时消息与流式进度修复

- 用户截图显示自己刚发送的消息标成 “Bio-Agent”。数据库/API 中角色实际正确，问题是前端 SSE reducer 创建实时 message 时把角色硬编码为 assistant；现已使用服务端事件中的受限 `user/assistant` 角色，刷新前后显示一致。
- provider 原本已使用 `astream`，但 Task31 工具循环先把所有文本分片收集进 `ToolLoopResult`，TurnService 在模型结束后才一次性落库。工具循环新增受控 `on_text` 回调，普通文本分片直接通过既有 `append_delta` 事务与 SSE 推送；取消或终态导致写入停止时不再继续完成 turn，默认无回调路径保持既有测试兼容。
- 工作台在 QUEUED/RUNNING 时显示“等待 Agent 处理/正在思考并检查可用工具”的可审计状态。模型私有 reasoning 继续不保存、不展示；用户可看到文本生成、工具确认和分析审批过程，而不是内部思维链。
- 当前没有关键词搜索能力是既有 Task22–27 的明确边界：内置 `geo_lookup` 只接受已知 GSE。若扩展，需要新增受限 GEO/Entrez 搜索工具或显式配置搜索 MCP，并为查询、候选与来源证据建立契约，不能让模型猜编号。
- 修复后完整 `scripts/check.ps1` 通过：前端 Vitest **15 files / 29 passed**、Playwright **3 passed**、Python **601 passed、2 skipped、1 deselected**、扩展 e2e **3 passed**、R testthat **37 passed**、真实 R/DESeq2/e2e **13 passed**，Ruff、mypy、typecheck、production build 与 renv 同步检查均通过。skip 与 pytest cache 警告仍只来自 Windows 权限。

## 31–33 整体复盘

- 单 Agent 边界保持：Task31 只允许受约束 action loop，Task32 只做设置/策略/批准 UI，Task33 只补本地 fixture、恢复审计和文档；没有多 Agent 编排或新统计方法。
- 无任意执行与自动下载：Skill 仅本地文本快照；MCP 只能运行用户已保存的绝对 executable/argv 或完整 endpoint，不接受聊天生成命令，不使用 `npx -y` 或市场安装。
- 无凭据进入证据：模型 Key 与 MCP 独立 refs 只在连接请求边界使用；secret 不进入 SQLite、事件、checkpoint、manifest、日志或模型上下文；MCP 返回带不可信标签且不是统计证据。
- 统计审批未绕过：MCP policy/批准不改变 AnalysisPlan 的 revision/hash、R attempt、QC 或报告；DESeq2 仍需原人工分析审批。取消、重启和已发出未知结果均不自动重发远端调用。
- 已验证客户端/transport：Node `v24.15.0`（CI 固定 `22.12.0`）、npm `11.12.1`、uv `0.12.5`、R `4.5.2`、MCP SDK `2.2.0`；本地真实 SDK fixture 覆盖 stdio 与 Streamable HTTP，浏览器仅使用合成 route fixture。未做真实账户手工联调，真实模型 API 由用户后续明确配置。

真实模型 API 仍可由用户后续接入，不等待 Key。Task 15 发布收尾单独保留：推送需前述明确授权，之后核验最新 CI；具体 UI 演示审批获准后补录结果/GIF及手工下载核验。保持 Draft，不直接合并。

## 下一阶段设计与计划

2026-09-08 用户确认：先本地 Web 工作台与模型配置，再 GEO GSE counts/样本信息，最后 Skills/MCP；保留 bulk 双组 DESeq2、人工审批和单 Agent 架构。CLI 共用 API 的边界保留，首版不实现 TUI。

| 子项目 | 规格 | 计划 | 状态 |
| --- | --- | --- | --- |
| A 工作台与模型 | [设计](../superpowers/specs/2026-09-08-workbench-design.md) | [16–21](../superpowers/plans/2026-09-08-workbench.md) | 16–21 已实现 |
| B GEO 数据接入 | [设计](../superpowers/specs/2026-09-08-geo-design.md) | [22–27](../superpowers/plans/2026-09-08-geo.md) | 22–27 已实现 |
| C Skills/MCP | [设计](../superpowers/specs/2026-09-08-extensions-design.md) | [28–33](../superpowers/plans/2026-09-08-extensions.md) | 28–33 已实现，真实 API/账户联调由用户后接 |

设计采用 React/TypeScript + FastAPI 同源工作台、REST/SSE 事件、独立对话存储和 turn 队列；API Key 使用系统凭据存储/环境引用，切换模型只影响新轮次。GEO 下载、样本确认、source/dataset 绑定和 run provenance 已通过 Task27；Skill/MCP 不具有替代分析审批的权限。

2026-09-14 用户批准 [GEO 关键词搜索、下载衔接与 RAG 扩展设计](../superpowers/specs/2026-09-14-geo-search-rag-design.md)，选择第一版只实现 GEO 关键词搜索，并把符合现有 raw counts 合约的数据接入 bulk RNA-seq 双组 DESeq2；同时预留独立 `KnowledgeRetriever`，本阶段不实现知识库。对应 [Task 34–36 实施计划](../superpowers/plans/2026-09-14-geo-search-rag.md) 现已完成；公网调用继续使用 Mock，不读取真实 Key。后续功能扩展需重新获得明确授权。

规格准备会话仅新增规格/计划并更新进度；基线统计修复为 `0b14036`，其 Python 359 passed/1 skipped、R 37 passed 是此前实际验证结果，不是新功能验收。该会话的文档检查结果在本节记录；任务 16 的实现与测试结果见上文独立记录。

文档验收：六份文档的 15 个相对链接全部存在，编号任务恰为 16–33；24 段 Python 示例通过 AST 语法解析，24 段 PowerShell 示例通过原生 Parser 检查，无占位符扫描命中。规格覆盖与字段自检修正了 ArtifactRecord.relative_path、Skill 引用组合 hash 和 GEO 下载/映射顺序。八项 pre-commit hooks 通过，暂存 diff 检查通过。仅做文档语法/一致性检查，未执行计划中的未来代码示例，也未重跑未改动的统计实现。

## Task 34 GEO 搜索 provider、状态服务与 API

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支；保留用户已有的 `renv/activate.R` 空白修改，未恢复、格式化、暂存或提交。
- TDD 红灯先新增本地 `MockTransport` provider fixture、搜索服务与 API 测试。provider 首次收集失败为 `ModuleNotFoundError: bioagent.geo.search`；服务/API 首次收集失败为 `ModuleNotFoundError: bioagent.geo.search_service`，均对应尚未实现的 Task 34 模块。首次 sandbox 因 uv 缓存 ACL 被拒，获准使用现有本地离线缓存后完成测试；未访问公网、真实 GEO、模型或 Key。
- 新增冻结的 retrieval 查询/证据/命中/分页契约、NCBI ESearch→ESummary provider、原子搜索快照仓库与独立 2 worker/16 queued 搜索服务。查询只生成受控 Entrez 参数，业务文本转义引号/括号/反斜杠；结果仅接受、稳定去重合法 GSE，并构造官方 NCBI HTTPS 证据 URI。eutils 主机加入既有 DNS 固定 allowlist，搜索实例禁用跳转。
- 搜索状态保存至 `data/searches/<uuid>/search.json`，恢复时只将 `QUEUED/SEARCHING` 标记为 `FAILED/GEO_SEARCH_PROCESS_RESTARTED`；分页 token 为已签发且搜索 query hash 绑定的服务端 opaque token。选择校验 revision 与快照归属后仅调用注入的 `GeoImportService.create_source`，不接触下载器；factory 失败不写入 `SELECTED`。
- 新增五个 `/api/v1/geo/searches` 端点，沿用 local-host/CSRF 约束；容器启动/关闭搜索服务。事件仅投影搜索 ID、状态、revision 与结果数。
- 验证：`uv run --offline pytest tests/unit/geo/test_geo_search.py tests/unit/geo/test_geo_search_service.py tests/integration/api/test_geo.py tests/integration/test_geo_transport.py -q -p no:cacheprovider` 为 **29 passed in 4.38s**；`uv run --offline ruff check .` 为 **All checks passed**（仅 uv cache ACL warning）；`uv run --offline mypy src` 为 **Success: no issues found in 78 source files**。下一编号任务为 **Task 35：Agent 搜索动作、事件衔接、搜索结果界面和现有 source discovery 复用**。
- Task 34 审查修复：provider 先检查 `Content-Length`，再以流式字节累计限制 2 MiB，避免通过 `.content` 无界物化响应；搜索 owner 改为服务端签名的 HttpOnly/SameSite cookie，并与持久化 conversation/turn 对照，未拥有 search 的读写统一返回 404；搜索状态改为 `GeoSearchStatus` `StrEnum`。新回归覆盖声明超限零读取、chunked 超限在阈值停止、跨客户端未拥有的读写 404 和状态枚举。修复验证：同一 pytest 命令为 **31 passed in 4.48s**；Ruff 为 **All checks passed**（仅 uv cache ACL warning）；mypy 为 **Success: no issues found in 78 source files**。未访问公网、真实 GEO、模型或 Key。
- Task 34 所有权恢复修复：第一次创建搜索时生成高熵 HttpOnly/SameSite browser owner token，后续创建沿用该 cookie；每个 search snapshot 仅保存其 SHA-256，读写按 hash 比较，原 token 不进入 JSON、事件、日志、manifest 或 API 请求字段。所有者可以同时访问多个 search，使用同一 data/workbench state 的新 app/container 后仍可恢复访问；没有该 cookie 的另一客户端继续统一得到 404。红灯先确认旧 cookie 覆盖导致第一个 search 404；修复验证：同一 pytest 命令为 **32 passed in 4.64s**；Ruff 为 **All checks passed**（仅 uv cache ACL warning）；mypy 为 **Success: no issues found in 78 source files**。未访问公网、真实 GEO、模型或 Key。

## Task 35 Agent 搜索动作与搜索结果界面

- 会话在 `.worktrees/bio-agent-mvp` 的 `agent/bio-agent-mvp` 分支执行；用户已有的 `renv/activate.R` 空白改动保持未恢复、未格式化、未暂存或提交。
- TDD：先为严格的 `dataset_search` 动作和 Agent 搜索轮次新增测试。首次后端定向运行如预期失败（动作未知、turn 为 `FAILED` 而非等待选择）；首次前端组件测试如预期因模块不存在而失败。随后新增的 Agent 搜索读取回归先复现浏览器所有权检查返回 404，再转绿。
- `DatasetSearchAction` 仅接受受限的检索字段，不接受 URL、路径或额外字段；`ToolLoop` 和受限 GEO 工具目录将其作为终止动作。`TurnService` 经受控依赖注入创建 `DatasetSearchQuery`，保存 nullable `Conversation.geo_search_id`，投影 `geo.search.updated`/`geo.search.selected` 事件并要求用户选择结果；GSE 编号路径继续使用既有 `geo_lookup`。搜索不下载数据、不创建分析运行。
- 为恢复 Agent 创建的搜索，API 仅在没有 GEO browser-owner cookie 时接受受控 `conversation_id`，并同时核验 HttpOnly workbench owner cookie 的持久化 hash、`conversation.geo_search_id` 与 search record 的 `conversation_id`；直接从浏览器创建的搜索仍要求其原有 HttpOnly owner cookie，跨客户端读、分页、选择和取消均为 404。选择成功后复用既有 source discovery，保留 search ID 供后续 provenance。
- 前端新增服务端状态驱动的搜索结果卡与 API client：纯文本渲染不可信标题/摘要，官方链接固定 `target="_blank" rel="noreferrer"`，选择按钮为“检查可分析文件”，`NEEDS_INSPECTION` 明示仍需检查 raw counts；分页、取消与重试均使用服务端 revision/token，SSE 或重载按 conversation 的 search ID 恢复状态。
- 独立审查先发现 Agent search 仅按无 owner token 放行会暴露给知道 UUID 的其他客户端；已改为 conversation owner hash 绑定并补跨客户端 404、错误 conversation 与重启持久性回归，复审无 Critical/Important。
- 提交前验证：`uv run --offline pytest tests/unit/workbench tests/integration/api/test_workbench_tools.py tests/integration/api/test_geo.py -q -p no:cacheprovider` 为 **61 passed in 6.29s**；`npm --prefix frontend run test -- --run` 为 **16 files / 32 tests passed**；前端 `typecheck` 与生产 `build` 退出 0；`uv run --offline ruff check .` 为 **All checks passed**（仅 uv cache ACL warning）；`uv run --offline mypy src` 为 **Success: no issues found in 79 source files**。所有测试使用 Mock；未访问公网、真实 GEO、模型或 Key。
- 下一编号任务为 **Task 36：搜索 provenance、RAG 接口与端到端验收**；本任务未开始 Task 36。

## Task 36 搜索 provenance、RAG 接口与端到端验收

- 会话开始确认既有 `.worktrees/bio-agent-mvp`、`agent/bio-agent-mvp` 分支和用户已有的 `renv/activate.R` 空白改动；该文件全程未恢复、格式化、暂存或提交。
- TDD 红灯：`uv run --offline pytest tests/unit/retrieval/test_knowledge.py tests/unit/geo/test_geo_search_service.py tests/unit/geo/test_geo_repository.py tests/unit/artifacts/test_manifest.py -q -p no:cacheprovider` 在实现前以 4 个收集错误失败，分别为缺少 `bioagent.retrieval.knowledge` 与 `GeoSearchProvenance`；这是新契约尚不存在的预期失败。实现后同一聚焦集合为 **51 passed in 1.96s**，未访问公开 GEO、模型或 Key。
- 新增独立、冻结且 `extra=forbid` 的 `KnowledgeQuery`、`KnowledgeEvidence`、`KnowledgeRetriever`、`KnowledgeRetrievalError` 与默认 `NullKnowledgeRetriever`。证据要求 document/chunk/无凭据 HTTPS source URI 和 64 位 SHA-256；user-info、HTTP 和 `token`/`key`/`authorization` 等敏感 query 字段稳定拒绝。未配置时稳定返回 `RAG_NOT_CONFIGURED`。它不解析为 `DatasetSearchQuery` 或工作台 action，依赖容器只允许显式 override，不增加知识动作、向量库、上传或凭据表。
- 搜索结果选择时由已认证搜索快照生成冻结 `GeoSearchProvenance`（search ID、query/evidence hash、provider、accession、selection revision、检索时间）。搜索服务先持久化 `SELECTING` snapshot；`GeoImportService.create_source()` 必须从共享 `GeoSearchRepository` 逐字段重读这个 snapshot，`GeoRepository.publish()` 又必须从最终 `SELECTED` snapshot 逐字段重读。这样篡改 source state 后重新计算自洽 hash 仍会在 dataset 发布前拒绝，直接伪造 provenance 也不能成为 source。随后才写入 `source.json` 及规范 JSON SHA-256，读取时仍重新验证。直接 GSE 与上传来源继续没有 provenance，旧 manifest 以 `None` 读取。
- `AnalysisService` 仍先以 `GeoRepository.read()` 验证 source，再复制唯一的受控 `source.json` 到 run；`ExecutionController` 在 execution key、执行、复用和恢复前校验 source artifact hash、source/dataset ID、provenance accession 及 hash，并以容器注入的同一 `GeoSearchRepository` 重读权威 `SELECTED` 搜索快照。它只把该只读验证值写入 `RunManifest.search_provenance`；篡改 selection/accession、query/evidence 或 provenance hash（即使攻击者同时重算自洽 hash）稳定拒绝 `SOURCE_SEARCH_PROVENANCE_TAMPERED`，不会调用 runner。
- 新增本地 `httpx.MockTransport` + 合成 counts 的 Python e2e：搜索快照 → 选择 GSE → source → dataset → run manifest 的 ID/hash 链一致，raw counts/mapping 确认前没有下载、计划批准前没有 attempt，且 RAG 未配置不会影响 GEO。它为 **1 passed in 14.35s**。Task36 聚焦回归（`tests/unit/retrieval tests/unit/geo tests/e2e/test_geo_search_workflow.py tests/e2e/test_geo_workflow.py`）通过；Ruff 为 **All checks passed**，mypy 为 **Success: no issues found in 80 source files**。
- 新增 Playwright route-fixture 流程，覆盖关键词输入、候选、选择、raw-count 确认、映射、批准和 COMPLETED；选择前断言 import/download 请求为零。`npm --prefix frontend run e2e -- --grep "keyword GEO search"` 为 **1 passed (2.4s)**；Vitest **16 files / 32 passed**，typecheck 与 production build 通过。
- 完整 `./scripts/check.ps1` 已退出成功；前端安装、Vitest、typecheck、build、完整 Playwright、Ruff、mypy、Python/R/DESeq2 分项与 renv 同步检查均已执行。`uv run --offline pre-commit run --all-files` 的 8 个 hooks 全部通过。测试只使用本地 fixture、MockTransport、route fixture 与合成 counts；没有真实 GEO 下载、真实模型或 Key。
- Task36 复审修正：先新增 credential-bearing URI、直接伪造 provenance、source state 篡改和完整 source→dataset→manifest 链回归；修正前聚焦集合为 **8 failed, 29 passed in 13.88s**（URI 规则缺失，且测试也暴露了未完成的 provenance 权威边界）。修正后 `tests/unit/retrieval/test_knowledge.py tests/unit/geo/test_geo_service.py tests/unit/geo/test_geo_search_service.py tests/unit/geo/test_geo_repository.py tests/e2e/test_geo_search_workflow.py` 为 **46 passed in 14.06s**；Ruff/mypy（80 个 source files）通过，关键字 GEO Playwright fixture 为 **1 passed in 2.6s**。完整门禁复跑结果见本任务提交记录；仍未访问公网或凭据。
- Task36 最终复审修正：TDD 先把已发布 `source.json` 的 `query_hash` 改写并重算 `search_provenance_sha256`，再经真实 `AnalysisService.create_run()`，红灯为 **1 failed in 17.02s**（未抛 `GeoRepositoryError`）；另一个 Controller 回归先因缺少显式 `search_repository` 依赖红灯。`GeoRepository.read()` 现在对非空 provenance 重读持久化 `SELECTED` snapshot，`ExecutionController` 也通过依赖容器取得同一仓库并在执行、复用/恢复前逐字段验证。修正后两条回归为 **2 passed in 17.20s**；包含 controller、GEO repository/search、RAG、manifest、直接 GSE API、本地 upload 和两条 GEO e2e 的离线集合共 **102 tests collected**，运行至完成且无失败（退出 0）。Ruff 与 mypy（80 个 source files）通过，关键字 GEO Playwright route fixture 为 **1 passed (2.4s)**；不访问公网、真实模型或 Key。
- Task36 最终双重独立审查又发现 API 启动恢复未重读权威搜索快照、删除 provenance 可降级为直接 GSE、另一条真实搜索快照可跨 source 替换，以及 evidence URI 对预签名/fragment 凭据覆盖不足。TDD 红灯分别覆盖启动恢复伪造、缺失/替换 provenance 和 URI 变体；修正后搜索快照以 `source_id` 绑定，发布、读取、导入、AnalysisService、Controller 与启动恢复均失败关闭，直接 GSE/上传仍兼容。合并相关回归为 **187 passed in 67.67s**；Ruff 为 **All checks passed**，mypy 为 **Success: no issues found in 80 source files**。测试只用本地 fixture，`renv/activate.R` 仍未暂存或修改。
- Task36 提交后质量复审补出一个恢复一致性问题：重启时持久化的 `SELECTING` 记录改为 `FAILED` 后仍保留 selection 字段，导致后续读取报 `GEO_SEARCH_STATE_INVALID`；同时补齐依赖覆盖下的搜索仓库绑定，以及 `X-Amz-Security-Token`、`session_token`、`refresh_token` 三类 evidence URI 凭据名。三个红灯场景修复前为 **5 failed, 12 passed**，最小修复后为 **17 passed**；最终受影响合并回归为 **195 passed in 82.33s**，Ruff 与 mypy（80 个 source files）通过。恢复后的记录可跨再次重启读取，覆盖的 `GeoRepository` 使用容器同一权威搜索仓库。

## Task 34–36 整体复盘

- 受控搜索、受控选择和既有下载/映射/分析审批保持三段式：搜索文本、标题和摘要不可信，搜索本身不能创建 import 或 run；只有选中的、所属及 revision 已验证的 GSE 才能进入 source discovery，raw-count 与人工计划审批仍是不可绕过的关口。
- 选择 provenance 由后端快照生成并在 source/run 两端校验 hash，读取、执行、复用和恢复还逐字段重读权威 `SELECTED` snapshot；query、selection revision、accession 或 evidence 被替换并重算自洽 hash 时也不会复用来源或执行。直接 GSE、上传和旧 manifest 保持兼容。
- `DatasetCatalogProvider` 只服务数据目录搜索；`KnowledgeRetriever` 保持独立且当前显式未配置。证据或 manifest 不保存凭据，没有新增统计方法、自动批准、真实账户调用或多 Agent 编排。

## 新会话启动提示词

```text
扩展计划任务 28–38 已完成。下一编号任务为 Task 39，由父会话验收后安排。进入既有 .worktrees/bio-agent-mvp，确认
agent/bio-agent-mvp 分支，按 AGENTS.md 读取设计/计划/进度及 Git 状态。
随后读取 2026-09-08-extensions-design.md 和 2026-09-08-extensions.md。
Task 38 规格和计划为 2026-10-12-literature-rag-design.md / 2026-10-12-literature-ingestion.md。
同时读取 docs/knowledge-ingestion.md 和 docs/research/2026-10-12-docling-experiment.md。
Task 38 已实现知识库/PDF/job/revision、离线 Docling 及受控资源 API，状态止于 PARSED。
只实施 Task 39 检索/API；先制定计划和失败测试，不实现 Task 40 前端集成。
自动模型和 GEO 测试继续用 Mock，不读取真实 Key。真实模型 API/账户联调由用户后续明确配置。
保持明确人工审批和原统计执行边界；不要回改已完成的任务 28–33。
如需继续，先获得用户明确授权再做真实 API/账户联调；保留旧 PR Draft，不推送、不合并、不新建 worktree。
```

## Task 37 模型设置与统一调用

- 已读取权威资料、确认既有 worktree 和 `agent/bio-agent-mvp` / `24374c9`；保留父任务交接规格与进度。`renv/activate.R` 为用户原有空白改动，不恢复、不暂存、不提交；根目录 main 的 `runs/` 未操作。
- 使用 writing-plans 制定单编号任务计划，沿用当前会话执行。模型设置移入“设置 → 模型与 API / Skills / MCP”，保存多个配置、编辑选择与聊天选择独立，对话选择通过既有 PATCH 持久化。异步保存禁重复，凭据成功返回值更新配置状态；失败重读真实配置并提示部分保存风险，不显示伪成功。
- ModelAdapter 统一装配聊天与 Planner，PreparedChat 只在服务端内存持有同一客户端创建的 Planner；上传规划复用该 Planner，GEO READY 按原 turn 的固定 snapshot 在边界重新解析凭据。每次规划构建独立图，共享 checkpoint/执行依赖，客户端/凭据/闭包不进入状态或科研记录。审批恢复沿用保存的计划，不重选模型；旧无 profile API 与默认 readiness 保留。
- 生产适配器补齐受限 `plan_analysis` 工具及选中 dataset ID 上下文；动作仍经强类型和数据集所属校验，不能批准或执行分析。GEO 配置删除/凭据缺失通过 `run.updated` 稳定失败事件显示，禁止回退环境模型。
- TDD：最初后端新增用例为 **1 failed, 6 passed**，发现生产工具目录缺少 plan_analysis；前端为 **1 failed, 3 passed**，复现重复保存没有禁用。随后额外临时移除当轮 Planner 绑定，单条 Ollama 用例稳定红灯 **1 failed, 8 deselected**，表现为环境 Planner 导致 VALIDATION_FAILED；finally 已恢复文件。三个协议均用 Mock、系统凭据库用内存替代，无真实账户调用。
- 验证中间结果：模型/工作台/上传/GEO 定向 **119 passed**；受影响 API+模型+工作台+GEO e2e **171 passed in 128.12s**；最终协议/审批/readiness 聚焦 **107 passed in 42.08s**。Vitest **16 files / 33 passed**；Playwright **5 passed (6.0s)**（含独立设置、对话记忆、删除恢复入口和窄屏）；typecheck/build、全仓 Ruff 与 mypy（80 source files）通过。最终关键用例（增加审批和默认 readiness 断言、失败规划防伪审批）为 **9 passed in 38.68s**；pre-commit 全仓 **8 hooks passed**。`git diff --cached --check` 曾发现计划 EOF 空行，已修复后退出 0。

- Task37 收尾：规划文档已单独提交 `dbf7877`；实现与使用文档另作任务 37 提交。最终没有新增包、数据库重建或迁移、真实 Key/账户调用、push、merge 或 PR。`/ready` 对没有环境 Key 的旧默认模型仍返回 503，而页面配置的三种 Mock 协议可以完成聊天、上传/GEO 规划及审批；系统凭据库与真实 provider 能力仍需用户自行联调。
- 保留 `renv/activate.R` 原有未提交改动，收尾核对 SHA-256 为 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。提交后 Git 实际状态保留 `M renv/activate.R`；收尾时另出现未跟踪 `docs/research/` 与 `docs/superpowers/specs/2026-10-12-literature-rag-design.md`，属于任务外改动，未读取、修改或暂存。没有下一编号任务授权，停止开发。
- 父会话独立验收（实现提交 `4af770f`）：审阅设置选择/聊天选择分离、ModelAdapter 与 PreparedChat 的 Planner 绑定、上传/GEO snapshot、审批恢复和旧 API/readiness 路径；重跑 `uv run --offline pytest tests/integration/api/test_workbench_analysis.py -q -p no:cacheprovider` 为 **9 passed in 39.16s**，`git show 4af770f --check` 退出 0。默认沙盒首次无法访问 uv 解释器，改用已审批执行后成功；未访问真实模型或读取真实 Key。没有发现阻止进入 RAG 设计阶段的问题。上条“没有下一编号任务授权”描述 Task 37 子会话限定范围；父会话已获用户授权准备后续 RAG，具体设计审批状态以本文件顶部为准。

## Task 38 本地文献导入与结构化解析

- 会话使用既有 `.worktrees/bio-agent-mvp` / `agent/bio-agent-mvp`，起点 `31a8307`。按已批准 RAG 规格编写单任务实施计划；子代理仅做兼容性实验和独立规格/质量审查，没有多 Agent 产品编排。保留用户 `renv/activate.R` 改动，根目录 main 的 runs 未操作，不 push/merge/PR，也不创建下一聊天。
- 新增 SQLite 库/document/job/revision、同库 SHA256 去重、异库隔离、新 revision 重试和先撤销可见性的删除。完整性校验与发布条件在同一事务内，取消/删除/迟到结果不能重新发布；只发布 PARSED，index_revision 始终为空。原文、Docling 原始 JSON、归一化元素、模型/设置快照及 PNG 全部保存哈希；资源 API 每次核验所属关系和哈希。
- 默认安装不引入 Docling。可选 rag extra 固定实测 Docling 2.58.0、core 2.101.1、ibm-models 3.15.0、parse 4.7.3、torch 2.14.1、RapidOCR 3.10.0、onnxruntime 1.31.0；基础新增 psutil 7.1.0。显式 prepare 固定 11 个公开模型文件来源、长度和 SHA256，共 **400,650,044 bytes**，运行时无下载且逐文件核验。实际官方配置下载及完整 bundle 复用校验成功，readiness=true；模型权重仅在 ignored data。
- 单 supervisor 串行执行固定离线 Python worker，不继承模型 Key，不执行文档代码；关闭 remote services/plugins/视觉增强并拒绝 socket 连接。最多 4×10 MiB PDF/批、200 页、600 秒、4 GiB 进程树 RSS、100 MiB 输出；超限/取消杀进程树。重启持久化 INGESTION_INTERRUPTED 并清理失败/取消未发布目录，Windows 文件占用时下次启动重试；删除目录在 worker 退出及启动恢复再次清理。保留原文和 job 审计记录。
- knowledge API 沿用 Host/Origin/CSRF，提供库 CRUD、多文件上传、任务/文献状态、重试/取消/删除、原文/结构/PNG；请求不接受服务器路径。response/readiness/error 均有 OpenAPI 模型。原 HTTPS KnowledgeEvidence 不变，本地独立 local-reference.v1 为后续索引保留 base/document/revision/element/page/hash。
- TDD 首次因 knowledge/service 模块不存在失败；审查发现的 Windows 原文占用、重启目录残留均补失败测试后修复。规格复审通过，质量复审无 P0/P1/P2；唯一 P3 已修复，独立 store 回归 **6 passed in 0.41s**。
- 最终命令 `uv run --offline pytest tests/unit/knowledge tests/unit/retrieval tests/unit/domain/test_runs.py tests/integration/api/test_knowledge.py -q -p no:cacheprovider`：**39 passed in 7.37s**。完整 API 目录单独运行 `uv run --extra rag --offline pytest tests/integration/api -q -p no:cacheprovider`：**87 passed in 152.10s**。全仓 Ruff 通过（旧 pytest 目录 ACL warning），mypy **90 source files** 通过；wheel 构建及 model_catalog.json 包含检查通过。最终暂存检查结果见下条收尾记录。
- 真实 CPU API 验收命令 `uv run --extra rag --offline python scripts/verify_literature_ingestion.py --output data/task38/api-acceptance-final`：3 份自制 PDF 共 4 页全部 PARSED/index_revision=null。digital/scan/cross-page 分别 **13.031/12.532/11.922 秒**，peak RSS **1,141,379,072/1,120,493,568/1,164,365,824 bytes**。核验扫描 OCR、表头/单位/脚注、坐标页码、图片 OCR/裁剪/PNG 和删除后资源不可读。所有样本与 acceptance.json 位于 ignored data，未使用用户 PDF、真实 LLM/Key 或真实 GEO。
- 质量限制与阻塞：无任务 38 阻塞。双栏样本左右行交错，跨页表格保留独立片段，图片 OCR 有空格丢失，图注/脚注可能关联缺失；保留完整原始结构并告警，视觉语义为 not_performed。资源监督为采样限制，非 native-code 操作系统沙盒；仅支持一个后端实例。真实账户调用、生产语料质量和 Task 39 embedding 实验仍未验收。
- 安装/准备/使用见 `docs/knowledge-ingestion.md`，模型许可证/硬件/样本逐项结果见 `docs/research/2026-10-12-docling-experiment.md`。下一任务为 Task 39 检索/API；必须再核验 parse/source/assets，构建完整独立 index revision，再比较当前 parse/deleted 状态事务发布 READY。
- 收尾：26 个任务文件明确暂存后，`uv run --offline pre-commit run --all-files` **8 hooks 全通过**，`git diff --cached --check` 退出 0；未暂存 renv、数据、权重、PDF、.env 或运行产物。默认沙盒写 worktree index.lock 被拒后，使用用户已授权的 Git 提交权限完成暂存。用户文件 `renv/activate.R` SHA256 仍为 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`，留作唯一预期未提交改动。
- 父会话独立验收（2026-10-12，`955a6f0`）：审阅事务发布/取消/删除、受控资源完整性、离线 worker、可选依赖与 API 边界。聚焦集合 `uv run --extra rag --offline pytest tests/unit/knowledge tests/unit/retrieval tests/unit/domain/test_runs.py tests/integration/api/test_knowledge.py -q -p no:cacheprovider` 为 **39 passed in 7.31s**。独立重跑真实 API 脚本，产物在 ignored `data/task38/parent-acceptance-20261012/`：3 份自制 PDF 共 4 页全部 PARSED，digital/scan/cross-page 为 **13.046/12.516/12.312s**，峰值 RSS **1,111,699,456/1,174,261,760/1,174,597,632 bytes**；扫描 OCR、表头单位脚注、图片裁剪及删除失效断言全部通过，退出 0。`git show 955a6f0 --check` 退出 0，用户 renv 哈希未变。接受已明确记录的双栏阅读顺序和跨页表格质量限制，未发现阻止任务 39 的问题；授权进入下一模块，不能宣称完整 RAG 已完成。
