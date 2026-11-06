# 本地文献检索与问答（任务 39）

知识库现在可以从 PARSED 构建独立索引并发布 READY。任务 40 已接入 [工作台知识库管理、聊天工具和可信证据预览](knowledge-workbench.md)。检索与文献问答不会创建 counts、执行代码、批准或运行 DESeq2。

## 安装、准备与进程

```powershell
uv sync --extra rag --dev
uv run --extra rag python -m bioagent.knowledge.prepare_embedding --models-dir data/embedding-models
```

解析模型另按 [导入说明](knowledge-ingestion.md) 显式准备。默认 embedding 目录为 `data/embedding-models`，可通过 `BIOAGENT_KNOWLEDGE_EMBEDDING_MODELS_DIR` 配置。启动、检索、索引和问答均不会下载模型；GET `/api/v1/knowledge/retrieval/readiness` 每次核对固定包版本和全部模型 SHA256。基础安装不导入 Torch、Transformers、Docling 或 Qdrant，原有聊天和统计照常使用。

固定 E5 revision、许可、逐文件 SHA256/bytes 位于 `src/bioagent/knowledge/embedding_catalog.json`。下载总量 487,725,595 bytes（465.13 MiB）；CPU、384 维，query:/passage: 前缀、attention mean pooling、L2 normalize。长文本按 480 token 窗口计算并平均归一化，不静默截断。Qdrant 使用预先归一化向量的 DOT（与 cosine 等价），固定 float32，避免 Cosine 内部归一化导致内存与持久化值不同。

只运行一个后端进程，沿用现有启动方式并绑定 `127.0.0.1`，不要启用多个 Uvicorn worker。进程锁在任何恢复动作前获取，Qdrant 在第一次使用时延迟打开并由同一进程持有。重复活动索引请求返回原 job；终态后再次 POST index 是显式重建。构建完整新 revision 后事务切换，失败/取消保留旧 READY 版本。首次失败恢复为 PARSED，错误在 index job 中。重启把 QUEUED/INDEXING 标为 FAILED/INDEX_INTERRUPTED，不自动继续；问答中断为 FAILED/ASK_INTERRUPTED。

删除事务立即撤销可检索/可引用状态，后台清理失效索引。新进程仅加载已发布索引；忽略不完整 collection。Qdrant 1.15.1 的本地 SQLite 使用 pickle，因此在交给 Qdrant 反序列化之前检查每个文件的已登记哈希，并根据可信 manifest 生成 collection 元数据。应用只保存自身生成的向量对象，不接受用户上传索引。更换 embedding 权重、算法或维度必须重建；不同身份不能混查。

## API 与契约

OpenAPI：GET `/openapi.json`；交互文档：`/docs`。以下路径前缀均为 `/api/v1/knowledge`。请求拒绝额外字段和服务器文件路径，所有 ID 由服务端生成。继承已有 Host、Origin、CSRF 和请求大小边界，不开放 CORS。

| 方法与路径 | 内容 |
| --- | --- |
| GET `/retrieval/readiness` | ready/code、固定模型版本/维度、准备命令 |
| POST `/documents/{document_id}/index` | 202 IndexJob；无需 body |
| GET `/documents/{document_id}/index` | 当前 index_revision 和 latest_job |
| GET `/index-jobs/{job_id}` | 状态、progress、稳定 error_code |
| POST `/index-jobs/{job_id}/cancel` | 持久化取消，迟到结果不能发布 |
| POST `/search` | `{query, knowledge_base_ids, top_k=6}` → SearchResponse |
| POST `/ask` | `{question, knowledge_base_ids, model_profile_id}` → 202 AskTask |
| GET `/asks/{ask_id}` | 状态、冻结配置、证据、答案、引用及错误 |
| GET `/asks/{ask_id}/events?after=0` | SSE，单调 sequence；after 可断线续读 |
| POST `/asks/{ask_id}/cancel` | 取消排队/生成；不发布答案 |
| POST `/evidence/validate` | LocalEvidence → 当前有效 Chunk；旧引用 409 |

