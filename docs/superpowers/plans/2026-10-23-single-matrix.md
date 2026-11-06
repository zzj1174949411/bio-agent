# 单表达矩阵到真实双组分析实施计划

使用 writing-plans/TDD；唯一 Task48，起点d4489b8。既有worktree单写入，不push/merge，不动renv、根runs或用户8000。

目标：单CSV/TSV上传，持久化预览和列/方向/分组/来源确认，生成规范counts+metadata并直接进入所选模型的既有AnalysisService待审批流程；真实R验收与旧规范路径比较。

文件：新增`services/matrices.py`确定性有限解析/SQLite草稿/幂等确认，`api/matrix_routes.py`owner与受控上传/确认/规划，app注册；新增`features/chat/MatrixImport.tsx`对话内表单，Composer与ChatWorkspace接线，api/client类型；测试`tests/integration/api/test_matrices.py`和`tests/e2e/test_matrix_workflow.py`、前端MatrixImport测试及浏览器矩阵用例；使用说明、进度和本计划。

- [x] 红灯：缺服务；上传不要求feature_id；NA/小数/负/重复/不足两样本拒绝；非raw拒绝；方向/分组确认与hash保留；跨owner、旧revision、重复确认、重启恢复。
- [x] 最小后端：固定CSV解析无代码执行，沿用原上传字节/行列/超时限制；UUID/SQLite原始bytes+hash与确认JSON、规范文件绑定。只支持raw counts，显式transpose；每组≥2。确认后固定配置调用原Planner并确定性核验dataset/比较，创建WAITING_USER，不执行R。幂等同payload返回原结果，冲突拒绝。
- [x] 前端：加号单矩阵入口，研究目标、预览、方向、ID列、样本纳入/分组及比较/raw来源对话表单，保存并恢复；确认生成dataset及run，不要求第二文件或手找API。原pair/GEO/知识入口保留。
- [x] 真实验收：合成矩阵通过新HTTP上传/确认生成metadata，审批前attempt/R为零，明确批准后真实Rscript/DESeq2，核验表/四图/QC/报告/manifest与同规范旧pair路径数值一致，输出ignored data/task48。
- [x] 门禁：受影响pytest、全部Vitest/typecheck/build、矩阵及相关Playwright（320/390px、取消恢复、文件），Ruff/mypy、8hooks/cached检查，更新文档与进度，逐文件提交含任务48 message后停止。

命令：`uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/integration/api/test_matrices.py tests/e2e/test_matrix_workflow.py -q -p no:cacheprovider --basetemp data/task48/verification`；`npm --prefix frontend test -- --run --maxWorkers=2`、`typecheck`、`build`、`e2e -- --workers=1`；`uv ... ruff check .`、`mypy src`、`pre-commit run --all-files`、`git diff --cached --check`。

不读取Key，不用真实LLM/旧付费额度。不扩展TPM方法/FASTQ/任意附件；整数外观不证明raw来源。运行和解释必须来自实际产物，不以仅文件存在替代数值验收。


执行证据：初始缺少MatrixService收集红灯，最小持久化测试通过；补齐HTTP和数值拒绝、owner/重启/幂等/worker超时等测试。真实R首次仅因错误文件名断言中止，修正后新旧路径完整一致性通过。最终17项矩阵/真实R/产物测试94.51s、18项聊天/知识回归11.67s；51项前端11.29s；默认浏览器16通过/3跳过26.2s，补结果阅读专项3通过7.2s；typecheck/build、Ruff、mypy114文件通过。详细内容和限制见`docs/reviews/2026-10-23-task48.md`。

实际文件另包括`docs/single-matrix.md`、复核记录、`frontend/src/styles.css`（表单窄屏）、进度；其余文件见上方。所有统计/截图/源bytes/SQLite/模型留在ignored data/task48。未改变原R入口或统计方法。收尾逐文件暂存、8hooks/cached与renv哈希核对后提交。

收尾：明确暂存17份任务48文件后，8项pre-commit全部Passed，cached diff检查退出0。renv SHA256仍为A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A，未暂存或修改。使用含任务48编号的commit本地提交，提交后检查Git仅剩用户renv；不push/merge，不自动实施49。后端需在用户自行重启/父会话部署服务后加载，本聊天未操作其8000进程。

## Task48 父会话审查修复

父会话对实现提交`dd58288`复现：Planner异常后GET仍为PLANNING。原因是finally中的UPDATE随外层连接上下文重新抛错而回滚。

- [x] 先补正式失败持久化、重启遗留PLANNING和JSON对象键重排回归。红灯命令`uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/integration/api/test_matrices.py -q -k 'durable_terminal or abandoned or http_owner' -p no:cacheprovider --basetemp data/task48/failure-red --tb=short`：**3 failed, 11 deselected in48.47s**，分别复现失败后仍PLANNING、启动未恢复和同请求键重排返回冲突。
- [x] 终态以独立事务提交；失败保存MATRIX_PLANNING_FAILED并结束turn。启动在聊天服务启动前将遗留PLANNING标记为FAILED/MATRIX_PLANNING_INTERRUPTED，不调用Planner、不创建或批准新run。重复确认失败记录稳定409。确认JSON递归排序对象键后生成SHA256，并兼容既有确认记录；数组顺序和科学参数冲突仍保留。
- [x] 修复后`uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/integration/api/test_matrices.py tests/integration/api/test_workbench.py -q -p no:cacheprovider --basetemp data/task48/fix-regression --tb=short`：**24 passed in86.46s**；Mock Planner，无真实模型或R调用。全仓Ruff通过，mypy114文件通过。本轮不重复真实R验收；父会话另作独立验收，不进入49。
- [x] 修复提交门禁：8项pre-commit全部Passed；仅暂存3份后端、1份回归和3份状态/审查文档。cached diff检查退出0后本地提交，提交后再次核对状态；保留renv，不push/merge。
