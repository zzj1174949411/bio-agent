# 本地文献 Wiki（任务 43）

Wiki 是原文的 AI 派生导航层。原文 PDF、Docling 结构和 READY chunk 仍是事实来源；引用校验只证明归属和原文匹配，不保证语义蕴含。页面明确标记 **AI 生成、未经人工审定**，候选分歧保留原研究条件，不自动裁决新旧论文。图像仍只有图注/OCR，无视觉推断。任务44已增加hybrid问答和三模式评测工具，见 `knowledge-hybrid.md`、`knowledge-evaluation.md`；真实语义验收状态见current-state。普通聊天、原文RAG、统计/GEO审批保持既有边界。

## 使用

1. 按 `docs/knowledge-ingestion.md`、`docs/knowledge-retrieval.md` 准备本地解析/embedding 权重，导入 PDF 并建立 READY 索引。上传不会自动构建 Wiki 或调用付费模型。
2. 在“知识库 → 管理文献 Wiki”选择已保存的构建模型，设置调用上限，点击“预检 Wiki 构建”。核对库名、文献数/READY 数、模型 revision、每次输入/输出限制、分段和覆盖信息。
3. 点击“确认开始 Wiki 构建”。需要发送的只是有限文本、表格片段、图注和 OCR，不发送 PDF 或图像。可停止任务；失败/取消后先重新预检，再显式重试。重试建立新的任务和预算，不自动恢复已发生的调用。
4. 从论文摘要、概念/方法、主题综合页面阅读，点击相关页面和“原文证据”核对 PDF 页。导出只返回固定文件名的 Markdown 下载；没有服务器路径输入、磁盘任意写入或 AGENTS.md 修改权限。

每库只有一个在途任务。其他库独立，仍只支持一个后端实例；沿用 RetrievalEngine 的进程 owner lease 以及本机 Host/Origin/CSRF 请求边界。Wiki 是本机共享知识库，未新增多用户权限系统。任务、页面、引用所属库与 UUID 在服务端校验，不能通过另一库的 URL 读取页面或任务。

## 输入、预算和模型限制

默认每次调用最多 24,000 UTF-8 bytes（系统提示词与完整 JSON 输入合计），最多32次调用、每篇最多8段；配置服务端范围为调用1–256、输入4,000–64,000 bytes、输出1,000–64,000 bytes、每篇1–32段。完整 chunk 不在 Wiki 中截断，超大 chunk 跳过并记录未覆盖；长论文顺序分段，达到段上限后停止选入。context 保留相邻限定条件，但模型引用必须匹配主 chunk 的原文 text，不能把相邻 element 的文字冒充主 element。输入快照与发布页面各最多8 MiB。

论文页合并各段的陈述，保留实际 chunk/页/文本字节覆盖。综合阶段按文献轮流选完整 chunk，以相同输入上限选入原文，单独记录实际覆盖；不把未发送的全文或仅发送论文摘要说成已经读过。页面和 Markdown 均携带其输入覆盖信息。覆盖率衡量输入范围，不代表摘要完整性或事实准确性。

调用次数在发送前持久化预留；错误、取消、超时或 usage 缺失均不退还。没有 SDK 自动重试、自动换模型或隐式继续任务。OpenAI-compatible/DeepSeek 请求绑定 `max_tokens`，Ollama 绑定 `num_predict`；复用所选 profile 的原 endpoint、模型和配置，不因评测路径仅支持两个 OpenAI 模型而换掉用户模型。

**这些 profile 的 Wiki 协议能力没有真实供应商实测。** 输入字节和调用数为应用端限制；输出在返回后按 UTF-8 bytes 拒收超限内容，不能保证供应商传输/隐藏推理/token/计费上界。参数不被支持时记录分类失败，不降级或切换模型。实际 usage 分别累加，缺失为 null 或部分未知，不能当零费用；不编造金额。任务42诊断复用于连接、超时、认证、计费请求、模型/路由、限流、协议、5xx及输出失败，不保存原错误正文、Key 或 traceback。

## 来源、版本、撤销

