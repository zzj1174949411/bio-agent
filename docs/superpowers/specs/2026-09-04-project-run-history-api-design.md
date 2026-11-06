# Bio-Agent 项目运行历史 API 设计规格

**状态：** 已批准

**日期：** 2026-09-04

**目标任务：** Task 12.1

## 1. 背景

Task 12 的 Streamlit Run History 只能读取浏览器 Session State 中已知的 run ID。关闭浏览器或换一个会话后，界面无法发现项目已经创建的其他分析任务。

后端已经为每个 run 保存 `runs/<run_id>/run.json`，完成态还保存独立的 `manifest.json`。现有 API 只能通过 `GET /api/v1/runs/{run_id}` 查询已知 run，缺少项目级列表接口。

## 2. 目标

新增只读项目运行历史能力，使 Streamlit 可以通过 HTTP API 查看当前 Bio-Agent 项目下的全部分析任务，包括：

- `DRAFT`
- `VALIDATING`
- `AWAITING_APPROVAL`
- `QUEUED`
- `RUNNING`
- `COMPLETED`
- `VALIDATION_FAILED`
- `FAILED`
- `CANCELLED`

列表需要展示 run ID、dataset ID、状态、QC、plan revision、attempt ID 和可用时间信息。完成态必须区分“存在工作流索引”和“manifest 已验证”两种证据强度。

## 3. 非目标

- 不列出 Codex 开发任务、Git commit 或聊天会话。
- 不增加用户账户、项目租户或远程鉴权系统；MVP 仍是本地单用户模式。
- 不允许 Streamlit 扫描 `runs/` 或读取服务器文件路径。
- 不新增 SQLite 运行目录；LangGraph checkpoint 仍只负责工作流恢复。
- 不修改统计方法、审批规则、执行控制或科研 manifest 格式。
- 不提前实现 Task 13 的 Agent eval 或端到端测试内容。

## 4. 方案选择

采用 `RunRepository` 枚举加 API 汇总方案：

1. `RunRepository` 枚举 `runs_dir` 的直接子目录，只接受规范 UUID4 run ID。
2. 每个候选项都通过现有 `RunRepository.read()` 重新解析和校验 `run.json`。
3. API 层将工作流状态缩减为固定的只读摘要，不返回用户目标、完整计划、错误堆栈或文件路径。
4. 对 `COMPLETED` run，API 读取并验证对应 `RunManifest`，只在身份和顶层状态一致时返回 manifest 时间。
5. Streamlit Run History 只调用新的列表 API，不再依赖 Session State 才能发现历史任务。

不采用以下方案：

- Streamlit 直接扫描目录：违反“UI 只通过 HTTP API 使用后端”的已批准边界。
- 新建 SQLite 目录：对本地单用户 MVP 过度设计，并会产生新的迁移与一致性问题。

## 5. API 契约

新增：

```text
GET /api/v1/runs
```

可选查询参数：

- `status`：按一个合法 `RunStatus` 精确过滤；省略时返回全部状态。

成功响应：

```json
{
  "runs": [
    {
      "run_id": "b8b439c9-c576-4f87-ae41-69e0810c38c9",
      "dataset_id": "61d32f63-7c68-41df-814e-296fc47b5730",
      "status": "COMPLETED",
      "qc_status": "WARN",
      "plan_revision": 2,
      "attempt_id": "b99fb530-a935-45d8-8ccd-c5c01c07354d",
      "index_updated_at": "2026-09-04T08:30:00+00:00",
      "completed_at": "2026-09-04T08:29:58+00:00",
      "evidence_status": "VERIFIED"
    }
  ],
  "issues": []
}
```

字段规则：

- `index_updated_at` 来自 `run.json` 的文件修改时间，只用于界面排序，不属于科研 provenance。
- `completed_at` 只来自验证通过的完成态 manifest；其他情况为 `null`。
- `evidence_status` 取值为：
  - `VERIFIED`：完成态 index 与 manifest 的 run、dataset、attempt、状态和 QC 一致。
  - `INDEX_ONLY`：未完成 run，当前只有合法的工作流索引。
  - `INVALID`：run 目录存在，但 index 或完成态 manifest 无法验证。
- 列表按 `index_updated_at` 降序排列；时间相同时按 run ID 升序排列。
- 空项目返回 HTTP 200、空 `runs` 和空 `issues`。
- 非法 `status` 查询值返回 HTTP 422。
- `status` 只过滤能够验证状态的 `runs`；无法读取状态的完整性 `issues` 始终返回。

单个损坏 run 不阻止查看其他任务。损坏项不进入 `runs`，而是在 `issues` 中返回：

```json
{
  "run_id": "b8b439c9-c576-4f87-ae41-69e0810c38c9",
  "code": "RUN_INDEX_INVALID"
}
```

