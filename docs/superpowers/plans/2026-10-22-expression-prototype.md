# Task46 表达矩阵工作台设计与原型

> 依据用户最新指令，先设计并展示原型，审阅后再实施产品代码。仅执行编号任务46，保持Task45和renv工作区改动。

**目标：** 按用户最新反馈，展示类似Codex的项目/聊天侧栏、对话与底部附件输入框、按需打开的右侧文件预览；普通使用以聊天为主。

**架构：** 设计文档记录实际边界；聊天原型独立保存至本聊天获授权的visualizations目录；使用内存演示状态，无API/模型/数据下载。正式应用保持不变。

**技术栈：** 独立HTML/CSS/JavaScript交互原型，现有Python渲染器包装，Chromium/Playwright本地检查。

## Task46（唯一任务）

- [x] 阅读权威资料和Git；辨认Task45未提交文件。记录用户从“全流程”到“表达矩阵、不做FASTQ”再到“先原型”的最新约束；撤回本会话新增的FASTQ实现、测试及旧规格/计划。
- [x] 编写`docs/superpowers/specs/2026-10-22-expression-workbench-design.md`，覆盖入口、数据类型、五阶段、两种布局、审批与结果边界。
- [x] 创建`expression-workbench.html`交互原型，含“分析工作台”与“对话工作台”，采用现有绿色视觉风格。入口、分组、计划、运行、结果均有有效本地交互；数据是合成示例。
- [x] 用本地渲染器生成可检查预览；读取回源片段，确认无完整document标签/联网逻辑/缺失元素；用Chromium检查主要交互、取消、桌面和390px布局，保存本聊天visualizations目录中的验证记录和截图。
- [x] 更新current-state和本计划，记录实际验证结果与原型路径、正式实现尚未开始。明确暂存本任务两个文档和进度文件，执行`git diff --cached --check`、适用文档hooks后用含Task46的commit提交（实际提交结果以Git为准）；不暂存Task45、renv、数据或截图。
- [x] 准备好聊天内审阅用原型，在本次最终回复展示并等待用户反馈布局和流程。此为用户要求的产品审阅，不再请求原先已给出的开发方向授权。

## 验证命令

Python统一通过`uv --cache-dir data/task46/uv-cache run --offline --no-sync`使用现有环境，避开默认缓存ACL故障。运行visualize技能的`render.py FRAGMENT PREVIEW`；使用项目已安装Playwright的本地脚本检查生成预览，不访问用户浏览器登录信息、不启动/停止用户8000服务。原型不改生产代码，不运行无关统计和模型测试；检查本次文档diff与提交。

## 实际验证

以下为第一轮原型的历史证据。用户未接受两种工作台布局，当前方案以文末“审阅迭代”及更新后的规格为准，不将历史通过误写为设计获批。

本聊天持久目录：`[local path omitted]`。原型`expression-workbench.html`、本地预览`expression-workbench-preview.html`、检查脚本`verify-expression-workbench.mjs`与`expression-workbench-checks.json`。

`render.py`退出0；`node verify-expression-workbench.mjs`最终退出0，14项交互检查通过，无pageerror。390px浏览器中的内容视口358px、scrollWidth358px；已查看desktop/source/chat/mobile截图。中途演示问答提交后未显示，改为本地按钮事件并限制无关change重绘；保存状态增加revision以避免旧状态回写，不据此宣称已确定单一根因。本地预览首次覆盖忘记`--force`退出2，随后使用正确命令重建；这些中间失败不作为最终通过结果。

最终`uv --cache-dir data/task46/uv-cache run --offline --no-sync pre-commit run --all-files`八项hooks全部通过；默认沙盒首次因既有pre-commit缓存SQLite只读失败，使用授权的本地执行后通过。明确暂存三个任务文档，cached diff检查退出0；未混入Task45或renv文件。

没有真实研究数据、模型调用、API写入、统计执行或生产界面改动。原型上的规范化矩阵分支与自动metadata属于拟议产品行为，不能冒称现有正式功能。

## Task46 审阅迭代：聊天主界面

- [x] 按用户反馈撤回两种工作台布局，更新规格为单一聊天主界面；不新增编号任务或修改生产实现。
- [x] 创建同目录`chat-workspace.html`：项目及聊天侧栏、中心对话、底部附件输入框；右侧文件按需预览且默认关闭。分组、审批、模拟运行与文件链接均在对话中。
- [x] 本地渲染为`chat-workspace-preview.html`，运行`node verify-chat-workspace.mjs`：13项检查通过，errors=[]。覆盖文件预览/关闭、表格/文本、图表/报告/标签、聊天与草稿、换行/发送、示例分组/审批/停止/完成、本地文件附件、新项目/聊天、项目文件隔离、390/320px和深色模式；已查看desktop、file-preview、mobile与dark截图。
- [x] 更新计划、规格、进度；限定暂存这三个文档，运行文档hooks和cached diff检查后作任务46迭代提交，保留Task45和renv。
- [x] 用户审阅新版原型并确认后续生产界面实施方向。

本次检查脚本首次使用小写`gene`匹配实际`feature_id/GENE_A`而失败，修正检查断言后完整脚本退出0。原型未因该断言修改；该中间失败不是功能缺陷或最终通过结果。真实上传文件仅在本地读取作预览，不发送到服务端；公开数据检索和模型回复均未接入。原型保持示意标识。

本次重新运行`pre-commit run --all-files`八项hooks全部通过；三个任务文档的`git diff --check`退出0。renv原文件SHA256仍为`A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。暂存检查和提交结果以Git为准。

2026-10-22用户先表示“这个还是可以的”，随后接受左侧底部知识库管理、输入框旁选库、普通附件与加入知识库分开的方案，并明确授权“现在可以指挥其他聊天开始工作”。任务46设计审阅完成；后续任务47先实施聊天界面及既有能力整合，单矩阵预览/自动metadata另作后续编号任务，不将其作为已完成能力。共用worktree的任务45先收尾提交，任务47在释放写入权前只读准备，避免同时改动共享进度和Git索引。
