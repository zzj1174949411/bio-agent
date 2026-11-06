# 本地文献检索与问答 API 实施计划

> **面向 AI 代理的工作者：** 使用 writing-plans 制定计划、executing-plans 在当前聊天执行。以下全部步骤属于唯一编号任务 39；不启动任务 40，不改变统计审批。

**目标：** 真实本地多语言混合检索、版本化可信引用和可取消的配置模型问答 API。

**架构：** KnowledgeStore 的 SQLite 为发布权威。独立 index revision 完整写入 Qdrant local 和哈希 manifest 后，在同一事务比较存活 parse revision 并发布 READY。一个进程持有一个可延迟打开的 Qdrant 实例，串行索引和查询；失败重建保留旧索引，取消/删除不发布半成品。问答冻结指定 profile 和本轮检索证据，模型只接收有限文本，所有引用逐项复核。

**技术栈：** Python 3.12、FastAPI、SQLite、Pydantic；rag extra 固定 qdrant-client 1.15.1、transformers 4.57.6，复用 torch 2.14.1；intfloat/multilingual-e5-small 固定 revision 614241f622f53c4eeff9890bdc4f31cfecc418b3，384 维、MIT。模型卡规定 query:/passage: 前缀、attention mean pooling、L2 normalize、512 token 限制。只有显式 prepare 下载。

## 文件与职责

- `knowledge/retrieval_models.py`：Chunk、LocalEvidence v2、SearchRequest/Response、IndexJob、AskRequest/Task/Event、模型输出 schema。
- `knowledge/chunks.py`：按元素切分原文、独立表格与图注/OCR，保留章节、位置、资产、父元素和相邻上下文；长表保留标题/表头/脚注的分段。
- `knowledge/embedding.py`、`embedding_catalog.json`、`prepare_embedding.py`：固定包/模型、哈希 readiness、显式下载、纯本地 CPU embedding 可替换协议。
- `knowledge/vector.py`：单实例 Qdrant local 适配协议、revision collection、持久化内容校验。
- `knowledge/index_catalog.py`：同 KnowledgeStore DB 的 index jobs/revisions、比较发布、恢复和取消；`store.py`/`models.py` 演进 READY/INDEXING 的解析读取契约。
- `knowledge/retrieval.py`：索引串行 worker、完整性检查、关键词 BM25 + dense RRF、库范围隔离、证据逐项校验。`retrieval/knowledge.py` 扩展本地协议并保留 HTTPS/Null。
- `knowledge/answers.py`：durable 问答任务/事件、冻结 profile、状态/文本事件、取消、错误脱敏和引用验证。
- `api/knowledge_retrieval_routes.py`、`api/app.py`、`api/dependencies.py`、`config.py`：生命周期、OpenAPI 类型和原有 Host/Origin/CSRF 边界。
- `tests/unit/knowledge/test_retrieval.py`、`tests/integration/api/test_knowledge_retrieval.py`：关键发布/取消/重建/篡改/伪造引用/注入/空证据和边界测试；问答测试共用前者 fixture，没有另拆 test_answers.py。Mock 仅用于隔离模型或生命周期。
- `scripts/verify_literature_retrieval.py`、`docs/research/2026-10-12-retrieval-experiment.md`：真实解析、真实 embedding/Qdrant、重启、隔离、删除/重建及实际命中记录。
- `docs/knowledge-retrieval.md`、`docs/knowledge-ingestion.md`、本计划和 `docs/progress/current-state.md`：使用、验证、交接；依赖变更为 `pyproject.toml`/`uv.lock`。

所有源码路径相对 `src/bioagent/`。数据/文献/权重/索引写入 ignored data，不入 Git。

### 任务 39：真实混合检索、可信引用与 API

- [x] **步骤 1：关键红灯。** 先写测试验证 PARSED→独立完整索引→READY；READY 仍可读 parsed/assets；取消、删除和 parse 变更拒绝发布；重建失败保留旧版本；旧证据与伪造引用失败。

