# 工作台滚动与上传反馈实施计划

> **面向 AI 代理的工作者：** 使用 executing-plans 在当前聊天内执行。全部步骤属于唯一编号任务 41；用户已授权此修复，任务 38–40 收尾记录为历史状态。不启动 42，不 push/merge，不重启用户 8000 服务。

**目标：** 桌面长聊天不再撑高整页；一次可选择 1–100 份、每份最多 50 MiB 的 PDF 自动上传，显示大小、进度和禁用/失败原因。

**架构：** 为桌面 grid/flex 祖先提供受限视口高度、可收缩轨道和独立滚动区；设置/知识库独立滚动。平板/手机恢复正常页面流以保证下方资源可达。按用户追加授权，单份上限提高至 50 MiB、一次选择 1–100 份；UI 逐份串行发送，HTTP API 仍最多四份/请求（201 MiB 含 multipart 余量），解析保持串行。后端 limits 契约为上传、Store、Docling、中间件和 UI 提供统一来源；超限项跳过，失败项单独重试，可停止尚未上传部分，目标库被冻结且卸载后不更新旧状态。

**技术栈：** 现有 React/TypeScript/CSS、Vitest、Playwright Chromium、固定 API fixture。

## 文件与职责

- `frontend/src/styles.css`：桌面三列视口/滚动约束、设置内容可达、窄屏回退及管理区基础控件样式。
- `frontend/src/features/knowledge/KnowledgeManager.tsx`：选中文件大小、数量/单文件超限/就绪/操作中提示及 readiness 独立失败反馈。
- `frontend/src/features/knowledge/KnowledgeManager.test.tsx`：合成 File 的 50 MiB、100/101 份边界、失败继续/仅重试失败、停止/卸载和 readiness 隔离。
- `frontend/e2e/usability.spec.ts`：真实浏览器长消息/侧栏/资源独立滚动、设置/知识库底部可达、390/1000 宽度可用及超限文件反馈。
- `src/bioagent/knowledge/limits.py`、`store.py`、`parser.py`、`api/local_access.py`、`api/knowledge_routes.py`：统一 50 MiB/四份 HTTP/201 MiB/100 份 UI 契约；`frontend/src/api/knowledge.ts`、`client.ts` 读取该契约。
- `tests/integration/api/test_knowledge.py`、`tests/unit/knowledge/test_store.py`：合成大于旧上限且合规文件可接收，50 MiB 边界、超限拒绝、四份/请求保护及 >41 MiB 请求可接收；Mock 禁止解析。
- `docs/knowledge-workbench.md`、`docs/knowledge-ingestion.md`、本计划、`docs/progress/current-state.md`：用户说明、实际结果、限制与收尾状态。

### 任务 41：修复整体滚动与上传无原因禁用

- [x] **步骤 1：保存计划并登记授权。** 确认 `agent/bio-agent-mvp` / `cb7ccba`，唯一既有改动为 `renv/activate.R`（SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`）。
- [x] **步骤 2：先写并运行聚焦失败用例。** 合成超限 File 显示 `oversize.pdf`、`50.01 MiB`、`超过单份 50 MiB`，合规 12 MiB 可启用。选择 100 份一次点击自动上传，失败后继续并仅重试失败项，101 份禁用并解释；等待 readiness/读取失败和卸载/停止隔离。浏览器在 1440×900 填充真实消息/项目/资源 fixture，滚动消息后 timeline.scrollTop > 0 且 window.scrollY = 0，标题/输入及侧栏坐标稳定。

```powershell
npm --prefix frontend run test -- --run src/features/knowledge/KnowledgeManager.test.tsx
# 在 frontend 目录：
npm exec --offline -- playwright test e2e/usability.spec.ts --workers=1 --output=../data/task41/red
```

- [x] **步骤 3：最小修复。** 桌面 `.app-shell` 高度 `100dvh`、轨道 `minmax(0,1fr)`，`.conversation/.chat-content/.timeline` 可收缩，侧栏/右列/设置明确各自 overflow。小于 1200px 恢复文档流，长消息/文件名可换行，资源不隐藏。上传以原因数组控制 `disabled` 与 `aria-describedby`，逐份显示大小及超限说明；分别处理 readiness/limits 成功失败。上传循环冻结库/文件，逐份 try/catch、累计已上传/总数，停止后保留未上传项；选择器上传期间禁用，卸载标记停止且忽略迟到状态。

```ts
const uploadIssues: string[] = [];
if (busy) uploadIssues.push("操作进行中，请稍候。");
if (!parser?.ready) uploadIssues.push("本地解析尚未就绪，请查看上方状态。");
if (!items.length) uploadIssues.push("请选择 PDF。");
if (limits && items.length > limits.max_files_per_selection) uploadIssues.push(`已选择 ${items.length} 份，超过每次最多 ${limits.max_files_per_selection} 份。`);
```

- [x] **步骤 4：验收受影响路径。** 同一失败用例转绿；验证左右列 scrollTop 独立变化，设置底部保存按钮/知识库最后一份文献可滚动到；390px、1000px 无横向溢出、资源及按钮可达。真实浏览器一次选择100份合成小文件，观察自动逐份上传、失败继续及只重试失败项；合规文件上传 API 为 fixture。不要读取/上传/解析用户 PDF，不访问真实供应商，不将 fixture 视为100篇解析质量验收。后端运行 `uv run --offline pytest tests/unit/knowledge tests/integration/api/test_knowledge.py -q -p no:cacheprovider`，静态 `uv run --offline ruff check src/bioagent tests/unit/knowledge tests/integration/api/test_knowledge.py` / `uv run --offline mypy src`。

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
# 在 frontend 目录，真实文献用例保持默认跳过：
npm exec --offline -- playwright test --workers=1 --output=../data/task41/final
uv run --offline pre-commit run --all-files
```

