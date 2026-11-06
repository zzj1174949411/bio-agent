# 本地工作台与模型配置实现计划

> **面向 AI 代理的工作者：** 使用 `superpowers-zh:executing-plans` 在既有 worktree 逐任务实现；每次领取一个编号任务，步骤使用复选框跟踪。任务 18、21 后整体复盘。

**目标：** 提供可对话、上传、审批、查看结果并切换模型的本地 Web 工作台。

**架构：** React 仅通过 FastAPI REST/SSE 访问后台。新增对话存储和后台 turn 服务，共用已有分析、审批与统计执行链；模型适配与凭据存储分离。

**技术栈：** Python 3.12、uv、FastAPI、SQLite、keyring、React、TypeScript、Vite、Vitest、Testing Library、Playwright；统计环境沿用 renv。

---

## 执行约定与文件地图

规格：[工作台设计](../specs/2026-09-08-workbench-design.md)。依赖基线 `0b14036`，任务 15 剩余远端发布状态独立保留。本文件是未来实施清单，未勾选不代表实现完成。

工作目录固定为 `.worktrees/bio-agent-mvp`，先读取仓库 AGENTS、原设计/计划、current-state 和 Git 状态。新包创建空 `__init__.py`；新测试目录避免与旧模块同名。下列测试代码是必须先写的核心回归，随后按各任务列出的场景扩展；实现片段固定关键契约，其余实现必须满足对应规格。

| 文件 | 职责 / 首次任务 |
| --- | --- |
| `src/bioagent/workbench/{models,store}.py` | 对话记录、事务、事件序号 / 16 |
| `src/bioagent/models/{profiles,store,secrets,adapters}.py` | 模型配置、凭据引用、客户端 / 17 |
| `src/bioagent/workbench/{turns,events}.py` | turn 队列、恢复、SSE 编码 / 18 |
| `src/bioagent/api/{workbench_routes,model_routes,local_access}.py` | 新端点与本地请求保护 / 17–18 |
| `src/bioagent/workbench/actions.py` | 结构化动作与确定性路由 / 19 |
| `src/bioagent/services/analysis.py` | 旧 API 与新工作台共用分析服务 / 19 |
| `frontend/src/{api,features,components}` | API 客户端、对话/结果/设置、通用组件 / 20 |
| `scripts/start-workbench.ps1` | 检查构建并启动本地后端 / 21 |

所有后端测试命令从 worktree 执行并加 `-p no:cacheprovider`。首次依赖安装可联网；自动模型测试始终 Mock，不读真实 Key。每个任务提交前执行下列门禁，记录实际结果、更新本计划当前任务复选框与 `docs/progress/current-state.md`；只暂存该任务列出的文件和这两份状态文档：

```powershell
uv run --offline ruff check .
uv run --offline mypy src
uv run --offline pre-commit run --all-files
git diff --check
git diff --cached --check
```

缓存 ACL 问题使用进度中已验证的临时 UV/PRE_COMMIT 缓存配置；不关闭 hook。下面提交命令里的目录均为本任务新建的明确目录，执行前先用 `git diff --cached --name-only` 排除其他任务或用户改动。不自动 push。

## 任务 16：项目、对话和事务存储

**创建：** `src/bioagent/workbench/__init__.py`、`models.py`、`store.py`；`tests/unit/workbench/test_workbench_store.py`。
**修改：** `src/bioagent/config.py`（独立 workbench DB 路径）。

- [x] 写存储失败测试，使用临时 SQLite，不接模型。公共接口 `WorkbenchStore(path)`、`create_project(title)`、`create_conversation(project_id,title)`、`begin_turn(conversation_id,client_request_id,text,model_snapshot)`、`append_event(conversation_id,turn_id,kind,payload)`、`list_events(conversation_id,after,limit)`、`close()`。

```python
from uuid import uuid4
from bioagent.workbench.store import WorkbenchStore


def test_request_is_idempotent_after_reopen(tmp_path):
    path = tmp_path / "workbench.sqlite"
    store = WorkbenchStore(path)
    project = store.create_project("RNA 项目")
    chat = store.create_conversation(project.id, "第一次分析")
    request_id = uuid4()
    args = dict(conversation_id=chat.id, client_request_id=request_id,
                text="检查数据", model_snapshot=None)
    first = store.begin_turn(**args)
    store.close()
    reopened = WorkbenchStore(path)
    assert reopened.begin_turn(**args).id == first.id
    reopened.close()
```

