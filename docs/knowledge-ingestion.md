# 本地文献导入（Task 38）

Task 38 提供知识库 CRUD、批量 PDF 导入、后台解析、取消/重试/删除和受控资源读取。解析完成是 **PARSED**。Task 39 增加真实混合检索、独立索引 READY 与问答 API，见 [检索使用说明](knowledge-retrieval.md)；Task 40 已接入 [工作台页面、聊天与证据预览](knowledge-workbench.md)。READY/INDEXING 仍支持原来的解析结构和资源读取。

## 安装与显式准备

基础 `uv sync --dev` 不安装 Docling，聊天和 DESeq2 可正常启动。知识库 API 此时仍可管理库/原文，解析任务以 `KNOWLEDGE_DEPENDENCY_MISSING` 失败；准备后显式 retry。不会因上传文献或读取 readiness 下载权重。

在 Windows/Python 3.12 安装可选依赖并准备固定版开源模型：

```powershell
uv sync --extra rag --dev
uv run --extra rag python -m bioagent.knowledge.prepare --models-dir data/knowledge-models
uv run --extra rag python -m bioagent.knowledge.runtime --models-dir data/knowledge-models
uv run --extra rag uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1
```

`prepare` 是唯一允许下载模型的入口，只读取代码中的固定来源和校验清单。部分下载没有 `bundle.json` 成功发布；模型文件 SHA256/长度不符会拒绝就绪。准备完成后可以断网运行。HTTP readiness 使用完整 SHA256 核验，与原有 `/ready`（分析模型环境）独立。

可用配置：`BIOAGENT_KNOWLEDGE_DIR`（默认 `BIOAGENT_DATA_DIR/knowledge`）、`BIOAGENT_KNOWLEDGE_MODELS_DIR`（默认 `data/knowledge-models`）、`BIOAGENT_KNOWLEDGE_PARSE_TIMEOUT_SECONDS`（600）、`BIOAGENT_KNOWLEDGE_MEMORY_BYTES`（4 GiB）。这些是服务器配置，API 不允许指定路径、可执行命令或解析器参数。只运行一个后端实例；SQLite 的事务不代替多进程 worker 所需的分布式租约。

## 本机脚本调用

所有 knowledge 路径使用现有 Host/Origin/CSRF 保护。脚本首先获取本地 token，之后带 `X-CSRF-Token`；无需开放 CORS，也不要在日志中输出 token。可从本机调用 OpenAPI `/docs` 查看完整 UUID 和响应 schema。

```python
import time
from pathlib import Path
import httpx

with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60) as client:
    bootstrap = client.get("/api/v1/workbench/bootstrap")
    bootstrap.raise_for_status()
    client.headers["X-CSRF-Token"] = bootstrap.json()["csrf_token"]
    prefix = "/api/v1/knowledge"
    ready = client.get(prefix + "/readiness").json()
    if not ready["ready"]:
        raise RuntimeError(ready["code"])
    response = client.post(prefix + "/bases", json={"name": "Local papers"})
    response.raise_for_status()
    base_id = response.json()["id"]
    # Only these explicitly chosen files are read by the caller. No directory scan.
    selected = [Path("data/task38/samples/scan_ocr.pdf")]
    response = client.post(prefix + f"/bases/{base_id}/documents", files=[
        ("files", (path.name, path.read_bytes(), "application/pdf")) for path in selected
    ])
    response.raise_for_status()
    document = response.json()["items"][0]["document"]
    document_id = document["id"]
    while document["status"] in {"QUEUED", "PARSING"}:
        time.sleep(1)
        response = client.get(prefix + f"/documents/{document_id}")
        response.raise_for_status()
        document = response.json()
    if document["status"] != "PARSED":
        raise RuntimeError(document["job"]["error_code"] or document["status"])
    revision = document["published_revision"]
    parsed = client.get(prefix + f"/documents/{document_id}/revisions/{revision}").json()
    print(parsed["page_count"], parsed["warnings"])
    # PDF: GET /documents/{id}/pdf (attachment); use #page=N in a PDF reader.
    # PNG: GET /documents/{id}/revisions/{revision}/assets/{asset_id}
```

同库原始 SHA256 相同返回已有 document 与 `duplicate=true`；不同库独立导入。每批最多 4 个 PDF，每个 10 MiB，总请求 41 MiB；扩展名、MIME、PDF magic 都检查。后台最多 200 PDF 页、600 秒、进程树 4 GiB RSS 和 100 MiB 输出。重复导入不会自动重试失败任务。

## API 与错误

所有路径以 `/api/v1/knowledge` 开头：

