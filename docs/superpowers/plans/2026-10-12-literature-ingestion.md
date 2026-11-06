# 本地文献导入与结构化解析实施计划

> **面向 AI 代理的工作者：** 使用 writing-plans 制定计划，executing-plans 在本聊天执行；独立兼容性实验和最终审查使用子代理。以下全部步骤属于唯一编号任务 38，不启动任务 39/40。

**目标：** 批量导入本地 PDF，通过离线 Docling 受控子进程形成可审计 PARSED revision，并提供知识库、任务和资源 API。

**架构：** SQLite 事务管理库、原文去重、任务和 revision。原文及每次解析的不可变目录位于 knowledge 根目录；只有完整验证和条件事务发布的 revision 可读。独立单 worker 监督固定 Python 子进程，持久化取消、失败和重启状态；不接入 LLM 或检索。

**技术栈：** Python 3.12、FastAPI、SQLite、Pydantic、可选固定版 Docling/RapidOCR、psutil 进程资源监督。

---

## 文件与职责

- `src/bioagent/knowledge/models.py`：版本化元素、坐标、表格、资产、解析结果、本地引用契约；不修改既有 HTTPS KnowledgeEvidence。
- `src/bioagent/knowledge/store.py`：SQLite 事务、ID 路径映射、哈希去重、revision/job 状态转换、发布完整性、删除与资源验证。
- `src/bioagent/knowledge/parser.py`、`worker.py`：默认可替换 Docling 适配器、固定离线解析入口，保存完整 Docling JSON、顺序元素、表格及图片。
- `src/bioagent/knowledge/runtime.py`、`prepare.py`、`catalog.py`、`model_catalog.json`：固定来源/长度/哈希模型清单及 readiness；显式准备才允许下载，运行时逐文件校验和禁止网络。
- `src/bioagent/knowledge/service.py`：单 worker 排队、受控 subprocess、timeout/取消/内存监督、停止与恢复。
- `src/bioagent/api/knowledge_routes.py`：知识库 CRUD、批量上传、文献/任务状态/取消重试/删除、原文/结构/资产 ID API。
- 修改 `api/app.py`、`api/dependencies.py`、`api/local_access.py`、`config.py`：装配可选能力、生命周期、Host/Origin/CSRF 和受限 multipart 大小。
- 修改 `pyproject.toml`、`uv.lock`：独立 `rag` extra；基础安装不导入 Docling。
- `tests/unit/knowledge/test_store.py`、`test_service.py`、`tests/integration/api/test_knowledge.py`：只测试关键完整性、竞争、失败和安全边界。
- `scripts/literature_samples.py`、`scripts/verify_literature_ingestion.py`、`docs/research/2026-10-12-docling-experiment.md`：自行制作代表性样本、真实安装/OCR/结构及资源实验和实际 API 验收；PDF/权重/运行结果仅写 ignored data。
- `docs/knowledge-ingestion.md`：准备、readiness、API、本机脚本 token、限制和后续索引事务契约。
- 本计划、`docs/progress/current-state.md`：实际验证和任务交接。

### 任务 38：导入、解析、受控资源与真实实验

- [x] **步骤 1：固定契约和失败测试。** 先测试同库 SHA 去重、不同库隔离；取消/删除/旧 revision 不能发布；重启中断；篡改资源不能读取。API 测试 knowledge 路径 Host/Origin/CSRF、多文件上传、不接受服务器路径、缺依赖仍可启动。

```python
def test_cancelled_revision_cannot_publish(store, imported):
    job = store.claim()
    store.cancel(job["id"])
    assert store.publish(job["id"]) is False
    assert store.document(imported["id"])["published_revision"] is None
```

运行 `uv run --offline pytest tests/unit/knowledge tests/integration/api/test_knowledge.py -q`，预期因 knowledge 模块不存在失败；保留真实红灯结果。