- [x] 运行 `uv run --offline pytest tests/unit/workbench/test_workbench_store.py -v -p no:cacheprovider`，预期因新模块缺失而失败；保存红灯原因。
- [x] 创建冻结 Pydantic 记录，字段按规格 §4；增加 `updated_at` 支持列表游标，Message 增加 `turn_id` 和 `partial`，支持重启后的部分消息。用独立数据库版本表做向前迁移，未知较新版本拒绝启动。项目/对话创建、重命名和归档，UUID 所属关系与外键检查都在存储边界完成。
- [x] 在一次 `BEGIN IMMEDIATE` 事务内按以下顺序处理幂等和在途约束；相同 request ID 但 payload 不同返回 `REQUEST_ID_CONFLICT`。消息与对应事件同事务保存；事件序号采用每个 conversation 的事务计数器。

```sql
CREATE UNIQUE INDEX turn_request_once
ON turns(conversation_id, client_request_id);
CREATE UNIQUE INDEX one_active_turn
ON turns(conversation_id)
WHERE status IN ('QUEUED', 'RUNNING', 'WAITING_USER');
CREATE UNIQUE INDEX event_sequence
ON events(conversation_id, seq);
```

先查重复 request，再检查 active turn，再写新 turn/用户消息；不能用先查后写的两个事务。终态只包含 COMPLETED、FAILED、CANCELLED；WAITING_USER 仍占用该 conversation。

- [x] 扩展测试覆盖并发重复请求只有一个 turn、不同 request 竞争返回 TURN_BUSY、不同对话互不阻塞、回滚无孤立消息、事件游标不重漏、归档不删证据、分页默认 50/最大 100、损坏外键拒绝、旧数据库重新打开。再次运行上述命令，预期全通过。
- [x] 执行公共门禁、更新进度并提交：

```powershell
git add src/bioagent/workbench src/bioagent/config.py tests/unit/workbench/test_workbench_store.py docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务16): 建立工作台项目对话与事务事件存储"
```

## 任务 17：多模型配置、凭据和探针

**依赖：** 16。
**创建：** `src/bioagent/models/__init__.py`、`profiles.py`、`store.py`、`secrets.py`、`adapters.py`；`src/bioagent/api/model_routes.py`、`local_access.py`；`tests/unit/models/test_model_profiles.py`、`tests/integration/api/test_model_profiles.py`。
**修改：** `pyproject.toml`、`uv.lock`、`.gitignore`、`src/bioagent/api/{app,dependencies}.py`、`src/bioagent/config.py`、`src/bioagent/llm/factory.py`。

- [x] 写失败测试；`ModelProfile` 的 `snapshot()` 返回冻结且无凭据的 `ModelSnapshot`，`public_dict(credential_configured=...)` 明确列出公开字段。

```python
from uuid import uuid4
from bioagent.models.profiles import ModelProfile


def test_snapshot_survives_profile_change():
    profile = ModelProfile(id=uuid4(), label="本地", provider="ollama",
                           model="model-a", base_url="http://127.0.0.1:11434",
                           credential_ref=None, structured_method="function_calling",
                           thinking="default", revision=1)
    snapshot = profile.snapshot()
    changed = profile.model_copy(update={"model": "model-b", "revision": 2})
    assert snapshot.model == "model-a"
    assert changed.snapshot().model == "model-b"
    assert "credential_ref" not in snapshot.model_dump()
    assert "credential_ref" not in profile.public_dict(credential_configured=False)
```