`knowledge_base_ids` 必须非空，最多 16 个；query/question 去空格后 1–4096 字符，top_k 为 1–20 整数。只查询范围内 READY 且模型身份一致的文献；无索引/候选返回 NO_EVIDENCE。BM25（英文单词/汉字双字）与多语言 dense 排名通过 RRF(k=60) 融合。返回 dense_score、keyword_score、融合 score 以及明确的模型、索引 revision 和库范围。分数不是概率或科学真实性证明；没有通用的语义相关性阈值，READY 非空语料通常会产生邻近命中，用户仍应核对原文。

每个命中包括原文 chunk、章节、位置、类型、上下文及对应元素 ID、资产 ID；`pdf_url`/`asset_url` 是服务端固定的相对 API 路径，不是主机文件路径。表格每个分段保留标题、全部已识别列头/单位、脚注；解析器未识别的关联不能由检索修复。正文默认 1200 字符窗口，100 字符重叠；相邻上下文最多两项、每项 100 字符，单独标注来源。每文献最多 5000 chunks；过长章节（合计 >2000 字符）或表格标题/表头/脚注（合计 >2800 字符）明确索引失败 INDEX_CONTEXT_TOO_LARGE，不静默丢弃它们。原文和结构 API 在 READY/INDEXING 状态继续可读。

引用 `local-evidence.v2` 的字段为 `base_id/document_id/parse_revision/index_revision/chunk_id/element_id/page/content_sha256`。服务器校验当前存活版本、原文/解析/资产/manifest/向量哈希；问答还要求每项引用属于本轮实际检索集合。公开 evidence/validate 只验证当前来源，不能证明某一任意问答曾经检索过它。重建和删除立即使旧证据失效，已存问答下次读取/重放也撤销旧答案。归属验证不能证明模型正确理解了文献。

问答提交时冻结用户选择的 model profile snapshot；读取已保存凭据，通过 ModelAdapter 调用，不静默改用默认模型。问答最多串行 1 个、排队 16 个，120 秒超时。模型仅收到最多 6 个有限文本片段及 question，文献数据和系统规则分开，不绑定工具、不上传 PDF 或图片。图片只依据图注/OCR，响应 `visual_semantics=not_performed`，不能推断精确图表读数。

SSE 的 `data` 是 AskEvent JSON：`sequence/kind/data`，kind 为 status、retrieval.completed、answer.delta、completed、failed、cancelled。状态实时发送；答案先完整接收、解析并验证引用，再以 256 字符分段发布 answer.delta，**不是模型原始 token 的实时透传**。这样伪造引用、超时或取消不会向客户端泄漏未校验半答案。失败只有稳定代码，不输出 provider 原始异常。

| HTTP | 常见 detail.code |
| --- | --- |
| 403 | LOCAL_HOST_REJECTED / LOCAL_ORIGIN_REJECTED / CSRF_TOKEN_REQUIRED |
| 404 | BASE_NOT_FOUND / DOCUMENT_NOT_FOUND / INDEX_NOT_FOUND / ASK_NOT_FOUND |
| 409 | REVISION_NOT_PUBLISHED / INDEX_CONFLICT / INDEX_MODEL_MISMATCH / INDEX_OWNER_CONFLICT / EVIDENCE_STALE |
| 422 | REQUEST_INVALID / EVIDENCE_INVALID |
| 429 | ASK_QUEUE_FULL |
| 503 | RAG_DEPENDENCY_MISSING / RAG_DEPENDENCY_VERSION / RAG_MODELS_MISSING / RAG_MODELS_INVALID / INDEX_INTEGRITY_FAILED |

后台 job 可能返回 INDEX_INTERRUPTED、INDEX_BUILD_FAILED、INDEX_EMPTY、INDEX_CONTEXT_TOO_LARGE、INDEX_TOO_LARGE；问答可能返回 ASK_INTERRUPTED、MODEL_TIMEOUT、MODEL_AUTH_FAILED、MODEL_NOT_CONFIGURED、MODEL_OUTPUT_INVALID、EVIDENCE_INVALID、EVIDENCE_STALE。无证据是 NO_EVIDENCE 终态，且不调用模型。

## 本机 curl.exe