如果完成态 index 合法但 manifest 缺失或不一致，该 run 仍进入 `runs`，`evidence_status` 为 `INVALID`，同时增加稳定 issue：

```json
{
  "run_id": "b8b439c9-c576-4f87-ae41-69e0810c38c9",
  "code": "RUN_MANIFEST_INVALID"
}
```

响应不包含绝对路径、原始异常文本或 manifest 全文。

## 6. 组件职责

### 6.1 RunRepository

新增只读枚举接口，负责：

- 只访问配置的 `runs_dir` 直接子目录。
- 拒绝非 UUID4 目录名和符号链接越界。
- 使用现有 `read()` 校验 run ID、JSON 对象和运行状态。
- 返回合法状态、`run.json` 修改时间和结构化读取问题。

它不读取 manifest，也不决定科研证据是否完整。

### 6.2 FastAPI

新增列表路由，负责：

- 校验可选状态过滤器。
- 将状态投影为固定摘要字段。
- 对完成态读取 `manifest.json`，重用 `RunManifest` 不变量校验。
- 核对 index 与 manifest 的 run ID、dataset ID、attempt ID、status 和 QC。
- 返回每个损坏项的稳定错误码，同时保留其他合法项。

列表 API 是只读操作，不修复、不删除、不重写 run 或 manifest。

### 6.3 Streamlit

`ApiClient` 新增 `list_runs(status=None)`，Run History 每次渲染时从 API 获取项目级历史。

界面展示：

- run ID、dataset ID 和当前状态。
- plan revision、attempt ID 和 QC。
- manifest 验证状态。
- 完成时间；没有验证时间时展示索引更新时间并明确标注。
- API 返回的结构化 issue，不显示服务器路径或原始异常。

Session State 仍只保存当前选中的 dataset ID、run ID、plan revision 和页面选择。项目历史不缓存到 Session State。

## 7. 数据流

```text
Streamlit Run History
  → GET /api/v1/runs
  → RunRepository 枚举并校验 run.json
  → FastAPI 对完成态核验 RunManifest
  → 返回固定摘要与稳定 issues
  → Streamlit 展示并允许选择一个 run 作为当前 run
```

用户在历史列表中选择 run 后，只把该 run ID 写入 Session State。后续 Plan Review、Run Monitor 和 Results 继续使用已有单 run API。

## 8. 安全与一致性

- API 不接受路径，只接受可选枚举状态。
- 所有 run ID 继续使用规范 UUID4 校验。
- 枚举只处理 `runs_dir` 的直接子目录；解析后路径必须仍在根目录内。
- 符号链接、junction 或其他解析后越界项返回稳定 issue，不跟随到项目外部。
- 完成态不能仅凭 `run.json` 宣称 evidence 已验证。
- 列表读取不改变任何状态，避免“查看历史”触发恢复或修复副作用。
- 错误响应不暴露绝对路径、Python 异常文本、API Key 或上传内容。

## 9. 测试策略

按 TDD 先写失败测试，再实现最少代码。

### 9.1 Repository 单元测试

- 空目录返回空列表。
- 多个合法 run 按更新时间降序排列。
- 非 UUID、非法 JSON、身份不一致和越界链接不会作为合法 run 返回。
- 单个损坏项不影响其他合法项。

### 9.2 API 集成测试

- `GET /api/v1/runs` 返回全部状态摘要。
- `status` 过滤准确，非法值返回 422。
- 完成态 manifest 一致时返回 `VERIFIED` 和 `completed_at`。
- manifest 缺失、损坏或身份不一致时返回 `INVALID` 与 `RUN_MANIFEST_INVALID`。
- 响应不包含绝对路径、完整计划、用户目标或原始异常。

### 9.3 Streamlit 测试

- Run History 使用 Mock HTTP client 调用 `GET /api/v1/runs`。
- 新浏览器 Session 不含 run ID 时仍能展示项目历史。
- 选择历史 run 后只保存当前 run ID，不缓存完整列表。
- `VERIFIED`、`INDEX_ONLY`、`INVALID` 和结构化 issues 均有清晰展示。
- AST 测试继续确认 Streamlit 不导入 workflow 或 execution。

### 9.4 完整回归

运行 Task 12.1 定向测试、全量 pytest、Ruff、mypy、OpenAPI 检查和 Streamlit headless 健康检查。

## 10. 实施边界与顺序

Task 12.1 作为单独编号任务插入 Task 12 与 Task 13 之间，单独提交。预计只修改运行存储、API、Streamlit、对应测试、实施计划和进度文件。

Task 12.1 完成并通过验证后，`docs/progress/current-state.md` 的下一任务恢复为 Task 13。不得同时创建 `evals/cases.yaml` 或修改 Task 13 文件。