| 方法 | 路径 | 响应 |
| --- | --- | --- |
| GET | `/readiness` | ready/code/parser_version 或 prepare_command |
| POST/GET | `/bases` | 201 BaseRecord / 200 BasePage |
| GET/PATCH/DELETE | `/bases/{base_id}` | BaseRecord / BaseRecord / 204 |
| POST/GET | `/bases/{base_id}/documents` | 202 ImportPage / DocumentPage |
| GET/DELETE | `/documents/{document_id}` | DocumentRecord / 204 |
| POST | `/documents/{document_id}/retry` | 202 JobRecord，新 UUID revision |
| GET/POST | `/jobs/{job_id}`、`/jobs/{job_id}/cancel` | JobRecord |
| GET | `/documents/{document_id}/pdf` | 经源 SHA256 核验的 PDF 附件 |
| GET | `/documents/{document_id}/revisions/{revision_id}` | ParsedResponse（当前已发布 revision） |
| GET | `/documents/{document_id}/revisions/{revision_id}/assets/{asset_id}` | 经所属关系/哈希核验的 PNG |

边界错误为 403（Host/Origin/CSRF）、404（不存在/已删除）、409（任务状态冲突/未发布 revision）、413（大小超限）、422（格式/ID/请求不合法）、503（资源完整性失败）。解析失败仍可通过 200 job/document 状态读取稳定 `error_code`：依赖/权重缺失或无效、`PARSE_PROCESS_FAILED`、`PARSE_INCOMPLETE`、`PARSE_EMPTY`、`PARSE_TIMEOUT`、`PARSE_MEMORY_LIMIT`、`PARSE_OUTPUT_TOO_LARGE`、`INGESTION_INTERRUPTED`。API 不返回原始异常、主机路径或模型密钥。

取消立即持久化为 CANCELLED，supervisor 随后杀进程树。失败/取消只可显式重试，新 job/revision 保留旧状态。重启把遗留 QUEUED/PARSING 标为 FAILED/INGESTION_INTERRUPTED，并清理失败/取消任务的未发布目录，保留原文和任务记录。删除事务先清空 published/index revision 并取消在途任务，再清理整个文献目录；Windows 文件占用时 supervisor 退出后或下次启动重试清理。删除不会重新排队。

## 解析与可信边界

每个 revision 保存原文哈希、完整 `docling.json`、归一化 `parsed.json`、`settings.json`、`models.json` 和 UUID 命名的 PNG。SQLite publication 事务记录这些哈希和解析版本，检查 job 仍为 PARSING、文献仍为当前 revision 且未删除，并核验全部资产后一次性发布 PARSED。原文不变，重试不会覆盖上一 revision。

元素保留 Docling 阅读顺序、章节、element ID、1-based PDF 页码、bbox 与坐标原点；PDF 印刷页码不冒充页索引。表格保留完整 cell/header/span/bbox 结构、caption、footnote refs 和 Markdown 文本；原始 JSON 保留未映射字段。`page_text_cells` 保存数字/OCR 文本的 `from_ocr`、confidence 和 rect。图片保存裁剪、图注和单独运行 RapidOCR 得到的文字；`visual_semantics=not_performed`，不能据此推断图形含义或精确柱高。表格裁剪也可核查。

OCR 和版面模型会漏读、错字或错误关联 caption/footnote。所有表格均显示 `TABLE_STRUCTURE_AND_CROSS_PAGE_CONTINUITY_REQUIRE_REVIEW`；未关联的图注/脚注和不可用裁剪单独告警。跨页表格保留各页片段，不保证自动合并正确。真实样本观察和硬件/体积见 [Docling 实验记录](research/2026-10-12-docling-experiment.md)。

复现自制样本和真实 API 验收（样本生成额外需要 ReportLab，结果仅写 ignored data）：

```powershell
uv run --extra rag --with reportlab==5.0.1 python scripts/literature_samples.py
uv run --extra rag --offline python scripts/verify_literature_ingestion.py --models data/knowledge-models --output data/task38/api-acceptance
```

解析不调用云端模型/服务，不执行 PDF 中的脚本、附件或提示。固定 subprocess 使用最小环境（不继承模型 Key）、`shell=False`，Docling remote services/外部插件/视觉推断关闭，worker 禁止 Python socket 连接。RSS/磁盘限制由 supervisor 定期采样，超限终止；这是受控本地解析隔离，不是防御任意 native-code 漏洞的操作系统沙盒。PDF 作为附件返回，上传内容始终是不可信资料，不能成为 DESeq2 审批或执行指令。

## Task 39 交接

既有 HTTPS `KnowledgeEvidence` 保持原契约；本地元素使用独立 `local-reference.v1`（base/document/revision/element/page/content SHA256）。Task 39 为分块增加 chunk 身份及模型版本，引用必须属于实际命中集合。

`current_revision`、`published_revision` 与 `index_revision` 独立；Task 38 的 index_revision 始终为空。Task 39 需再次核验 parse/source/assets，构建独立索引 revision 并记录 embedding 版本/维度、chunk 和索引哈希；完整索引准备后以事务比较 published/current parse revision 和未删除状态，再切换 index_revision/READY。失败、取消和旧 revision 不允许发布；删除事务先移除检索可见性。不要仅把 PARSED 改名 READY。