```python
def test_ready_still_serves_parsed_and_rebuild_revokes_evidence(engine, document):
    engine.build(document['id'])
    first = engine.search('untrusted text', [document['base_id']], 3)
    assert engine.store.parsed(document['id'], document['published_revision'])
    engine.build(document['id'])
    with pytest.raises(KnowledgeError, match='EVIDENCE_STALE'):
        engine.validate(first.items[0].reference, first.items)
```

运行 `uv run --extra rag --offline pytest tests/unit/knowledge/test_retrieval.py -q -p no:cacheprovider`；预期缺失新检索模块红灯。补问答/API 红灯后才实现对应功能。

- [x] **步骤 2：固定准备与真实依赖。** 官方模型 API/模型卡核对 revision/许可/维度，各配置文件及权重固定 bytes/SHA256。固定 optional extra 并更新 lock；`uv sync --extra rag --dev`，`uv run --extra rag python -m bioagent.knowledge.prepare_embedding --models-dir data/embedding-models`。readiness 不导入重模型，运行时 local_files_only/use_safetensors/trust_remote_code=False，不运行 Hub 代码、不自动下载。
- [x] **步骤 3：分块、索引与事务。** 元素内分段、少量相邻上下文并单独标识其来源；表格片段携带标题/表头/脚注。完整 manifest 包含 parse/source/settings/models/raw/assets provenance、chunk SHA、embedding identity/dimension、Qdrant 快照 SHA。索引 job QUEUED→INDEXING→READY 或 FAILED/CANCELLED；发布使用同库事务比较 published/current parse、deleted、job 状态。重启把活动任务标 FAILED/INDEX_INTERRUPTED；无效 collection 不可检索，失效 collection 清理。单进程锁拒绝第二 owner，模型切换只能重建。
- [x] **步骤 4：混合检索与可信引用。** 显式非空库范围（最多 16）、query 1–4096、top_k 1–20；只查匹配模型的 READY revision。候选为 dense cosine 与 BM25 关键词排名，用 RRF(k=60) 融合，返回各分数/版本和原文。无候选返回 NO_EVIDENCE；不把向量相似度当语义真实性。引用 schema local-evidence.v2 包含库/doc/parse/index/chunk/element/page/hash；验证本轮实际集合、当前 revision 和磁盘内容。禁止模型自造 URL/路径。
- [x] **步骤 5：问答任务与流。** 指定 model_profile_id，提交时冻结 snapshot；检索最多 6 个有限片段，序列化数据消息与系统规则分开。模型输出 `answer` 和引用服务端 chunk UUID 列表，后端解析并校验后才发 answer.delta（分段的已验证答案）。状态/检索事件实时 SSE；空证据不调用模型，返回 NO_EVIDENCE。问答超时/取消/重启留 durable 失败状态，禁止半答案标成功。图片固定 not_performed，无工具调用/视觉/整 PDF 上传。
- [x] **步骤 6：API 和文档。** schema 如下，全部继承现有本机访问边界，错误 detail.code，OpenAPI 可直接取用。

| 方法及 `/api/v1/knowledge` 路径 | 请求/响应 |
| --- | --- |
| GET `/retrieval/readiness` | ready/code/model_id/revision/dimension/prepare_command |
| POST `/documents/{id}/index` | 无用户路径/模型名，202 IndexJob；重复活动请求复用 job，新请求显式重建 |
| GET `/documents/{id}/index` | 当前索引及最新 job 状态 |
| GET `/index-jobs/{id}` | IndexJob |
| POST `/index-jobs/{id}/cancel` | IndexJob |
| POST `/search` | SearchRequest(query,knowledge_base_ids,top_k) → SearchResponse(code,items,retrieval)；不调用 LLM |
| POST `/ask` | AskRequest(question,knowledge_base_ids,model_profile_id) → 202 AskTask(id,status,snapshot,status_url,events_url) |
| GET `/asks/{id}` | AskTask(答案/引用/错误/版本) |
| GET `/asks/{id}/events?after=0` | SSE，序号可恢复；状态/检索/已验证答案/失败/取消，终态结束 |
| POST `/asks/{id}/cancel` | AskTask |
| POST `/evidence/validate` | local-evidence.v2 → 当前受控 Chunk（这里只校验存活/完整性；问答还要求属本轮集合） |

