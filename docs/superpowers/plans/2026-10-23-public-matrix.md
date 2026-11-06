# Task49 真实公开表达矩阵验收计划

> 使用 writing-plans、executing-plans；涉及兼容修复时严格TDD。用户已经批准方向，本聊天内执行唯一49，完成后交父会话独立验收。

**目标：** 核实至少一个适合既有非配对双组DESeq2的真实公开raw counts研究，验证受控下载/映射、单文件入口、人工审批和真实统计/图表/报告。

**架构：** 复用GEO搜索、来源、下载、映射API与48单矩阵API，外部Planner使用Mock，RRunner保持真实。专用脚本默认只用SHA256锁定的本地缓存，只有显式`--download`访问固定官方来源；研究数据/统计产物仅放ignored data/task49。必要兼容修复限于已定位的确定性格式或官方协议差异，不增加科学方法。

**技术栈：** 现有uv/Python、httpx、FastAPI TestClient、GEO transport、pandas、Rscript/DESeq2、pytest、Playwright；不升级依赖。

**起点与约束：** 5a03065，既有.worktrees/bio-agent-mvp / agent/bio-agent-mvp。保留renv原SHA256 A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A；不动用户8000、根runs、旧付费台账，不读取Key/真实LLM、不push/merge。只领取49，不进入50。

## 文件与步骤（均属同一编号49）

- 创建`scripts/verify_public_matrix.py`：固定研究、官方URL/hash/样本设计、显式联网缓存准备与真实HTTP/R验收，输出下载审计和acceptance.json。
- 创建`tests/unit/test_public_matrix_acceptance.py`：离线微型fixture验证缓存篡改拒绝、样本映射完整/唯一和显式联网开关；在实现脚本前执行红灯。若已有入口遇到真实协议/格式缺陷，先把脱敏最小响应放对应GEO单元测试再修复；只改被回归证明的模块，不预设需要修改生产代码。
- 创建`docs/public-matrix.md`与`docs/reviews/2026-10-23-task49.md`：使用命令、官方出处/来源hash/样本表/处理历史、真实验收及未通过入口、科学局限。
- 修改本计划与`docs/progress/current-state.md`；不提交下载数据、SQLite、统计/图表/截图。

实际必要兼容文件：`src/bioagent/geo/client.py`与`tests/unit/geo/test_geo_client.py`（有界stream、完整family、官方可选目录空响应）；`src/bioagent/geo/service.py`与`tests/unit/geo/test_geo_service.py`（gzip内部后缀）；`src/bioagent/api/local_access.py`、`src/bioagent/api/app.py`与`tests/integration/api/test_matrices.py`（仅multipart矩阵上传沿用上传限额，普通JSON仍32KiB）；`r/deseq2/functions.R`、`r/tests/testthat/test-zero-features.R`、`src/bioagent/execution/controller.py`与`tests/unit/execution/test_controller.py`（既有全零去除契约、最终保留输入QC）。新增`frontend/e2e/public-matrix.spec.ts`只读取显式指定的真实验收证据，以HTTP route fixture验证实际矩阵/结果展示，不改变生产UI或冒充浏览器现场运行R。

报告补充文件：`src/bioagent/reporting/templates/report.html.j2`及`tests/unit/reporting/test_generator.py`。实际复核发现HTML只显示QC文字、不显示7132数量，红灯后增加安全转义的JSON证据展示；不改变统计或LLM叙述。