- [x] 运行 `uv run --offline pytest tests/unit/models/test_model_profiles.py tests/integration/api/test_model_profiles.py -v -p no:cacheprovider`，预期缺少模型配置模块/API。
- [x] `uv add keyring` 后锁定依赖；配置入 workbench DB 的独立表，Key 只通过 `SecretStore.set(ref,value)`、`get(ref)`、`delete(ref)` 接口进入 keyring。测试注入内存 SecretStore。旧环境设置投影为只读 profile，禁止经 UI 覆写 `.env`。配置更新用预期 revision 防止并发覆盖；被引用 profile 删除后保留快照但不可再用于新请求。
- [x] 实现 provider 适配及固定探针，保留已有工厂兼容入口。客户端在每次请求开始解析凭据，无跨 revision/凭据修改缓存。DeepSeek 参数必须保持既有故障回归：

```python
def structured_options(provider: str, method: str) -> dict[str, object]:
    if provider == "deepseek":
        return {"method": "function_calling",
                "extra_body": {"thinking": {"type": "disabled"}}}
    if provider == "ollama":
        return {"method": "function_calling"}
    return {"method": method}
```

`extra_body` 传模型构造器，`method` 传 `with_structured_output`，不要原样混传。固定探针只要求返回 `{"ok":true}`，按钮显式触发，60 秒超时；不发送用户数据，也不自动探测全部 profile。按规格 §7 白名单映射异常，不返回异常字符串或 HTTP body。
- [x] 在挂载凭据 API 前实现 local_access：Host 白名单、Origin 精确匹配、同源 bootstrap 随机 CSRF token、新端点写请求校验 token。开发仅允许配置的 5173 origin；无 Origin 的旧 API 请求保持现有兼容。测试恶意 Origin/Host、缺 token、token 不进入 URL、无 keyring 时不创建明文文件；扫描 API/日志/DB/快照中不存在虚拟秘密。补充 DeepSeek/Ollama/兼容 schema 分支、401/429/超时及无自动 fallback 测试。
- [x] 重跑两份新测试及 `uv run --offline pytest tests/unit/llm tests/integration/api -q -p no:cacheprovider`，预期全部通过；执行公共门禁并提交：

```powershell
git add src/bioagent/models src/bioagent/api/model_routes.py src/bioagent/api/local_access.py src/bioagent/api/app.py src/bioagent/api/dependencies.py src/bioagent/config.py src/bioagent/llm/factory.py tests/unit/models/test_model_profiles.py tests/integration/api/test_model_profiles.py pyproject.toml uv.lock .gitignore docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务17): 增加多模型配置与系统凭据存储"
```

## 任务 18：后台对话、SSE 和恢复

**依赖：** 16–17。
**创建：** `src/bioagent/workbench/{turns,events}.py`、`src/bioagent/api/workbench_routes.py`；`tests/unit/workbench/test_turn_service.py`、`tests/integration/api/test_workbench.py`。
**修改：** `workbench/{models,store}.py`、`api/{app,dependencies}.py`。

- [x] 先写游标编码回归以及 Mock 模型后台队列测试。SSE 编码函数必须使用事件结构化 JSON，不能把用户文本拼为事件控制行。

```python
import json
from bioagent.workbench.events import encode_sse


def test_sse_content_cannot_inject_event():
    frame = encode_sse(7, "message.delta", {"text": "你好\n\nid: 99"})
    assert frame.startswith("id: 7\nevent: message.delta\n")
    assert frame.count("\ndata: ") == 1
    assert json.loads(frame.split("data: ", 1)[1]) == {"text": "你好\n\nid: 99"}
```

- [x] 运行 `uv run --offline pytest tests/unit/workbench/test_turn_service.py tests/integration/api/test_workbench.py -v -p no:cacheprovider`，预期新模块/路由失败。
- [x] 实现持久化事件到 SSE 的编码和游标读取；先落盘再推送。`Last-Event-ID` 和 `after` 同时提供时采用两者较大合法值，负值/非法游标 422。单连接分批读 100 条，15 秒注释心跳，断连释放订阅但不取消 turn。

```python
import json


def encode_sse(seq: int, kind: str, payload: dict[str, object]) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {seq}\nevent: {kind}\ndata: {body}\n\n"
```