关键错误：RAG_DEPENDENCY_MISSING、RAG_MODELS_MISSING/INVALID、RAG_NOT_READY、INDEX_CONFLICT、INDEX_NOT_FOUND、INDEX_INTEGRITY_FAILED、INDEX_MODEL_MISMATCH、EVIDENCE_INVALID/STALE、ASK_NOT_FOUND、ASK_QUEUE_FULL；模型错误复用 ModelAdapter 稳定错误码。文档给出 bootstrap token、curl.exe 和 httpx Python 完整调用流程，无 CORS/公网变化。

- [x] **步骤 7：真实实验。** 重新 API 导入自制 digital/scan/cross-page PDF，实际 Docling→E5→Qdrant；中文 query 命中英文正文/表格/图注，记录原文/页码/分数。关闭重开持久化检索一致、另库为空、重建旧引用失败、删除即时失效，篡改 index/source/asset 不可信。问答只用 Mock 和内存 SecretStore；不读取真实 API Key。记录小样本/双栏/跨页表格/OCR 限制，不声称全文理解。
- [x] **步骤 8：验证、进度与唯一提交。** 必需命令如下。只暂存本计划文件清单涉及的实际变更，不使用 git add .；保持 renv SHA A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A；不动根 runs。

```powershell
uv run --extra rag --offline pytest tests/unit/knowledge tests/unit/retrieval tests/unit/models tests/integration/api/test_knowledge.py tests/integration/api/test_knowledge_retrieval.py -q -p no:cacheprovider
uv run --extra rag --offline pytest tests/integration/api -q -p no:cacheprovider
uv run --extra rag --offline python scripts/verify_literature_retrieval.py --output data/task39/acceptance
uv run --offline ruff check .
uv run --offline mypy src
uv run --offline pre-commit run --all-files
git diff --cached --check
git commit -m "feat(任务39): 添加本地混合检索与可信问答API"
git status --short --branch
Get-FileHash renv/activate.R
```

## 执行记录

开始时 HEAD 8043632，唯一未提交改动为用户 renv/activate.R，哈希与交接一致。原始设计/计划、最新进度、任务 38 资料及现有代码均已阅读；实际解释器 3.12，已装 transformers 4.57.6 / torch 2.14.1。默认沙盒不允许查询 uv interpreter 或网络，已按正常审批接口核验官方模型元数据，未绕过沙盒。

完成记录：

- 红灯顺序：缺失 retrieval 模块 → 缺失 ask/API → 真实非平凡向量重启摘要不一致 → 表格全部列头/上下文边界 → 模型伪造 file URL → 重启残留 collection。每项均先观察失败后修复，最终均进入回归。问答测试与检索测试共用 fixture，合并于 test_retrieval.py。
- 实际准备五个模型文件并核对全部 bytes/SHA256；固定 E5 384 维。真实 Qdrant Cosine 的持久化与内存归一化差异经实验复现，改用已 L2 归一化 float32 向量的 DOT（对应 cosine 分数），算法/模型维度变更要求重建。
- 真实 API 验收最终使用 `--output data/task39/acceptance-final3`，exit 0；Docling/E5/Qdrant 为实际依赖，中文正文/表格目标 rank 1，picture rank 4、caption rank 1，重启所有命中完全一致。问答仅 Mock；删除/重建即时使旧引用和已完成答案失效。初始失败、措辞敏感、小语料和 RSS 采样限制完整保留于实验记录。按实际 API top_k=6 验收图片，不声称稳定 top 3。
- 最终定向 pytest：**80 passed in 18.73 s**；完整 API：**89 passed in 173.22 s**。Ruff exit 0；mypy **100 source files** 无问题；pre-commit **8/8 hooks Passed**；`git diff --cached --check` 无输出并通过。Ruff/Git 的既有 `.pytest-reg-final30/` ACL 扫描警告不影响退出码；未修用户缓存或用户 renv。
- 明确暂存 27 个任务文件，无 .env、PDF、权重、索引或运行数据。用户 renv/activate.R SHA256 仍为 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。当前状态与下一步已更新；本任务唯一提交使用上述任务39 message，提交身份以 Git 为准。保留分支/worktree，不 push/merge/PR，不进入任务40。