- [x] **步骤 5：收尾并停止。** 更新复选框、真实结果与限制，明确暂存上述 17 个任务文件，运行 `git diff --cached --check`，提交 `fix(任务41): 修复工作台独立滚动与PDF上传反馈`。再次确认 Git 状态与 renv 哈希；不执行 Python/R 全套、不启动下一编号任务。新 dist 需配合用户自行重启后端再刷新，浏览器缓存及运行服务静态文件版本需实际确认。

## 执行记录

- 起点 `cb7ccba`，工作区只有用户 renv 改动；根目录 main 的 `runs/` 不操作。用户新报告授权任务 41，原“停止自动跟进”约束继续适用于后续任务。
- 红灯：前端新增四项 **4 failed**；后端两项 **2 failed (6.53s)**，分别复现 Store 旧 10 MiB 拒绝及中间件旧 41 MiB 拒绝。浏览器首轮 fixture 使用了无状态更新的事件，并触发 Playwright 50 MB buffer 传输限制，不作为产品红灯；改用 turn.completed 和浏览器内合成 File 后 **2 failed, 1 passed (15.6s)**，timeline.scrollTop 始终为 0、超限提示缺失。修复后专项浏览器 **3 passed (6.6s)**。
- 后端定向 `uv run --offline pytest tests/unit/knowledge tests/integration/api/test_knowledge.py -q -p no:cacheprovider`：**32 passed (12.50s)**。4×11 MiB 合成 HTTP 上传成功，50 MiB Store 边界成功，超一字节拒绝；第五份 HTTP 文件拒绝。解析 supervisor 在大文件 API 用例中被 Mock，未解析用户文献。
- Python 静态：Ruff 初次指出测试五处行长，修正后通过；mypy **103 source files** 通过。默认沙盒无法访问 uv 解释器，使用已授权环境成功。前端全量首轮有 worker 临时文件 ENOENT，不作为产品失败；脱离该沙盒限制后 **18 files / 39 passed (2.57s)**。typecheck/build 退出 0。
- 默认浏览器全量 **8 passed, 1 skipped (12.3s)**：新三项以及既有模型、GEO/映射/审批、扩展、键盘/窄屏均通过。真实 Docling/E5/Qdrant 文献用例保持默认跳过，不重复任务 40，不声称真实100篇解析质量。截图位于 ignored `data/task41/final`，已实际查看桌面独立滚动、批量管理和390px文献底部画面。
- 最终只细化全无合规项提示并加强卸载回调断言，专项 **4 passed (1.38s)**；重新构建退出 0，最后浏览器专项 **3 passed (6.9s)**。上传目标库、停止、无效项跳过、100/101份、50 MiB精确边界覆盖。新 dist 已写入 ignored frontend/dist；用户运行中的8000服务未操作，需要由用户重启后端并刷新。未上传/失败列表只在当前页面保存；已导入文件由 Store 持久化和去重。
- 收尾门禁：八项 `uv run --offline pre-commit run --all-files` 全 Passed；17 个任务文件明确暂存，`git diff --cached --check` 退出 0。renv 未暂存，哈希不变；数据、截图、dist 均 ignored。Git 默认沙盒 index.lock 写入拒绝，按已有提交授权使用可访问主仓库 Git 索引的执行环境，不覆盖用户文件。任务到此结束，不启动42。
