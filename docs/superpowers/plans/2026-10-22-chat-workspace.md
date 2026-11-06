# 聊天主界面与既有能力整合实施计划

> 面向执行者：使用 writing-plans 与 test-driven-development，当前聊天内执行。全部步骤属于唯一编号 Task47；父会话已明确释放共享 worktree 写入权，不并发编辑，不创建新 worktree，不 push/merge，不启动48。

**目标：** 将获准的聊天原型布局接入正式 React，复用真实项目/聊天、数据导入、GEO、审批/运行、产物、知识库与设置能力。

**架构：** App 保留项目、对话与设置管理；拆出按 conversation ID 挂载的 ChatWorkspace，草稿/待导入文件/数据选择保存在父级内存的分对话记录，轮次/运行由既有 API/SSE 恢复。预览以共享宿主按需打开，文件和证据仍使用受控资源与撤销校验；关闭预览只影响阅读状态。产物列表补充 manifest 中的展示名/媒体类型，下载身份、完整性和审批边界不变。

**技术栈：** 现有 React/TypeScript、Vitest/Testing Library、Playwright/本机 Chrome；FastAPI 仅产物列表增补展示元数据，Python 通过 uv，模型/运行全部 Mock/固定本地 fixture。不升级依赖。

## 文件职责

- `frontend/src/App.test.tsx`：迟到创建响应不能覆盖新项目导航；
- `frontend/src/App.tsx`：项目/对话导航、设置与知识库视图、分对话草稿缓存；避免继续把聊天/运行/预览状态混在全局。
- `frontend/src/features/chat/ChatWorkspace.tsx`、`useRun.ts`：当前对话消息/SSE/GEO/上传/澄清、冻结轮次动作、真实审批与取消、轮询恢复运行；卸载后拒绝迟到响应。
- `frontend/src/features/chat/Composer.tsx`：受控草稿、加号“导入分析数据”面板、counts+metadata、模型与选库紧凑工具区。没有通用附件接口，不做假上传或单矩阵分析。
- `frontend/src/features/projects/ProjectSidebar.tsx`：项目下聊天、可展开的创建/改名操作、左下知识库与设置，窄屏抽屉。
- `frontend/src/components/FilePreview.tsx`：按需文件列表/标签/关闭，受控产物的图像、sandbox报告和有界文本/CSV预览，共享证据 portal 宿主；卸载释放 blob URL，文件切换取消旧读取。
- `frontend/src/features/chat/ChatTimeline.tsx`、`features/analysis/ApprovalCard.tsx`：对话内真实计划参数/明确审批、运行/QC与产物链接；保留 GEO/工具确认/知识回答。
- `frontend/src/features/knowledge/KnowledgeAnswer.tsx`、`KnowledgeWiki.tsx`：现有证据内容进入按需阅读区域，失败/撤销仍关闭；独立组件保留无宿主 fallback。
- `frontend/src/api/client.ts`、`types.ts`：产物展示元数据、有界受控文件读取和 abort；不接受模型任意URL。
- `frontend/src/styles.css`、`layout.ts`及测试：贴近原型的全高聊天、滚动、默认无右栏、窄屏预览/项目返回、深色兼容。
- `src/bioagent/api/routes.py`、`tests/integration/api/test_artifacts.py`：产物列表新增 basename/media_type，仍返回不透明 artifact ID，原下载校验不变。
- `frontend/src/features/chat/ChatWorkspace.test.tsx`、`Composer.test.tsx`、`components/FilePreview.test.tsx`、`ResourcePanel.test.tsx`（适用时迁移）、`features/projects/ProjectSidebar.test.tsx`、`api/client.test.ts`、`features/knowledge/KnowledgeAnswer.test.tsx`、`KnowledgeManager.test.tsx`：关键用户行为、受控读取、侧栏撤销和旧组件回归；管理器测试等待目标库初始化后再选择文件。
- `frontend/e2e/chat-workspace.spec.ts`、既有 e2e：新布局、文件开关/隔离、审批/取消/恢复、320/390px、键盘、GEO/知识/Wiki/设置入口；移除旧常驻右栏假设，不削弱功能断言。
- `docs/workbench.md`、本计划、`docs/progress/current-state.md`：真实范围、检查、截图路径、限制和45–47复盘交接。