- [x] **核实来源。** 搜索官方GEO/作者论文及样本记录，下载官方原始文本供核验。优选同平台同处理的独立生物重复每组≥3；至少2。排除配对设计、技术重复、TPM/FPKM/log或缺乏raw依据的候选。记录候选弃用原因。保留下载UTC时间、实际URL/bytes/SHA256；不能只凭文件名判断raw。
- [x] **实测既有GEO路径。** 用真实受控transport搜索/选择/来源发现/下载/映射，保存实际响应与失败。网页recaptcha不直接归因为后端不可用；不绕过验证或扩大allowlist。若自动入口不能走通，记录具体步骤并独立验证官方缓存+单文件入口，不宣称GEO完整通过。
- [x] **先跑失败测试。** `uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/unit/test_public_matrix_acceptance.py -q -p no:cacheprovider --basetemp data/task49/red`，预期脚本功能缺失；针对实际兼容缺陷另跑精确GEO回归红灯。确认失败原因后才实现。
- [x] **实现可复跑验收。** 固定源hash校验与完整样本设计，不将标准化值取整，不任意过滤基因。允许明确、可审计的压缩解包/表头适配/逐样本ID一致性合并。样本纳入/排除写入审计；来源原文件与转换输出分别hash。脚本使用受控API自动生成metadata、确定性Mock计划，比较方向与官方样本证据一致。
- [x] **真实R验收。** `uv --cache-dir data/task48/uv-cache run --no-sync --offline python scripts/verify_public_matrix.py --download --output data/task49/acceptance`首次显式下载；相同命令去掉`--download`可离线复跑。确认raw来源和分组前R调用0；计划批准前无attempt；显式批准后Rscript完成。验证实际结果CSV、PCA/相关热图/MA/火山图、QC/报告及manifest所有产物SHA、输入hash/参数/方向和结果摘要计数。完整数据运行，不为通过隐性裁剪。
- [x] **界面与回归。** 使用隔离端口/实际矩阵及摘要验证表单/计划/产物展示，截图ignored。无UI修改只跑专用浏览器项，不重复全浏览器。受影响pytest覆盖GEO与矩阵入口；如改TS则typecheck，未改不伪报新前端全验收。全仓Ruff/mypy、8hooks及`git diff --cached --check`必须通过。
- [x] **记录与提交。** 来源、全部红绿/失败记录/真实命令结果/样本局限已更新至使用说明、复核和进度；8项pre-commit全通过。仅明确暂存本计划列出的20份49文件，以含任务49的message本地提交，cached检查和提交后Git/renv哈希核对后停止写入，交父会话独立验收。

## 验收判断

验收至少证明一个真实公开研究在既有方法适用范围内，从官方提供的counts到实际统计产物可复跑；这不是原论文全部结果复现、真实LLM效果或任意GEO兼容性声明。QC警告、来源入口失败、独立过滤/NA及模型Mock必须明确报告；不以文件存在代替内容/hash/计数一致性验证。

## 实际收尾证据

完整联网真实验收命令使用新输出`data/task49/final-verification`，退出0；GEO READY自动run和单文件run各审批后真实R一次，20047行统计三列在rtol1e-8/atol1e-10一致。只去除4样本全零7132行，输入hash/来源保留，最终QC WARN和报告数量均核验。离线默认模式输出`data/task49/offline-final`，退出0/R一次/同结果hash；无GEO当次联网声明。

最终187项离线pytest为102.90s；R全testthat为21 tests/44 passed expectations/0失败；专用浏览器真实数据route fixture两项5.0s，截图及四类实际图均已查看。Windows一次os.replace权限失败已记录、单项6.47s复验及最终整套通过。Ruff、mypy114源文件、前端typecheck及8hooks通过，最后明确暂存20文件、cached检查退出0后提交；提交号以Git为准。没有未记录的科学过滤、真实LLM/Key、依赖升级、push/merge或用户服务操作；renv哈希保持原值。

## 父会话并行审查闭环（仍属 Task49）

用户明确授权增加并行聊天。三路按界面、统计/来源、接口/事务只读审查，父窗口核实七项问题后分配互斥文件修复；父窗口是唯一 Git 暂存和提交者，不创建 Task50。具体红绿及失败复验见 `docs/reviews/2026-10-23-task49-parent.md`。

追加修复文件：`frontend/src/features/chat/MatrixImport.tsx` 与组件测试；`src/bioagent/tools/deseq2.py`、runner 测试、公开验收脚本及其单元测试、新增 `tests/integration/api/test_matrix_summary_boundary.py`；`src/bioagent/api/matrix_routes.py`、`src/bioagent/geo/client.py`、`src/bioagent/services/analysis.py`、`src/bioagent/workbench/store.py` 及矩阵/GEO 回归。父窗口维护本计划、进度、来源说明与独立验收记录，不暂存 renv 或运行产物。

- [x] 核对官方原始数据、样本设计，独立完成真实 GEO/单文件双路径 R、登记产物 hash、实际图表和报告验收。
- [x] 修复上传替换/转置一致性、阈值等号及 NA 描述、GEO 正文异常、上传并发、取消与发布互斥；复核真实缓存 R 结果 hash 不变。
- [x] 独立串行复验全部矩阵与旧审批关键边界，记录并解决测试前置超时导致的故障注入覆盖不确定性；最终22 passed / 174.57s。
- [x] 父验收记录与进度完成，明确暂存18份任务文件后八项 hooks、cached diff 检查通过；由父窗口统一作单次 Task49 修复提交，提交后删除自动跟进并停止本轮工作，提交号/最终状态以Git为准。