- [x] TurnService 单独拥有有界聊天队列（最多 32 个排队 turn，满时 429，不使用 R worker）；异步请求立即 202。每轮固定 model snapshot，关联消息与 dataset ID；显式停止设置取消标记，迟到的模型片段不得复活终态。启动时将旧未终止 turn 标为 TURN_INTERRUPTED，保留部分内容，不重放付费请求。实现项目/对话 API、分页、取消和按 request/revision 的澄清响应；模型缺失返回可操作状态。
- [x] 扩展 Mock 测试：慢模型不阻塞 GET/另一个对话；同请求重试不再次调用；切换配置不改变在途快照；重连去重；断连不中止；取消与输出竞争；两次启动不重复失败事件；WAITING_USER 阻止新 turn，旧响应 409。测试 SSE 使用有界消费及可注入时钟，避免依赖无限连接退出。
- [x] 上述测试及 `uv run --offline pytest tests/unit/workbench tests/integration/api -q -p no:cacheprovider` 全通过；公共门禁后进行 **16–18 整体复盘**，确认无模型 Key 持久化、无 R 队列回归。

```powershell
git add src/bioagent/workbench src/bioagent/api/workbench_routes.py src/bioagent/api/app.py src/bioagent/api/dependencies.py tests/unit/workbench/test_turn_service.py tests/integration/api/test_workbench.py docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务18): 接通后台对话事件与重连恢复"
```

## 任务 19：动作到原分析服务与审批

**依赖：** 18。
**创建：** `src/bioagent/services/__init__.py`、`analysis.py`、`src/bioagent/workbench/actions.py`；`tests/unit/workbench/test_actions.py`、`tests/integration/api/test_workbench_analysis.py`。
**修改：** `api/{routes,dependencies}.py`、`workbench/{turns,models,store}.py`、`artifacts/manifest.py`、`execution/controller.py`、`storage/runs.py`（以上路径均位于 `src/bioagent/`）。

- [x] 先写动作白名单失败测试；同文件再覆盖合法 answer、clarify 和 plan_analysis 的 schema、未知字段与伪造审批拒绝。

```python
import pytest
from pydantic import ValidationError
from bioagent.workbench.actions import parse_action


def test_model_cannot_approve_analysis():
    with pytest.raises(ValidationError):
        parse_action({"kind": "approve", "run_id": "any", "approved": True})
```

- [x] 运行 `uv run --offline pytest tests/unit/workbench/test_actions.py tests/integration/api/test_workbench_analysis.py -v -p no:cacheprovider`，预期新动作/工作台分析绑定失败。
- [x] 定义 `AnswerAction(kind="answer",text)`、`ClarifyAction(kind="clarify",question)`、`PlanAnalysisAction(kind="plan_analysis",dataset_id:UUID,goal)`，均 extra forbid，通过 Pydantic discriminator 验证，不解析模型代码。路由表固定三个 handler，最多 8 次动作/120 秒主动时间；上下文限最近 20 条/64 KiB，按完整消息边界截断并发通知。
- [x] 从现有 routes 原样提取 AnalysisService 的 create/read/approve/cancel 业务，保持 per-run 锁、JobRunner 与异常语义；HTTP 路由和动作均直接调用该服务。工作台输入的 dataset 必须已归属于本会话的用户选择，不接受模型猜出的其他 dataset。生成计划后 WAITING_USER；审批仍由旧端点处理，成功/拒绝/取消通过服务通知 turn。未审批不得创建统计 attempt。
- [x] 新增可选 AgentContext 并在 run 初始保存阶段绑定，后续 Controller 复制到 manifest；旧 manifest 缺字段合法。避免先发布 run 再补 context 的崩溃窗口。按既有 manifest 模式重验复制/写入，验证 skill_names 与 skill_hashes 等长、hash 为 64 位十六进制；此阶段二者均为空。快照字段只含非密钥值：

```python
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from bioagent.models.profiles import ModelSnapshot


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    conversation_id: UUID
    turn_id: UUID
    model_snapshot: ModelSnapshot | None = None
    skill_hashes: tuple[str, ...] = ()
    skill_names: tuple[str, ...] = ()
    source_id: UUID | None = None
```

- [x] 集成测试注入确定性动作模型，覆盖上传→对话计划→零 attempt→明确批准→原 worker→QC/报告；修订后旧审批失败、切换模型不改旧计划、R 失败不显示完成、取消、重启及无 context 旧 run。新测试与 `uv run --offline pytest tests/integration/api tests/unit/workflow tests/unit/execution tests/unit/artifacts -q -p no:cacheprovider` 全通过，执行公共门禁。

