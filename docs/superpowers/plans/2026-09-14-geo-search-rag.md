# GEO 关键词搜索、下载衔接与 RAG 扩展实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 `superpowers-zh:executing-plans` 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度；每个编号任务完成、验证和提交后再进入下一任务，Task 36 后执行 34–36 整体复盘。

**目标：** 让用户按疾病、组织、物种和测序类型搜索 GEO GSE 候选，明确选择后复用现有 counts 下载与 DESeq2 流程，并为后续 RAG 知识库保留独立接口。

**架构：** `DatasetCatalogProvider` 隔离数据目录搜索，第一版由 `NcbiGeoCatalogProvider` 使用 NCBI ESearch → ESummary；`GeoSearchService` 持久化异步状态并把用户选择交给现有 `GeoImportService`。知识检索使用单独的 `KnowledgeRetriever`，不能创建 Dataset 或改变分析运行。

**技术栈：** Python 3.12、Pydantic、FastAPI、httpx、现有 GEO 安全 transport/SQLite 工作台、React/TypeScript、REST/SSE、Vitest、Playwright、pytest。

---

## 0. 依据、文件结构与共同约束

规格：[GEO 搜索与 RAG 设计](../specs/2026-09-14-geo-search-rag-design.md)。NCBI 调用方式以 [Programmatic access to GEO](https://www.ncbi.nlm.nih.gov/geo/info/geo_paccess.html) 和 [E-utilities 参数文档](https://www.ncbi.nlm.nih.gov/books/NBK25499/) 为准：在 `db=gds` 使用 ESearch，限定 `gse[ETYP]`，再用 ESummary 取得 accession 和元数据。

| 文件 | 职责 / 任务 |
| --- | --- |
| `src/bioagent/retrieval/contracts.py` | 数据目录查询、候选、证据和 provider 协议 / 34 |
| `src/bioagent/geo/search.py` | NCBI ESearch/ESummary、分页和规范化 / 34 |
| `src/bioagent/geo/search_repository.py` | 搜索状态原子持久化与 revision / 34 |
| `src/bioagent/geo/search_service.py` | 后台队列、事件、选择与现有 source discovery 衔接 / 34 |
| `src/bioagent/workbench/{actions,turns,models,store}.py` | `dataset_search` 动作和会话恢复 / 35 |
| `frontend/src/features/geo/GeoSearchResults.tsx` | 搜索进度、结果、分页和选择 / 35 |
| `src/bioagent/retrieval/knowledge.py` | RAG 查询/证据接口和未配置实现 / 36 |
| `tests/e2e/test_geo_search_workflow.py`、`frontend/e2e/geo-search.spec.ts` | 搜索到既有 GEO/审批链 / 36 |

所有公网行为使用 MockTransport 或本地 route fixture；测试不读取模型 Key，不执行真实 GEO 下载。保持 `renv/activate.R` 的用户改动，不恢复、格式化、暂存或提交。每个任务只暂存本节明确列出的文件、此计划与 `docs/progress/current-state.md`。

每个任务至少运行其定向测试、Ruff、mypy、前端 typecheck（涉及前端时）和暂存差异检查：

```powershell
uv run --offline ruff check .
uv run --offline mypy src
git diff --cached --check
git diff --cached --name-only
```

Task 36 才运行一次完整 `scripts/check.ps1`，避免为简单界面逻辑重复扩大测试。

## Task 34：GEO 搜索 provider、状态服务与 API

**创建：**

- `src/bioagent/retrieval/__init__.py`
- `src/bioagent/retrieval/contracts.py`
- `src/bioagent/geo/search.py`
- `src/bioagent/geo/search_repository.py`
- `src/bioagent/geo/search_service.py`
- `tests/unit/geo/test_geo_search.py`
- `tests/unit/geo/test_geo_search_service.py`
- `tests/fixtures/geo/search_esearch.json`
- `tests/fixtures/geo/search_esummary.json`

**修改：**

- `src/bioagent/geo/transport.py`
- `src/bioagent/api/geo_routes.py`
- `src/bioagent/api/dependencies.py`
- `tests/integration/api/test_geo.py`
- `docs/superpowers/plans/2026-09-14-geo-search-rag.md`
- `docs/progress/current-state.md`

- [x] **步骤 1：编写 provider 红灯测试**

在 `tests/unit/geo/test_geo_search.py` 使用 `httpx.MockTransport` 记录请求并返回两个 fixture。断言只查询 `db=gds`、查询项包含 `gse[ETYP]`、业务字段由 httpx 参数编码、ESummary 只保留合法 GSE、重复 accession 去重且顺序稳定。

```python
def test_geo_search_uses_esearch_then_esummary(mock_geo_search_client):
    page = mock_geo_search_client.search(
        DatasetSearchQuery(
            text="Alzheimer disease",
            organism="Homo sapiens",
            tissue="brain",
            technology="RNA-seq",
        )
    )
    assert [hit.record_id for hit in page.items] == ["GSE111", "GSE222"]
    assert all(hit.provider == "geo" for hit in page.items)
    assert mock_geo_search_client.requested_paths == [
        "/entrez/eutils/esearch.fcgi",
        "/entrez/eutils/esummary.fcgi",
    ]
```

- [x] **步骤 2：运行红灯并记录预期失败**

运行：

```powershell
uv run --offline pytest tests/unit/geo/test_geo_search.py -v -p no:cacheprovider
```

预期：收集阶段因 `bioagent.retrieval` 或 `bioagent.geo.search` 尚不存在而失败。

- [x] **步骤 3：实现严格检索契约**

在 `retrieval/contracts.py` 定义冻结且 `extra="forbid"` 的模型与协议。文本字段拒绝控制字符；query hash 使用排序 JSON；页大小默认 10、最大 20；候选 URI 必须为后端产生的 NCBI HTTPS URL。

```python
class DatasetSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=2, max_length=256)
    provider: Literal["geo"] = "geo"
    organism: str | None = Field(default=None, max_length=128)
    tissue: str | None = Field(default=None, max_length=128)
    technology: str | None = Field(default=None, max_length=128)
    page_token: str | None = Field(default=None, max_length=128)
    page_size: int = Field(default=10, ge=1, le=20, strict=True)


class DatasetCatalogProvider(Protocol):
    def search(self, query: DatasetSearchQuery) -> DatasetSearchPage: ...
```

同时定义 `EvidenceRef`、`AnalysisReadiness`、`DatasetSearchHit` 和 `DatasetSearchPage`。`EvidenceRef` 包含 provider、source ID、source URI、retrieved_at 和 64 位小写 SHA-256。

- [x] **步骤 4：实现 NCBI GEO provider**

`NcbiGeoCatalogProvider.search()` 执行两次受限 GET：ESearch 参数为 `db=gds`、`term=<规范化业务词> AND gse[ETYP]`、`retmode=json`、`retstart` 和 `retmax`；ESummary 参数为 `db=gds`、`id=<UID 列表>`、`retmode=json`、`version=2.0`。解析前检查各响应不超过 2 MiB，总结果最多 100 条。

```python
def build_term(query: DatasetSearchQuery) -> str:
    terms = [query.text, "gse[ETYP]"]
    if query.organism:
        terms.append(f'"{query.organism}"[ORGN]')
    if query.tissue:
        terms.append(query.tissue)
    if query.technology:
        terms.append(query.technology)
    return " AND ".join(terms)
```

对引号、方括号和反斜杠做确定性转义，不能允许业务字段注入额外 Entrez qualifier。游标绑定 query hash 和 offset；服务只接受上一次响应返回的精确 token。映射 404、429、网络错误、超时、畸形 JSON、超限和空结果为设计规定的稳定错误码。

把 `eutils.ncbi.nlm.nih.gov` 加入 GEO transport 允许列表，但继续拒绝 HTTP、非 443、私网解析、重定向和代理环境。

- [x] **步骤 5：补齐 provider 有意义的边界测试并转绿**

补充测试：空 UID、混入 GPL/GDS、重复 GSE、缺少可选字段、非法 accession、畸形 JSON、2 MiB 超限、429、超时、陈旧游标和最大 100 条。不要逐字段复制实现测试。

运行：

```powershell
uv run --offline pytest tests/unit/geo/test_geo_search.py tests/integration/test_geo_transport.py -q -p no:cacheprovider
```

预期：全部通过；没有公网请求。

- [x] **步骤 6：编写搜索状态与 API 红灯测试**

`tests/unit/geo/test_geo_search_service.py` 覆盖创建搜索、持久化完成态、重启把 `QUEUED/SEARCHING` 置为 `FAILED/GEO_SEARCH_PROCESS_RESTARTED`、精确 revision 选择候选，以及选择只调用 source discovery、不调用下载器。

```python
def test_selection_starts_source_discovery_without_downloading(search_service):
    ready = wait_for_search(search_service.create(query=QUERY))
    selected = search_service.select(
        ready["id"], accession="GSE111", revision=ready["revision"]
    )
    assert selected["status"] == "SELECTED"
    assert search_service.source_factory.calls == ["GSE111"]
    assert search_service.downloader_calls == []
```

`tests/integration/api/test_geo.py` 增加 CSRF、202/GET、分页 token、候选不属于搜索时 404、旧 revision 409、取消和稳定错误码断言。

- [x] **步骤 7：运行服务/API 红灯**

```powershell
uv run --offline pytest tests/unit/geo/test_geo_search_service.py tests/integration/api/test_geo.py -q -p no:cacheprovider
```

预期：因搜索 repository/service/API 尚不存在而失败。

- [x] **步骤 8：实现搜索仓库、后台服务和 API**

`GeoSearchRepository` 在 `data/searches/<UUID>/search.json` 原子保存状态，并在读取时校验 ID、query hash、revision 和结果 schema。`GeoSearchService` 使用独立的最多 2 worker、16 排队任务；取消采用 cooperative event，事件只发布 ID、状态、revision 和 result_count。

```python
class GeoSearchStatus(StrEnum):
    QUEUED = "QUEUED"
    SEARCHING = "SEARCHING"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    SELECTED = "SELECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
```

服务方法固定为 `create(query, conversation_id, turn_id)`、`get(search_id)`、`next_page(search_id, page_token, revision)`、`select(search_id, accession, revision)`、`cancel(search_id)` 和 `close()`。`select()` 校验 accession 属于当前结果快照后调用注入的 source factory，并保存 `source_id`；调用失败不写 SELECTED。

在 `geo_routes.py` 增加规格中的五个端点和严格 Pydantic request models。`DependencyContainer` 注入并关闭 `geo_search_service`，将 source factory 绑定到现有 `geo_service.create_source()`；测试 override 可注入假 provider/service。

- [x] **步骤 9：验证、更新状态并提交 Task 34**

```powershell
uv run --offline pytest tests/unit/geo/test_geo_search.py tests/unit/geo/test_geo_search_service.py tests/integration/api/test_geo.py tests/integration/test_geo_transport.py -q -p no:cacheprovider
uv run --offline ruff check .
uv run --offline mypy src
git add src/bioagent/retrieval/__init__.py src/bioagent/retrieval/contracts.py src/bioagent/geo/search.py src/bioagent/geo/search_repository.py src/bioagent/geo/search_service.py src/bioagent/geo/transport.py src/bioagent/api/geo_routes.py src/bioagent/api/dependencies.py tests/unit/geo/test_geo_search.py tests/unit/geo/test_geo_search_service.py tests/fixtures/geo/search_esearch.json tests/fixtures/geo/search_esummary.json tests/integration/api/test_geo.py docs/superpowers/plans/2026-09-14-geo-search-rag.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务34): 增加GEO关键词搜索服务"
```

## Task 35：Agent 搜索动作与搜索结果界面

**创建：**

- `frontend/src/features/geo/GeoSearchResults.tsx`
- `frontend/src/features/geo/GeoSearchResults.test.tsx`

**修改：**

- `src/bioagent/workbench/actions.py`
- `src/bioagent/workbench/models.py`
- `src/bioagent/workbench/store.py`
- `src/bioagent/workbench/tool_loop.py`
- `src/bioagent/workbench/turns.py`
- `src/bioagent/api/dependencies.py`
- `frontend/src/api/types.ts`
- `frontend/src/api/client.ts`
- `frontend/src/features/chat/ChatTimeline.tsx`
- `frontend/src/App.tsx`
- `tests/unit/workbench/test_tool_loop.py`
- `tests/integration/api/test_workbench_tools.py`
- `docs/superpowers/plans/2026-09-14-geo-search-rag.md`
- `docs/progress/current-state.md`

- [x] **步骤 1：编写 Agent 动作红灯测试**

新增 `DatasetSearchAction` 解析测试，并在工作台工具测试中模拟模型发出搜索。断言自然语言查询可以触发搜索、动作不能携带 URL/路径/额外字段、搜索后 turn 等待用户选结果；明确 GSE 仍触发原 `geo_lookup`。

```python
def test_dataset_search_action_is_strict():
    action = parse_action({"kind": "dataset_search", "text": "AD brain RNA-seq"})
    assert action.kind == "dataset_search"
    with pytest.raises(ValidationError):
        parse_action({"kind": "dataset_search", "text": "AD", "url": "https://x"})
```

- [x] **步骤 2：运行 Agent 红灯**

```powershell
uv run --offline pytest tests/unit/workbench/test_tool_loop.py tests/integration/api/test_workbench_tools.py -q -p no:cacheprovider
```

预期：`dataset_search` 不是已知 action/tool，测试失败。

- [x] **步骤 3：实现 `dataset_search` 对话动作和会话绑定**

在 `actions.py` 定义字段与 Task 34 查询契约一致的动作；在 `_GEO_TOOLS`、流式 tool-call 白名单、`_validated_geo_action()` 和 `ToolLoop` 终止动作集合中加入 `dataset_search`。

```python
class DatasetSearchAction(_Action):
    kind: Literal["dataset_search"]
    text: str = Field(min_length=2, max_length=256)
    organism: str | None = Field(default=None, max_length=128)
    tissue: str | None = Field(default=None, max_length=128)
    technology: str | None = Field(default=None, max_length=128)
```

`TurnService.bind_geo_search()` 注入搜索服务。`_run_dataset_search()` 从动作构造 `DatasetSearchQuery`，创建搜索并保存会话 `geo_search_id`，发出 `geo.search` 事件，随后 `require_input("请从 GEO 搜索结果中选择一个数据集继续。")`。

为 `conversations` 增加向后兼容的 nullable `geo_search_id` 列和 getter/setter；选择 source 后保留 search ID 用于 provenance，同时沿用 `geo_source_id` 展示现有卡片。重启、切换对话和 SSE 重放从服务端 ID 恢复。

- [x] **步骤 4：Agent 定向测试转绿**

```powershell
uv run --offline pytest tests/unit/workbench/test_tool_loop.py tests/integration/api/test_workbench_tools.py tests/unit/workbench/test_workbench_store.py -q -p no:cacheprovider
```

预期：全部通过，原 `geo_lookup` 测试保持通过。

- [x] **步骤 5：编写前端红灯测试**

`GeoSearchResults.test.tsx` 只覆盖有意义的交互：显示规范化查询和不可信摘要、点击“检查可分析文件”提交 accession/revision、分页使用服务端 token、FAILED 显示稳定错误并允许重试。

```tsx
it("selects a server-owned GEO hit for inspection", async () => {
  render(<GeoSearchResults search={searchFixture} onSelect={onSelect} onNext={onNext} />);
  await userEvent.click(screen.getByRole("button", { name: /检查 GSE111 的可分析文件/ }));
  expect(onSelect).toHaveBeenCalledWith("GSE111", searchFixture.revision);
});
```

- [x] **步骤 6：运行前端红灯**

```powershell
npm --prefix frontend run test -- --run src/features/geo/GeoSearchResults.test.tsx
```

预期：组件或 API 类型尚不存在，套件失败。

- [x] **步骤 7：实现 API 客户端、状态恢复和搜索结果卡**

在 `types.ts` 定义与后端 JSON 一致的 `GeoSearchState`、`DatasetSearchHit` 和 request 类型；`client.ts` 增加 create/get/next/select/cancel。`App.tsx` 订阅 `geo.search.updated` 和 `geo.search.selected`，事件到达后 GET 完整状态；选择成功后设置返回的 source 并继续现有 `GeoSourceCard`。

`GeoSearchResults.tsx` 使用文本节点显示 query/title/summary，官方链接固定新窗口且 `rel="noreferrer"`。按钮文字为“检查可分析文件”，搜索结果不显示“立即分析”；`NEEDS_INSPECTION` 明确说明还需检查 raw counts。页码、取消、失败重试均使用服务端状态，不在浏览器推断完成态。

- [x] **步骤 8：前后端回归、更新状态并提交 Task 35**

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
uv run --offline pytest tests/unit/workbench tests/integration/api/test_workbench_tools.py tests/integration/api/test_geo.py -q -p no:cacheprovider
uv run --offline ruff check .
uv run --offline mypy src
git add src/bioagent/workbench/actions.py src/bioagent/workbench/models.py src/bioagent/workbench/store.py src/bioagent/workbench/tool_loop.py src/bioagent/workbench/turns.py src/bioagent/api/dependencies.py frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/features/chat/ChatTimeline.tsx frontend/src/features/geo/GeoSearchResults.tsx frontend/src/features/geo/GeoSearchResults.test.tsx frontend/src/App.tsx tests/unit/workbench/test_tool_loop.py tests/integration/api/test_workbench_tools.py docs/superpowers/plans/2026-09-14-geo-search-rag.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务35): 接入Agent GEO搜索与结果界面"
```

## Task 36：搜索 provenance、RAG 接口与端到端验收

**创建：**

- `src/bioagent/retrieval/knowledge.py`
- `tests/unit/retrieval/test_knowledge.py`
- `tests/e2e/test_geo_search_workflow.py`
- `frontend/e2e/geo-search.spec.ts`

**修改：**

- `src/bioagent/retrieval/__init__.py`
- `src/bioagent/geo/models.py`
- `src/bioagent/geo/repository.py`
- `src/bioagent/geo/search_service.py`
- `src/bioagent/geo/service.py`
- `src/bioagent/artifacts/manifest.py`
- `src/bioagent/services/analysis.py`
- `src/bioagent/execution/controller.py`
- `src/bioagent/api/dependencies.py`
- `README.md`
- `docs/geo.md`
- `docs/architecture.md`
- `SECURITY.md`
- `tests/unit/artifacts/test_manifest.py`
- `tests/unit/execution/test_controller.py`
- `docs/superpowers/plans/2026-09-14-geo-search-rag.md`
- `docs/progress/current-state.md`

- [x] **步骤 1：编写 provenance 与 RAG 边界红灯测试**

`test_knowledge.py` 断言 `NullKnowledgeRetriever` 返回明确未配置错误，`KnowledgeEvidence` 必须带 document/chunk/source/hash，且接口结果不能作为 Dataset 或 action 解析。

```python
def test_null_retriever_is_explicitly_unconfigured():
    with pytest.raises(KnowledgeRetrievalError, match="RAG_NOT_CONFIGURED"):
        NullKnowledgeRetriever().retrieve(KnowledgeQuery(text="DESeq2 shrinkage"))