SQLite 是规范记录：`wiki_jobs` 保存模型/构建 profile、READY source hash/parse/index、提示词/schema hash、输入 hash、覆盖和调用/usage；`wiki_inputs` 冻结实际有限原文；`wiki_calls` 记录每次实际输入及 hash；`wiki_pages` 和 `wiki_dependencies` 保存完整版本与依赖，`wiki_heads` 只指向完整发布的 generation。Markdown 只是惰性下载产物，不被加载为指令或执行。

每条陈述的引用含实际发送 chunk UUID、原文 quote、内容 hash、库/document/parse/index/element/页码与 PDF source hash。模型不能填写来源路径或 URL。发布前再次核验原文/解析/索引和所有引用，在同一 SQLite 事务写入完整页面图并切换指针；事务失败回滚，新内容不替换旧有效版本。

相同源、模型、构建 profile、提示词/schema 无变化时返回 SKIPPED，零模型调用。源改变只重建对应论文页和依赖它的聚合页面；模型/profile变化则全部重建，不能混用模型快照。未受影响论文复制为新 generation 中的版本，保留原文引用。新导入只标“待更新”，已发布版本同时显示当前存活覆盖文献数。

删除、parse/current/index/source/status 变化以及显式索引重建请求，在源事务内递归标记相关历史/当前页面 STALE；综合页依赖服务器生成的完整论文导航集合。构建冻结 source epoch，过程中发生重建即使旧索引尚存活也不能发布迟到结果。失败、取消和重启不复活已撤销版本。物理文件篡改不经过 SQL trigger，因此每次页面/列表/导出/预览还要核验现有 source/chunk hash；失败后持久化递归撤销。失效列表只返回元数据，不返回旧陈述/引用/链接；页面、导出和证据 API 拒绝访问。历史 generation 不作为公开内容端点提供。

重启将未终结任务变为 FAILED / WIKI_INTERRUPTED，不自动调用模型。关闭时取消本进程任务；取消后迟到响应不能发布。取消请求可能已到达供应商，实际调用/usage仍可能未知，需按任务计数核查后再显式重试。

## API

前缀 `/api/v1/knowledge/bases/{base_id}/wiki`：

| 方法 | 后缀 | 行为 |
| --- | --- | --- |
| POST | `/preflight` | BuildRequest；不读凭据、不调用模型，返回 preflight hash |
| POST | `/build` | 同一 BuildRequest 加 preflight_sha256；重算来源/配置，不一致409 |
| GET | `/status`、`/jobs/{job_id}` | 最新任务 / 指定库所属任务 |
| POST | `/jobs/{job_id}/cancel` | 取消在途任务 |
| POST | `/jobs/{job_id}/retry` | 仅失败/取消可重试，必须携带新预检 hash |
| GET | `/pages`、`/pages/{page_id}` | 当前版本列表 / 有效页面 |
| GET | `/pages/{page_id}/export` | 固定 wiki-page.md 下载 |
| GET | `/pages/{page_id}/evidence/{chunk_id}` | 经页面归属/引用存活核验的结构与页码 |
| GET | `/pages/{page_id}/evidence/{chunk_id}/page`、`/pdf` | 原有受限静态 PNG renderer / PDF attachment |

BuildRequest 必填 model_profile_id；其余默认值见 OpenAPI。所有写操作使用既有 bootstrap 的 X-CSRF-Token。没有自动构建入口、任意路径参数、HTML渲染或模型 URL。

## 工程验收与语义边界

```powershell
uv run --extra rag --offline python scripts/verify_literature_wiki.py --output data/task43/acceptance-final
uv run --extra rag --offline python scripts/serve_literature_workbench.py --data data/task43/ui --port 4183
# 另一个终端，先 npm --prefix frontend run build
$env:BIOAGENT_REAL_WIKI_UI='1'
npm --prefix frontend run e2e -- --grep 'real local Wiki'
```

API验收复用 `data/task38/samples` 三份自制PDF和 ignored本地权重，独立目录/进程，不占用用户8000。模型仅内存Mock、凭据服务禁止读取。真实Docling/E5/Qdrant连通、来源追溯、增量、撤销和重启不等于Wiki语义质量；真实语料与付费调用预算尚未指定，REAL_BASELINE_PENDING仍保留，不宣称效果提升。