- [x] **步骤 2：实现事务和不可变解析契约。** 库/document/job/revision/asset 使用 UUID。状态为 QUEUED→PARSING→PARSED，失败/取消不可恢复发布；重试新 revision。单事务检查库和文献未删除、job 当前 revision 且 PARSING，然后登记完整 source/parser/settings/model/output 哈希及资产并切换 published_revision。为 Task 39 保留独立 `index_revision` 空值；Task 38 不写 INDEXING/READY。删除事务先清除 published/index revision、标删除及取消 job，再清理文件。

```sql
UPDATE documents SET published_revision = ?, index_revision = NULL
WHERE id = ? AND deleted = 0 AND current_revision = ?;
```

- [x] **步骤 3：真实安装与模型准备。** 从 Docling 官方/PyPI 与权重模型卡核对 Windows Python 3.12 可用版并固定 optional extra；独立实验环境避免干扰已有依赖。显式 prepare 命令下载所需 layout/table/OCR，记录模型 repo revision、许可证、文件 SHA256/体积。readiness 不导入重模型，缺包/文件/哈希不匹配返回稳定原因。运行子进程使用模型绝对受控路径、offline 环境、关闭 remote services/插件/图像语义增强，并在固定 worker 内拒绝网络 socket 连接。

```powershell
uv sync --extra rag --dev
uv run --extra rag python -m bioagent.knowledge.prepare --models-dir data/knowledge-models
uv run python -m bioagent.knowledge.runtime --models-dir data/knowledge-models
```

- [x] **步骤 4：实现解析器和 worker。** `parse_pdf(source: Path, output: Path, models: Path) -> ParsedDocument` 为固定适配器边界。Docling 按原始 iterate_items 顺序输出元素，章节栈、1-based 页码和 coordinate origin 原样保留；表格保存 cell row/col span/header、caption/footnotes 和完整 data；图片保存裁剪及 caption/OCR，视觉语义状态固定 `not_performed`。完整 Docling JSON 保留未归一化字段。所有表格附显式跨页/复杂表结构人工核查警告，失败不产出成功结果。worker 仅接受服务端固定参数，不执行文档内容或附件。

- [x] **步骤 5：实现受控后台监督。** 一个 supervisor 串行 claim，固定 `[sys.executable, '-m', 'bioagent.knowledge.worker', ...]`、`shell=False`、最小环境。轮询 durable cancellation、timeout 和进程树 RSS，超限杀进程树、持久化稳定错误码；子进程日志不返回 PDF 内容/任意异常。关闭时取消活动进程；启动把遗留 QUEUED/PARSING 标记 FAILED/INGESTION_INTERRUPTED，用户显式重试新 revision。Mock subprocess 只用于监督边界；真实解析必须单独验收。

- [x] **步骤 6：API 与本地边界。** 请求只接收 UUID/结构化 JSON 或 multipart PDF；每批最多 4 个、每个 10 MiB、总请求 41 MiB、magic/MIME/扩展名验证，最多 200 页，输出总量限制。既有 LocalAccessMiddleware 增加 knowledge 前缀和专用 multipart 限额，不开放 CORS。路由如下，错误码在 OpenAPI 的响应模型和使用文档固定。

| 方法与路径（`/api/v1/knowledge` 前缀） | 行为 |
| --- | --- |
| GET `/readiness` | 200，ready/code/准备命令，不依赖默认 LLM readiness |
| POST/GET `/bases` | 201 创建/200 列表 |
| GET/PATCH/DELETE `/bases/{base_id}` | 读取/改名/逻辑移除后资源清理 |
| POST/GET `/bases/{base_id}/documents` | 202 多文件导入（逐文件结果和重复标志）/列表 |
| GET/DELETE `/documents/{document_id}` | 状态/revision/质量警告；删除使证据立即失效 |
| POST `/documents/{document_id}/retry` | 202 新 revision，只有 FAILED/CANCELLED 可重试 |
| GET `/jobs/{job_id}` | durable stage/status/progress/error_code |
| POST `/jobs/{job_id}/cancel` | 200，持久化取消，发布条件阻止迟到结果 |
| GET `/documents/{document_id}/pdf` | 哈希验证后的原文，attachment/nosniff |
| GET `/documents/{document_id}/revisions/{revision_id}` | 只读当前发布 PARSED 结构 |
| GET `/documents/{document_id}/revisions/{revision_id}/assets/{asset_id}` | 验证 revision/ID/哈希后 PNG |