```powershell
git add src/bioagent/services src/bioagent/workbench src/bioagent/api/routes.py src/bioagent/api/dependencies.py src/bioagent/artifacts/manifest.py src/bioagent/execution/controller.py src/bioagent/storage/runs.py tests/unit/workbench/test_actions.py tests/integration/api/test_workbench_analysis.py docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务19): 连接对话动作与可审计分析审批"
```

## 任务 20：React 工作台与模型设置

**依赖：** 19。
**创建：** `frontend/package.json`、`package-lock.json`、`index.html`、`tsconfig.json`、`vite.config.ts`；`frontend/src/main.tsx`、`App.tsx`、`styles.css`、`layout.ts`、`api/{client,events,types}.ts`、`features/{chat,projects,analysis,models}/*.tsx`、`components/*.tsx`、`test/setup.ts`；前端单元测试覆盖 Composer、事件 reducer、审批卡、模型设置、项目侧栏、澄清卡、资源面板、安全 Markdown、客户端 revision 映射和响应式断点。
**修改：** `.gitignore`。

消息时间线固定为 `frontend/src/features/chat/ChatTimeline.tsx`，输入组件为同目录 `Composer.tsx`；审批组件为 `frontend/src/features/analysis/ApprovalCard.tsx`，模型设置为 `frontend/src/features/models/ModelSettings.tsx`。后续 GEO/扩展只在 ChatTimeline 注册对应卡片，不另建平行聊天页。

- [x] 用 Node 22.12+ 创建 React/TS/Vite 项目，安装并锁定 Vitest、Testing Library、jsdom。配置 `test` 为 `vitest`、`typecheck` 为 `tsc --noEmit`、`build` 为 `tsc --noEmit && vite build`。先写核心事件 reducer 测试和中文输入法测试；不要先画静态完成页。

```typescript
import { expect, it } from "vitest";
import { appendEvent } from "./events";

it("replayed events do not duplicate a message", () => {
  const event = { seq: 3, kind: "message.delta", payload: { text: "你好" } };
  const once = appendEvent([], event);
  expect(appendEvent(once, event)).toEqual(once);
});
```

- [x] 运行 `npm --prefix frontend run test -- --run`，预期缺 reducer/组件导致失败。
- [x] 实现客户端：bootstrap CSRF、JSON 错误映射、上传、模型配置、SSE fetch 流（断线带游标指数退避，最大 30 秒）、AbortController；浏览器存储只保留选中资源 ID，不保存消息或密钥。事件 reducer 只按 seq 去重，展示完成状态必须使用对应 run 的可信状态。

```typescript
export type WorkbenchEvent = {
  seq: number; kind: string; payload: Record<string, unknown>;
};
export function appendEvent(items: WorkbenchEvent[], event: WorkbenchEvent) {
  if (items.some(item => item.seq === event.seq)) return items;
  return [...items, event].sort((left, right) => left.seq - right.seq);
}
```

- [x] 实现规格 §2 三栏布局与三个断点、项目/对话归档、输入/附件/模型选择、澄清和原计划审批卡、进度停止、QC/图表/沙箱报告/下载、空状态和断连重试。Composer 的 `onKeyDown` 仅在 Enter、非 Shift、`!event.nativeEvent.isComposing` 时提交；禁止在渲染时自动发送。设置页完成 profile CRUD、凭据写入后清空输入、连接探针和错误解释。
- [x] 组件测试覆盖 IME 不发送、Shift 换行、重复发送禁用、数据集/每轮模型选择、旧 revision 响应映射、模型切换提示下一轮生效、虚拟 Key 不进 localStorage/DOM 回显、原始 HTML 与危险链接不执行、报告 iframe 无脚本权限、QC/图表/逐个下载和 900/1200 响应式断点。
- [x] 执行 `npm --prefix frontend run test -- --run`、`npm --prefix frontend run typecheck`、`npm --prefix frontend run build`，全部退出 0；公共门禁后提交，构建产物与 node_modules 不暂存：

