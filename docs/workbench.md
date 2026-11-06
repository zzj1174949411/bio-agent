# 本地 Web 工作台指南

任务 21 交付的是同源本地 Web 入口。React 构建产物位于 `frontend/dist`，FastAPI 先处理 `/api/v1`，再提供前端静态资源和 SPA 路由回退。未知 API 路径始终返回 JSON 404；前端路由（例如 `/chat/demo`）回退到 `index.html`。HTML 使用 `Cache-Control: no-store`，带内容哈希的 JS/CSS 使用长期 immutable 缓存。

## 一次启动

首次安装依赖并生成前端构建：

```powershell
uv sync --frozen --dev
npm --prefix frontend ci
npm --prefix frontend run build
```

确认本机已安装 Node 22.12+、uv、Rscript 和 R/renv 后，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-workbench.ps1
```

脚本只检查并启动自己拥有的前台 uvicorn 进程，不终止已有进程。默认地址是 `http://127.0.0.1:8000`；端口被占用时会明确退出，可用 `-Port 8010` 选择其他端口。缺少 `frontend/dist/index.html` 时先运行 `npm --prefix frontend run build`。按 Ctrl+C 结束前台服务。

开发时需要 React 热更新，可在两个终端分别运行：

```powershell
uv run uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

开发前端请求需要后端允许 `http://localhost:5173` 或 `http://127.0.0.1:5173`，在本地环境设置 `BIOAGENT_LOCAL_DEV_ORIGIN` 为精确匹配的 origin。不要为开发方便打开任意来源 CORS。

## 工作流

任务47采用聊天主界面。左侧项目下选择聊天，“＋ 新建聊天”展开名称输入，项目旁的加号创建项目，省略号展开改名/归档；底部为知识库和设置入口。中间默认只有对话与输入框，右侧文件阅读区默认关闭。窄屏用顶部“项目与对话”打开抽屉；预览文件时临时占据主区，关闭回到聊天。

普通问题直接选择本轮模型后发送。需要分析数据时，点击输入框“＋ → 导入分析数据”，成对选择 counts CSV/TSV 与 metadata CSV/TSV，上传成功后显示数据集和真实校验结果，再发送分析目标。此入口不会把矩阵加入文献库；单矩阵入口与自动 metadata 现见[单矩阵指南](single-matrix.md)；普通 PDF/通用附件发送给模型仍未支持，界面不会假称已经上传或理解这些附件。

草稿、待导入文件及数据选择在本次页面会话中按聊天分别保留；切换聊天后返回可恢复，刷新会清空未发送的本地草稿/文件选择。已保存消息、模型/选库和运行状态从后端恢复，历史消息中的数据集可重新勾选。只把当前聊天的选中数据集传入当轮请求，旧聊天的消息/文件读取/上传回调不能写入新聊天；迟到的新建聊天响应也不会把用户导航回旧项目。

Enter 发送，Shift+Enter 换行，中文输入法组合输入不会发送；运行中的 turn 禁止重复发送并显示停止入口。页面显示排队、处理与工具确认等可审计状态，普通文本按 provider 分片实时显示；不保存或展示私有思维链。模型失败显示稳定错误码，终态恢复发送入口。

打开“设置 → 模型与 API”，选择“新模型”，填写名称、接口协议、API Base URL、API Key 和模型 ID，保存后返回聊天，在输入区选择模型。支持 OpenAI 兼容 Chat Completions、DeepSeek 和 Ollama；Ollama 不需要 API Key。页面保存的配置即时生效，不需要 `.env` 或重启。编辑配置与聊天选择相互独立；每个对话的模型选择由后端保存，切换对话和刷新后可恢复。配置被删除时需重新选择或进入“管理模型”。

凭据只进入后端系统凭据库，API 不回显，不写入浏览器 localStorage、数据库明文、checkpoint 或 manifest。保存中禁用重复操作；如果配置已保存但凭据写入失败，页面显示失败与实际凭据状态，需要重新填写 Key。探针发送固定非敏感请求，只验证连接和结构化输出，不能代表所有工具能力都已通过验证。

`Environment / deepseek` 和 `Environment / ollama` 是可选的只读兼容配置，来自服务启动时读取的环境变量；修改这些环境变量需要重启。正常工作台用户使用页面配置即可。旧 Streamlit/无 profile 的 API 继续使用默认环境 Planner；`/ready` 仍检查默认依赖，不会因工作台另有有效模型而伪装默认 Planner 可用。