- [x] **步骤 7：真实质量验收。** 运行自制 digital/two-column、scan、figure/table/cross-page PDF，记录各用时、peak RSS、文字顺序、页码/坐标、表头/单位/脚注/跨页片段、图裁剪/图注/OCR。检查实际 JSON/图片，明确提取失败和质量警告；不以 Mock 替代 OCR，不访问用户文献/Key。通过新 API 导入至少一个真实样本并读出 PARSED 结果及资产。

- [x] **步骤 8：验证、文档与提交。** 定向 tests、相关 API/retrieval/配置回归、全仓 Ruff/mypy/pre-commit、`git diff --cached --check`。记录实际数量；必要时逐项修复并重跑受影响检查。更新本计划与 current-state；核对用户 renv 哈希；仅暂存上述明确文件。

```powershell
uv run --offline pytest tests/unit/knowledge tests/unit/retrieval tests/unit/domain/test_runs.py tests/integration/api/test_knowledge.py -q -p no:cacheprovider
uv run --extra rag --offline pytest tests/integration/api -q -p no:cacheprovider
uv run --offline ruff check .
uv run --offline mypy src
uv run --offline pre-commit run --all-files
git diff --cached --check
git commit -m "feat(任务38): 添加本地文献导入与结构化解析"
git status --short --branch
Get-FileHash renv/activate.R
```

## 验收和后续边界

以真实 Docling 结果和事务发布测试为完成依据。缺依赖或权重必须明确失败，不能改用伪解析。Task 39 必须对已发布 parse revision 的原文/结构/资产哈希再验证，构建单独 index revision（记录 embedding 模型版本/维度、chunk/索引哈希），在同一事务比较 current/published parse revision、删除状态和完整索引后切 READY；失败保留旧有效 revision，不能半发布。本任务只保存索引接口字段，不建立检索/API 问答或前端页面。

## 2026-10-12 执行记录

- 首次契约/API 测试因 knowledge 模块不存在而收集失败；监督测试先复现缺失 service。审查新增 Windows 原文占用和重启残留目录断言均先红后绿。Windows 删除先撤销可见性，worker 退出及启动恢复重试清理整个已删除目录；启动也清理 FAILED/CANCELLED 未发布 revision，保留原文/job。
- 独立规格审查通过；代码质量复审无 P0/P1/P2，唯一 P3 重启目录清理已修复并独立复测 **6 passed in 0.41s**。API 响应、readiness 和稳定错误码均有 OpenAPI 模型。
- 最终定向单元/API/retrieval/配置回归 **39 passed in 7.37s**；独立完整 API 目录 **87 passed in 152.10s**。全仓 Ruff 通过（扫描旧不可访问 pytest 目录有 ACL warning）；mypy **90 source files** 通过。wheel 构建成功且包含 model_catalog.json。暂存后 pre-commit 与 cached diff 检查见提交及进度记录。
- 已真实安装 rag extra，11 份固定模型文件共 **400,650,044 bytes**；prepare 官方配置下载和完整已有模型复用校验成功，runtime ready=true。未将模型/PDF/环境/运行产物加入 Git。
- 真 API 验收脚本：`uv run --extra rag --offline python scripts/verify_literature_ingestion.py --output data/task38/api-acceptance-final`。3 份自制 PDF 共 4 页全部 PARSED/index_revision=null；digital/scan/cross-page 用时 **13.031/12.532/11.922s**，峰值 RSS **1,141,379,072/1,120,493,568/1,164,365,824 bytes**。核验真实 OCR、表头单位脚注、图片裁剪/PNG 资源、删除后失效。
- 已知质量限制：双栏样本按左右行交错，跨页表格保留独立片段，图片 OCR 有空格丢失，图注/脚注关联可能缺失。均保留原始结构和人工核查警告，视觉语义状态为 not_performed。未调用真实 LLM、读取用户文献或访问真实 GEO；不启动 Task 39/40，不 push/merge/PR。
