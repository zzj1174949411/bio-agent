# 本地文献工作台（任务 40）

工作台顶部“知识库”可以创建、改名、删除库，上传本地 PDF，查看解析和索引状态。返回聊天后，在“对话知识库”选择需要使用的库，再选择本轮模型并发送文献问题。GEO 发现、数据选择、分析规划和人工审批仍沿用原流程；文献不是 counts，也不能授权统计执行。

## 安装与启动

在开发 worktree 根目录运行：

```powershell
uv sync --frozen --extra rag --dev
npm --prefix frontend ci
npm --prefix frontend run build
```

解析和检索分别需要固定模型包。仅在首次准备、允许下载时显式运行：

```powershell
uv run --extra rag python -m bioagent.knowledge.prepare --models-dir data/knowledge-models
uv run --extra rag python -m bioagent.knowledge.prepare_embedding --models-dir data/embedding-models
```

已有完整模型包可直接复用，不需再次下载。例如本仓库自制样本实验的解析模型位于 `data/task38/models`：

```powershell
$env:BIOAGENT_KNOWLEDGE_MODELS_DIR = (Resolve-Path data/task38/models).Path
$env:BIOAGENT_KNOWLEDGE_EMBEDDING_MODELS_DIR = (Resolve-Path data/embedding-models).Path
uv run --extra rag --offline uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000 。只运行一个后端实例，不加多个 worker。正常准备到默认目录时无需设置上述变量。界面分别展示解析依赖和检索依赖是否就绪，缺失时可打开此安装文档；上传、启动或索引不会隐式下载模型。不安装 `rag` 仍可使用原聊天和分析功能。完整准备、错误码及资源限制见 [导入说明](knowledge-ingestion.md) 与 [检索说明](knowledge-retrieval.md)。

## 从 PDF 到回答

1. 创建库后选择本地 PDF，每批最多四份、每份最多 10 MiB。页面显示上传、排队、解析阶段、进度及错误，可取消或重试。
2. PARSED 表示解析完成；点击“建立索引”后，独立索引任务完成才是 READY。页面支持取消、重试、重建索引和删除文献。解析质量警告不等于失败，请核查 OCR、双栏顺序和跨页表格。
3. 返回聊天，勾选库并发送明确的文献问题。选择按对话保存；切换对话和刷新会恢复。当前项目/对话 ID 保存在 localStorage，凭据不进入 localStorage。选择保存期间不能发送，运行中不能改变本轮选择。
4. 文献回答显示排队、检索、命中数量、生成、引用验证与终态。答案经过完整引用校验才分段展示，这是已验证文本分段，不是原始模型 token 流，也不展示私有思维链。SSE 按同一 turn 的序号恢复并去重。
5. 引用显示文件名、章节、PDF 页码、命中原文和有界相邻上下文。可打开静态 PDF 页、下载原 PDF、查看结构化表格与图表裁剪。表格保留结构中的合并单元格、图注和脚注；超过 500 行的界面预览提示核查 PDF。

图片仅使用图注/OCR，`visual_semantics=not_performed`；显示裁剪图不代表模型理解了图像，不能由此声称读出柱高或精确数值。引用合法只证明来源归属和存活，不证明答案正确解释论文。没有证据时显示 NO_EVIDENCE，不调用回答模型。停止按钮把取消传递到知识问答任务；失败后需排查配置或重新发送。

## 固定范围、撤销与预览边界

提交时服务端冻结所选库、当时 READY 的索引 revision 和已准备模型。`knowledge_ask` 只接受 question，模型不能指定库、文件路径或资源 URL。新增无关文献不扩展已提交轮次的范围；删除、重建或原版本失效会使旧轮次返回 EVIDENCE_STALE，需重新发送，不自动换用新索引。重建一开始就撤销旧轮次；即使重建失败、旧索引恢复，已经撤销的答案也不会恢复。

工作台消息和事件只保存知识任务引用及操作状态，不复制答案文本。历史答案读取、SSE 重放和预览都重新核验 Task 39 的证据；前端每两秒及窗口聚焦时复查，失效后清空答案、引用和已打开预览。离线或无法核验时也隐藏内容。已经下载到用户机器的文件无法撤回。

新增读取路由核对工作台 owner cookie、conversation/turn/ask 归属、本轮实际引用及磁盘哈希。原文、文件名和回答由 React 转义，不插入文档 HTML，不使用模型返回的链接。PDF 页由固定子进程渲染为 PNG，不运行文档脚本：禁止网络和密钥继承，15 秒、512 MiB RSS、16 MiB 输出限制，最长边不超过 2000 像素，串行渲染；返回前再核验证据。原 PDF 仅作附件下载，资源使用 no-store/nosniff/CSP。此进程限制不替代操作系统沙箱。

对话、轮次和消息的新字段有默认值；旧 JSON 记录无需破坏性迁移。未选择库的普通聊天保留原流式行为；选库轮次先缓冲有界模型前言，确定知识动作后丢弃未经验证的前言，普通聊天则完成后发布。既有 GEO/分析审批接口未改成知识问答。

## 可复现的本地 UI 验收

该验收使用真实 Docling、multilingual-e5-small 和 Qdrant，聊天和回答均为内存 Mock，不读取真实模型 Key，不调用供应商。只上传 `scripts/literature_samples.py` 生成的三份短合成 PDF。先准备 `data/task38/models`、`data/embedding-models` 与 `data/task38/samples/`，再启动独立服务：

```powershell
uv run --extra rag --offline python scripts/serve_literature_workbench.py --data data/task40/ui
```

另一个终端在 `frontend` 目录运行：

```powershell
$env:BIOAGENT_REAL_KNOWLEDGE_UI = '1'
npm exec --offline -- playwright test e2e/knowledge.spec.ts --workers=1 --output=../data/task40/playwright-real
```

真实用例默认跳过，必须显式启动服务并设置开关；普通 `npm run e2e` 仍只需固定 API fixture。用例实际覆盖创建库、三份 PDF 解析和 READY 索引、选库问答、状态 SSE、PDF 像素、表格、实际 picture 裁剪、切换/刷新恢复、重建/删除撤销、旧资源 409 及窄屏。记录和截图写入 ignored `data/task40/ui-acceptance/`。按 Ctrl+C 关闭验收服务；这是明确的 Mock 演示入口，不能用来验收真实供应商能力。

样本很短且主要为合成英文，检索结果对措辞敏感。没有真实供应商问答质量或视觉推理验收；继承任务 38 的 OCR/布局/跨页表格限制。不能把这些测试结果推广为任意论文的解析、召回或回答正确率。