```

`test_geo_search_workflow.py` 使用固定模型动作、MockTransport 和合成 counts，断言搜索快照 → selected accession → source → dataset → run manifest 的 ID/hash 链一致，审批前 attempts 为空；RAG 未配置不影响 GEO 搜索。

- [x] **步骤 2：运行 Python 红灯**

```powershell
uv run --offline pytest tests/unit/retrieval/test_knowledge.py tests/e2e/test_geo_search_workflow.py -v -p no:cacheprovider
```

预期：知识接口和搜索 provenance 字段尚不存在而失败。

- [x] **步骤 3：实现独立 KnowledgeRetriever 与依赖边界**

`knowledge.py` 定义冻结的 `KnowledgeQuery`、`KnowledgeEvidence`、`KnowledgeRetriever`、`KnowledgeRetrievalError` 和 `NullKnowledgeRetriever`。

```python
class KnowledgeRetriever(Protocol):
    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]: ...


class NullKnowledgeRetriever:
    def retrieve(self, query: KnowledgeQuery) -> tuple[KnowledgeEvidence, ...]:
        raise KnowledgeRetrievalError("RAG_NOT_CONFIGURED")
```

依赖容器接受 `knowledge_retriever` override，默认注入 Null 实现。本任务不增加模型知识搜索动作、向量数据库、embedding、文档上传或凭据表；接口仅保证未来实现可替换。

- [x] **步骤 4：绑定搜索 provenance 到 source 和 run**

用户选择搜索结果时生成不可变 `GeoSearchProvenance`：search ID、query hash、provider、selected accession、selection revision、retrieved_at 和 evidence hash。`GeoImportService.create_source()` 接受可选的已验证 provenance；`GeoRepository` 把它写入 `source.json`，读取时复算并校验。

`RunManifest` 增加可选 `search_provenance`，旧 manifest 默认 `None`。`AnalysisService` 和 `ExecutionController` 只从已验证 source 复制该值，模型和前端不能提交。执行前和恢复时同时校验 source artifact hash，因此改变 query、selection 或 accession 会拒绝来源复用。`test_manifest.py` 验证旧 manifest 兼容，`test_controller.py` 验证篡改 search provenance 后拒绝执行或恢复。

- [x] **步骤 5：Python 定向测试转绿**

```powershell
uv run --offline pytest tests/unit/retrieval tests/unit/geo tests/e2e/test_geo_search_workflow.py tests/e2e/test_geo_workflow.py -q -p no:cacheprovider
uv run --offline ruff check .
uv run --offline mypy src
```

预期：全部通过；原来直接 GSE 和本地上传产生的 manifest 仍可读取。

- [x] **步骤 6：编写并运行一个浏览器端到端流程**

`frontend/e2e/geo-search.spec.ts` 通过 Playwright route fixture 返回固定搜索、source、import 和 run 状态，覆盖“输入关键词 → 展示候选 → 选择 GSE → 确认 counts → 映射 → 审批 → COMPLETED”。断言选择搜索结果前没有 import/download 请求。

```powershell
npm --prefix frontend run e2e -- --grep "GEO keyword search"
```

预期：通过；网络只命中本地浏览器 fixture。

- [x] **步骤 7：更新用户文档和安全说明**

README 和 `docs/geo.md` 写明关键词搜索入口、筛选、分页、选择后检查、下载限制和直接 GSE 路径。架构与安全文档写明 DatasetCatalogProvider/KnowledgeRetriever 分离、搜索文本不可信、RAG 尚未配置、凭据不进入 evidence/manifest，以及搜索结果不能绕过 raw counts 和计划审批。

- [x] **步骤 8：运行完整门禁并做 34–36 整体复盘**

```powershell
./scripts/check.ps1
uv run --offline pre-commit run --all-files
git status --short --branch
```

记录真实的 Python、前端、Playwright、R、R/DESeq2、Ruff、mypy、typecheck 和 build 结果。复盘确认：搜索不会直接下载、选择归属和 revision 受控、来源 hash 链完整、直接 GSE 与上传流程兼容、RAG 未配置时行为明确、没有新增统计方法或多 Agent。

- [x] **步骤 9：更新计划/进度并提交 Task 36**

复审修正已重新执行步骤 1–8 的相关边界：`KnowledgeEvidence` 拒绝 userinfo、HTTP 及敏感 query 凭据；source 创建与发布分别从权威 `SELECTING`/`SELECTED` 搜索快照逐字段验证 provenance。新增回归覆盖直接伪造、创建后 state 篡改和 source→dataset→manifest 的完整 hash 链；修正后聚焦集合为 **46 passed in 14.06s**，Ruff、mypy 和 Playwright 关键字流程通过。

最终复审又补齐“自洽 hash 不等于权威”的读取与执行边界：先将已发布 `source.json` 的 query hash 改写并重算 `search_provenance_sha256`，`AnalysisService.create_run()` 红灯为 **1 failed in 17.02s**（原实现错误接受）；再为 Controller 注入同一持久化搜索仓库，加入 run 副本自洽伪造回归，红灯为缺少该显式依赖的 `TypeError`。修正后 source 读取以及 Controller 的执行、复用和恢复均逐字段验证持久化 `SELECTED` 快照；两个聚焦回归为 **2 passed in 17.20s**，无 provenance 的直接 GSE/上传路径保持兼容。

最终双重独立审查继续发现启动恢复、provenance 删除降级、跨 source 替换和 evidence URI 凭据变体四类边界。修正后 `GeoSearchRepository` 将权威 `SELECTED` 快照与具体 `source_id` 绑定；发布、读取、导入、AnalysisService、Controller 和 API 启动恢复均复用同一校验，已绑定搜索来源缺失或替换 provenance 时失败关闭。`KnowledgeEvidence` 同时检查 query/fragment，并拒绝 AWS 签名、`x-api-key`、`client_secret`、`sig`、token 等凭据字段。合并后的相关回归为 **187 passed in 67.67s**，Ruff 与 mypy（80 个 source files）通过。

提交后质量复审再验证了异常恢复和依赖覆盖：持久化 `SELECTING` 在进程重启后转为 `FAILED` 时必须同时清除 selection 字段，保证仓库模型约束成立并可在下一次启动继续读取；容器提供自定义 `GeoRepository` 时也会绑定同一个权威 `GeoSearchRepository`。URI 拒绝列表补齐 `X-Amz-Security-Token`、`session_token` 与 `refresh_token`。红灯为 **5 failed, 12 passed**，修复后的精确集合为 **17 passed**，最终合并回归为 **195 passed in 82.33s**；Ruff 与 mypy（80 个 source files）通过。

```powershell
git add src/bioagent/retrieval/__init__.py src/bioagent/retrieval/knowledge.py src/bioagent/geo/models.py src/bioagent/geo/repository.py src/bioagent/geo/search_service.py src/bioagent/geo/service.py src/bioagent/artifacts/manifest.py src/bioagent/services/analysis.py src/bioagent/execution/controller.py src/bioagent/api/dependencies.py tests/unit/retrieval/test_knowledge.py tests/unit/artifacts/test_manifest.py tests/unit/execution/test_controller.py tests/e2e/test_geo_search_workflow.py frontend/e2e/geo-search.spec.ts README.md docs/geo.md docs/architecture.md SECURITY.md docs/superpowers/plans/2026-09-14-geo-search-rag.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务36): 完成GEO搜索审计与RAG扩展接口"
```

Task 37 文档同步：Task 34/35 复选框依据提交 527f1cc、7635e6d、6cfb22b、41856c0 及 current-state.md 的红绿测试和门禁记录补齐；没有重做已有功能。