每次发送时绑定不含密钥的配置快照。聊天、上传数据规划和 GEO 导入后的规划使用该轮同一配置；请求中编辑模型不改变原轮次。GEO 延迟回调按原 turn 快照在请求边界解析凭据，配置已删除或凭据缺失时明确失败；不会回退环境模型。已生成待审批计划保留原快照，批准和人工修改仍使用已有计划契约。

“设置”入口还包含可切换的 Skills 与 MCP 页签。Skills 只读取本地说明快照；MCP 必须先保存用户填写的绝对 stdio 命令/argv 或完整 Streamable HTTP endpoint，再显式连接。工具目录默认每次确认，旧 capability revision、过期批准和重启后的旧批准都会失效。详见 [Skills 与 MCP 扩展指南](extensions.md)。

当前内置 GEO 支持明确 GSE 编号查询及受限的关键词目录搜索。可以描述疾病、组织、物种和测序技术；Agent 返回候选后，由用户点击“检查可分析文件”，再确认 raw counts 与样本映射。搜索和选择不会直接启动统计分析，不能用模型猜测编号替代来源证据。长读长数据可作为目录发现目标，但不属于当前 bulk RNA-seq/DESeq2 分析支持范围。

左下“知识库”复用本地 PDF 管理、解析、索引/重建及文献 Wiki；输入框旁“知识库”展开本对话多选范围和既有 RAG/hybrid 模式。加号中的“将 PDF 加入知识库”明确进入管理页，不会把普通聊天文件静默长期入库。任务提交冻结模型和索引范围；重建/删除撤销历史答案、引用及已打开证据。聊天证据在按需文件区域阅读；管理页 Wiki 保留其核验预览。安装与真实本地 Mock 验收见 [文献工作台指南](knowledge-workbench.md)。未准备 RAG 依赖不影响 GEO 或既有分析。

模型只可产生受限的回答、澄清、规划、GEO 及已配置工具动作。分组/澄清、真实计划参数、运行状态和结果文件保留在对话内。审批卡展示比较方向、分组列和完整方案；勾选“我已核对本次方案”后，批准当前 revision 才会创建 attempt。拒绝和“停止运行”调用既有 run cancel API；审批前 R 调用次数保持零。澄清回答携带 request ID 和 revision，过期响应由后端拒绝。重入聊天或刷新会恢复本聊天历史 turn 对应的最近分析，随后普通讨论不会清掉其已发布文件入口。

完成后，消息中显示运行状态、QC 和逐个产物的打开/下载链接。点击“打开”或右上“文件”才出现阅读区，支持文件标签切换；关闭、切换文件或进入设置不取消分析。产物列表从 manifest 增补文件名和固定媒体类型，不暴露本机路径；下载始终使用不透明 artifact ID，服务端重验 manifest 与 SHA-256。工作台不提供删除科研证据的按钮。

产物预览最多读取8 MiB，超限或不支持的格式提供下载核查。CSV/TSV预览最多100行、50列，文本/JSON转义展示，PNG/JPEG使用临时blob URL；HTML报告在无权限sandbox iframe中显示并限制外部资源及脚本。完整报告与其他格式可下载到本机阅读。聊天证据继续使用原PDF静态页/表格/图注/OCR和服务端撤销检查。切换聊天卸载旧预览、取消读取并释放blob URL。当前消息恢复沿用既有API单页窗口，不新增全历史分页或跨聊天文件汇总。

## 固定浏览器验收

浏览器测试使用 Playwright、固定 API route fixture 和无凭据演示模型，不访问真实 provider：

```powershell
npm --prefix frontend run e2e
```

用例覆盖设置保存与返回聊天、编辑和聊天选择独立、对话模型记忆、待审批计划、可达的 Composer、每轮模型切换、Shift+Enter/Enter、刷新、窄屏入口和固定项目/对话数据。CI 使用 Node 22 和 Chromium；本地若未安装 Playwright 浏览器，可使用已安装的 Chrome，或按 Playwright 官方命令安装浏览器。

## 门禁与诊断

任务 21 的统一门禁：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run pre-commit run --all-files
```

前端单项检查为 `npm --prefix frontend ci`、`test -- --run`、`typecheck`、`build` 和 `e2e`。后端日志在启动终端中显示；API 错误使用稳定 `detail.code`，不要把请求体或凭据加入日志。`/health` 表示进程在线，`/ready` 只表示依赖可用，不代表模型请求或 DESeq2 已完成。

浏览器 fixture 和 Python e2e 使用合成数据、任务 29 的本地 MCP fixture 与 Mock 模型，不访问公网、真实账户或模型 Key。真实 R 只在合成数据验收中运行；MCP 输出始终是不可信文本，不能成为统计证据。