后端已启动且文献已 PARSED。PowerShell 先取 token，再调用；`$documentId/$baseId/$profileId` 替换为已有 API 返回值。profile 必须是任务 37 设置页保存或 profile API 创建的记录。

```powershell
$api = 'http://127.0.0.1:8000'
$token = (curl.exe -s "$api/api/v1/workbench/bootstrap" | ConvertFrom-Json).csrf_token
$baseId = '替换为知识库UUID'
$documentId = '替换为文献UUID'
$profileId = '替换为模型配置UUID'
curl.exe -s "$api/api/v1/knowledge/retrieval/readiness"
curl.exe -s -X POST -H "X-CSRF-Token: $token" "$api/api/v1/knowledge/documents/$documentId/index"
curl.exe -s "$api/api/v1/knowledge/documents/$documentId/index"

# 等 latest_job.status=READY 后：使用 UTF-8 文件避免 Windows shell 引号处理差异。
$search = @{query='表格中的质量单位是什么'; knowledge_base_ids=@($baseId); top_k=6} | ConvertTo-Json
[IO.File]::WriteAllText("$env:TEMP/bioagent-search.json", $search, [Text.UTF8Encoding]::new($false))
curl.exe -s -X POST -H "X-CSRF-Token: $token" -H 'Content-Type: application/json' --data-binary "@$env:TEMP/bioagent-search.json" "$api/api/v1/knowledge/search"
$ask = @{question='图注说明了什么'; knowledge_base_ids=@($baseId); model_profile_id=$profileId} | ConvertTo-Json
[IO.File]::WriteAllText("$env:TEMP/bioagent-ask.json", $ask, [Text.UTF8Encoding]::new($false))
$task = curl.exe -s -X POST -H "X-CSRF-Token: $token" -H 'Content-Type: application/json' --data-binary "@$env:TEMP/bioagent-ask.json" "$api/api/v1/knowledge/ask" | ConvertFrom-Json
curl.exe -N "$api$($task.events_url)"
curl.exe -s "$api$($task.status_url)"
```

## Python 使用

```python
import time
import httpx

base_id = '替换为知识库UUID'
document_id = '替换为文献UUID'
profile_id = '替换为模型配置UUID'
with httpx.Client(base_url='http://127.0.0.1:8000', timeout=180) as client:
    response = client.get('/api/v1/workbench/bootstrap')
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    response = client.post(f'/api/v1/knowledge/documents/{document_id}/index')
    response.raise_for_status()
    job_id = response.json()['id']
    while True:
        response = client.get(f'/api/v1/knowledge/index-jobs/{job_id}')
        response.raise_for_status()
        job = response.json()
        if job['status'] not in {'QUEUED', 'INDEXING'}:
            break
        time.sleep(0.2)
    if job['status'] != 'READY':
        raise RuntimeError(job['error_code'] or job['status'])
    response = client.post('/api/v1/knowledge/search', json={
        'query': '图注说明了什么', 'knowledge_base_ids': [base_id], 'top_k': 6})
    response.raise_for_status()
    print(response.json())
    response = client.post('/api/v1/knowledge/ask', json={
        'question': '图注说明了什么', 'knowledge_base_ids': [base_id],
        'model_profile_id': profile_id})
    response.raise_for_status()
    task = response.json()
    with client.stream('GET', task['events_url']) as stream:
        stream.raise_for_status()
        for line in stream.iter_lines():
            if line.startswith('data: '):
                print(line[6:])
    response = client.get(task['status_url'])
    response.raise_for_status()
    print(response.json())
```

真实本地验收命令：`uv run --extra rag --offline python scripts/verify_literature_retrieval.py --output data/task39/acceptance-final3`。实际结果、最初失败及质量限制见 [实验记录](research/2026-10-12-retrieval-experiment.md)。问答模型为 Mock，未验证付费供应商的真实输出质量。

模型答案只允许文本和本轮 chunk UUID 引用；HTTP/file URL、Windows/UNC 路径、Markdown 链接和 HTML 超链接会被拒绝。PDF 与资产链接由服务端从已验证引用生成，不采信模型生成的来源地址。