## Task47（唯一编号任务）

- [x] **1. 红灯：** 先添加行为测试，确认旧实现失败：默认没有文件预览；点击产物打开/关闭；A草稿/数据不进入B，返回A恢复；A迟到消息/文件读取不能显示在B；批准前不提交approval，停止已运行任务调用run cancel；刷新/重入恢复已有run。产物 API 测试期望可读文件名。

```tsx
fireEvent.change(screen.getByLabelText('消息'), {target: {value: 'A草稿'}});
rerender(<ChatWorkspace key="b" conversation={chatB} {...propsB} />);
expect(screen.getByLabelText('消息')).toHaveValue('');
expect(screen.queryByRole('complementary', {name: '文件预览'})).toBeNull();
```

命令：`npm --prefix frontend test -- --run --maxWorkers=2 src/features/chat/ChatWorkspace.test.tsx src/components/FilePreview.test.tsx`；`uv --cache-dir data/task47/uv-cache run --no-sync --offline pytest tests/integration/api/test_artifacts.py -q -p no:cacheprovider --basetemp data/task47/api-red`。只接受缺少契约/行为红灯，环境错误另记。

- [x] **2. 实现隔离的真实聊天：** 拆分 ChatWorkspace/useRun，草稿与待导入pair按chat保留内存；dataset IDs从本聊天历史恢复。每个异步回调以生命周期/请求代际防过期，切换对话即卸载旧组件；SSE按原conversation恢复。正常聊天无常驻结果栏；设置、知识库与返回不终止在途任务。
- [x] **3. 导航和输入框：** 项目下聊天，展开创建/重命名/归档；左下管理知识库，输入框旁多选库及已有RAG/hybrid模式。加号只提供真实counts+metadata导入及明确知识库入口，保留数据校验结果和错误，不增加普通PDF附件发送、自动metadata、FASTQ或新统计。
- [x] **4. 文件和证据：** 受控产物ID列表增加basename/media_type；点击对话产物/报告打开阅读区，下载仍受hash校验。限制文本读取8MiB、文本/表格转义、PNG/JPEG图像、sandbox HTML，不把任意模型链接传入预览。证据复用原核验/撤销逻辑，共享侧栏；文件关闭/切换不调用运行取消。
- [x] **5. 审批、运行与恢复：** 计划显示真实comparison/options，按当前revision批准/拒绝；运行停止调用既有run cancel。轮询只更新本conversation/run，完成才取产物，失败显示稳定错误，恢复从本聊天SSE/历史turn ID找已有run，不自动创建新run/批准。
- [x] **6. 验收与收尾：** 全前端Vitest/typecheck/build；完整默认Playwright及新增320/390px/文件隔离测试（真实HTTP route fixture，不用演示回复充生产）；定向产物/工作台API，Ruff/mypy、8hooks/cached检查；实际查看桌面/预览/窄屏截图，更新真实结果、文档和进度。无需无关R或付费模型验收。逐文件暂存本任务，commit `feat(任务47): 整合聊天主界面与按需文件预览`，核验只有renv未提交后停止，交父会话独立验收与45–47复盘。

## 验收命令

```powershell
npm --prefix frontend test -- --run --maxWorkers=2
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run e2e -- --workers=1 --output=../data/task47/playwright
uv --cache-dir data/task47/uv-cache run --no-sync --offline pytest tests/integration/api/test_artifacts.py tests/integration/api/test_workbench.py tests/integration/api/test_workbench_analysis.py -q -p no:cacheprovider --basetemp data/task47/api-final
uv --cache-dir data/task47/uv-cache run --no-sync --offline ruff check .
uv --cache-dir data/task47/uv-cache run --no-sync --offline mypy src
uv --cache-dir data/task47/uv-cache run --no-sync --offline pre-commit run --all-files
git diff --cached --check
```