```powershell
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/src .gitignore docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务20): 实现本地对话工作台与模型设置界面"
```

## 任务 21：启动、浏览器验收和门禁

**依赖：** 20。
**创建：** `scripts/start-workbench.ps1`、`frontend/playwright.config.ts`、`frontend/e2e/{global-setup.ts,workbench.spec.ts}`、`tests/integration/api/test_workbench_static.py`、`tests/e2e/test_workbench_workflow.py`、`tests/unit/test_workbench_start.py`、`docs/workbench.md`。
**修改：** `src/bioagent/api/app.py`、`scripts/check.ps1`、`.github/workflows/ci.yml`、`.gitignore`、`frontend/package.json`、`frontend/package-lock.json`、`README.md`、`docs/architecture.md`、`SECURITY.md`、`tests/unit/test_check_script.py`。

- [x] 先写静态/API 路由分离测试与真实 R 端到端。测试沿用 `create_app(settings, overrides)` 工厂，临时静态目录 fixture 包含 index.html，mock 模型；API 未知路径必须保持 JSON 404。浏览器用固定演示后端，测试配置禁止加载真实 provider。

```typescript
import { test, expect } from "@playwright/test";

test("workbench loads with an accessible composer", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "消息" })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeVisible();
});
```

- [x] 运行 `uv run --offline pytest tests/integration/api/test_workbench_static.py tests/unit/test_workbench_start.py -v -p no:cacheprovider` 与 `npm --prefix frontend run e2e`，预期根路由/启动脚本/浏览器入口缺失，记录真实失败。
- [x] FastAPI 先注册 API，再注册静态资源与 SPA fallback；fallback 只处理前端路由，未知 `/api/` 返回原 JSON 404，缺 dist 时展示明确构建提示。HTML 不能缓存旧资源映射，哈希资源可缓存。启动脚本检查 Node/uv/Rscript/dist、端口冲突明确退出，使用前台 `uv run uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port 8000`，不杀其他进程；Ctrl+C 清理自己拥有的资源。
- [x] Playwright fixture 启动固定 Mock 模型后端，覆盖项目→上传 counts/metadata→消息→计划→未审批无 attempt→批准→QC/报告/逐个下载哈希；参数化 shrink 开/关在真实 R 的 Python e2e 验证。增加浏览器刷新/SSE 重连、取消、后端中断、模型切换、无 Key 提示、窄屏和键盘操作。fixture 的自动审批仅用于合成数据，手工用户 run 仍须用户批准。
- [x] 写首次安装、生产构建、单命令启动、开发双终端、设置 provider/base URL/model/Key、固定演示、日志定位和 R 前置条件。新增 CI 前端 job 使用 Node 22、`npm ci`、typecheck、test、build、Playwright；原 Windows/Ubuntu Python/R 门禁保持。统一 check.ps1 增加前端门禁，不将缺 Node 静默标为成功。

```powershell
npm --prefix frontend ci
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run e2e
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

- [x] 全部通过后做 **19–21 整体复盘**，记录浏览器真实结果、R 结果、未执行的远端检查；独立交付 A，不依赖 GEO 或 MCP。更新进度和公共门禁后提交：

```powershell
git add scripts/start-workbench.ps1 scripts/check.ps1 .github/workflows/ci.yml .gitignore src/bioagent/api/app.py frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/playwright.config.ts frontend/e2e tests/integration/api/test_workbench_static.py tests/e2e/test_workbench_workflow.py tests/unit/test_workbench_start.py tests/unit/test_check_script.py docs/workbench.md README.md docs/architecture.md SECURITY.md docs/superpowers/plans/2026-09-08-workbench.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务21): 交付工作台启动入口与完整验收"
```

## 计划自检

- 规格的存储/恢复落在 16/18，模型与本地访问边界落在 17，受约束规划和旧 API 兼容落在 19，界面落在 20，启动与完整验收落在 21。
- 每个新能力有可观察失败测试；已有 R 收缩和输出列契约沿用真实 e2e，不改 QC 来迁就结果。
- 此阶段不实现 GEO、Skills、MCP 或多 Agent；下一份为 [GEO 计划](2026-09-08-geo.md)。
