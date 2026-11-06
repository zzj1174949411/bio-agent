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

进入工作台后先创建项目和对话，选择或上传 counts/metadata 数据集，再在 Composer 中选择本轮模型并发送目标。Enter 发送，Shift+Enter 换行，中文输入法组合输入不会发送；运行中的 turn 会禁用重复发送并显示停止入口。模型设置里的凭据只发送到后端，保存后清空输入，不写入 localStorage。

模型输出只能产生回答、澄清或分析计划。计划进入原有人工审批卡后，批准当前 revision 才会创建统计 attempt；审批前 R 调用次数保持为零。澄清回答携带 request ID 和 revision，过期响应由后端拒绝。

完成运行后，右侧面板显示运行状态、QC、图表、sandbox 报告 iframe 和逐个 artifact 下载。下载链接来自不透明 artifact ID，服务端重新核对 manifest 与 SHA-256；工作台不提供删除科研证据的按钮。

## 固定浏览器验收

浏览器测试使用 Playwright、固定 API route fixture 和无凭据演示模型，不访问真实 provider：

```powershell
npm --prefix frontend run e2e
```

用例覆盖可达的 Composer、每轮模型切换、Shift+Enter/Enter、刷新、窄屏入口和固定项目/对话数据。CI 使用 Node 22 和 Chromium；本地若未安装 Playwright 浏览器，可使用已安装的 Chrome，或按 Playwright 官方命令安装浏览器。

## 门禁与诊断

任务 21 的统一门禁：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run pre-commit run --all-files
```

前端单项检查为 `npm --prefix frontend ci`、`test -- --run`、`typecheck`、`build` 和 `e2e`。后端日志在启动终端中显示；API 错误使用稳定 `detail.code`，不要把请求体或凭据加入日志。`/health` 表示进程在线，`/ready` 只表示依赖可用，不代表模型请求或 DESeq2 已完成。

任务 21 的浏览器 fixture 和 Python e2e 使用合成 counts/metadata 与 Mock 模型；真实 R 只在合成数据验收中运行，真实模型 API、GEO、Skills 和 MCP 不属于本阶段。