起点 `b5aa262`，仅renv原有未提交改动，SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。不操作用户8000服务或根runs。截图与测试缓存只写ignored data/task47；详细执行证据随工作追加。


## 实际执行记录

- 写入释放后确认 `b5aa262`，仅用户renv改动。计划先落盘，再添加缺少ChatWorkspace/FilePreview的红灯；产物契约 **1 failed, 3 passed (7.53s)**。默认沙盒API异步阻塞已中止，获准本地执行取得真实红灯；没有据环境错误声称TDD通过。
- 进一步红灯分别复现迟到history覆盖新SSE、普通讨论后恢复丢失分析文件、旧完成run错误解除新turn发送锁、迟到创建聊天导航回旧项目。修复后按对话挂载/导航代际、合并消息和独立最近分析ID保证隔离。发送锁测试改用act等待提交结束后才断言，避免只测临时submitting状态的假通过。
- 前端 **22 files / 50 passed (10.02s)**；新增测试混入Playwright的exact选项导致tsc失败，移除后typecheck/build通过。产物文本和表格转义、8MiB流式上限、旧文件迟到读取、证据撤销关闭侧栏、真实revision批准和run cancel均有断言。普通聊天的状态不再与文件预览开关绑定。
- 产物API初次使用系统MIME映射，Windows注册表把CSV变成application/vnd.ms-excel，已改为固定映射。下载ID、路径边界和hash检测不变。首次合并API另有Ollama恢复断言run=None；未修改该后端路径，单独复核通过，后续完整定向 **23 passed (106.25s)**，不据一次重跑推断唯一根因。最终命令为上列三个API文件，全部使用Mock/合成数据，无真实R/供应商调用。
- 全默认浏览器 **13 passed / 3 skipped (21.8s)**；三项旧真实Docling/Wiki/hybrid服务测试需要显式隔离服务及模型，本任务未启动或重跑这些链路。新增真实浏览器HTTP route fixtures覆盖文件开关/图像/受限报告、成对multipart导入、草稿/数据隔离、已完成分析后讨论不丢文件、审批/取消/刷新恢复、320/390px及深色。旧GEO fixture调整为可重放source事件，避免StrictMode断开首次连接就丢掉唯一假事件；旧窄屏设置改从真实项目抽屉进入。
- 旧知识库组件测试偶发在目标库初始化前选文件导致队列被重置；只将测试等待点改为管理库已选中，未修改既有上传实现。100份PDF批量上传、失败重试/停止等旧行为回归保留。截图写入ignored `data/task47/playwright-final2/`，桌面/报告/320/390px/深色均实际查看。
- `ruff check .`通过（既有pytest目录ACL warning）；mypy **112 source files**通过。没有依赖更新、迁移、单矩阵/自动metadata、通用聊天附件服务、FASTQ或新统计方法，没有读取Key、供应商调用、操作用户8000或根runs。
- 限制：草稿/待导入文件只存本页内存，刷新清空；恢复沿用现有单页消息窗口及最近分析，不新增全历史分页/跨聊天文件汇总。产物预览8MiB，CSV最多100行/50列，PDF统计产物等不支持格式可下载；文献PDF继续使用已有静态页。完整HTML报告可下载，内嵌sandbox/CSP会限制外部资源。真实provider及真实科研运行仍是独立验收，当前结果不冒称单矩阵自动分析或问答准确性。
- 45–47自查：45分块/证据选择结果与真实比较台账保留，46用户批准聊天布局，47接入真实现有API并保持审批/撤销边界。到此暂停，交父会话独立验收及整体复盘，不自动启动48。最终pre-commit与cached检查结果见下条收尾记录。

- 收尾：`pre-commit run --all-files`八项hooks全部Passed，`git diff --cached --check`退出0。只明确暂存本任务32份源码/测试/计划与文档；renv/数据/截图/模型/运行产物均未暂存。使用`feat(任务47): 整合聊天主界面与按需文件预览`本地提交，提交后以Git核验状态；renv SHA256保持原值，不push/merge、不启动48。默认`git diff --check`会报告用户renv既有空白，未改动该文件；任务暂存diff检查通过。
