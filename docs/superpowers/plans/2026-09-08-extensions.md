# Skills 与 MCP 扩展实现计划

> **面向 AI 代理的工作者：** 使用 `superpowers-zh:executing-plans` 在既有 worktree 逐任务实现；每次一个编号任务，步骤使用复选框跟踪。任务 30、33 后整体复盘。

**目标：** 在工作台配置本地 Skills 与 MCP 服务，让单个 Agent 在受控权限下选择并调用扩展工具。

**架构：** SkillCatalog 提供按 hash 固定的说明，MCP adapter 提供工具描述与连接；ToolGateway 在模型和工具之间执行 schema、权限、预算和一次性批准。统计执行仍沿用既有 AnalysisPlan/Controller/R/QC。

**技术栈：** Python/uv、正式发布版 MCP Python SDK、JSON Schema、SQLite、keyring、React/TypeScript、Vitest、Playwright、本地 fixture MCP server。

---

## 依赖、文件和共同门禁

规格：[扩展设计](../specs/2026-09-08-extensions-design.md)。依赖 [GEO 任务 27](2026-09-08-geo.md)；不扩展到多 Agent、通用执行器、云账户授权或自动安装市场。

| 文件 | 职责 / 任务 |
| --- | --- |
| `src/bioagent/extensions/{models,skills,store}.py` | Skill 索引、文本快照、配置 / 28 |
| `src/bioagent/extensions/mcp_client.py` | SDK adapter 与连接生命周期 / 29 |
| `src/bioagent/extensions/{policy,gateway}.py` | 工具描述、schema、决策与调用 / 30 |
| `src/bioagent/api/extension_routes.py` | 扩展配置/工具批准 API / 30–31 |
| `src/bioagent/workbench/tool_loop.py` | 已有 turn 内的受限工具循环 / 31 |
| `frontend/src/features/extensions/` | Skill/MCP 设置和工具确认 / 32 |
| `tests/fixtures/mcp/` | 只在本地运行的协议测试服务 / 29 |

新 Python 包创建 `__init__.py`。新增配置存入已有 workbench DB 的版本化独立表，迁移不能删除旧表或 checkpoint。每个任务先运行新失败测试，再实现；完成后更新本计划复选框和 `docs/progress/current-state.md`，执行：

```powershell
uv run --offline ruff check .
uv run --offline mypy src
uv run --offline pre-commit run --all-files
git diff --check
git diff --cached --check
```

仅暂存任务明确文件，检查 `git diff --cached --name-only`，不包含私有 Skill、密钥、MCP 本机配置或运行数据；仅本地提交，不自动 push。模型测试全部 Mock，MCP 测试服务无外网依赖。

## 任务 28：本地 Skill 发现、校验与快照

**创建：** `src/bioagent/extensions/__init__.py`、`models.py`、`skills.py`、`store.py`；`tests/unit/extensions/test_skills.py`。
**修改：** `src/bioagent/config.py`、`.gitignore`、`pyproject.toml`、`uv.lock`（如 safe YAML 解析依赖尚未显式声明）。

- [ ] 写 Skill 路径逃逸失败测试。`resolve_reference(skill_directory,relative_path)` 拒绝绝对路径、父目录、远程 URL 和解析后越界；异常为 `SkillPathError`。

```python
import pytest
from bioagent.extensions.skills import SkillPathError, resolve_reference


def test_reference_cannot_escape_skill(tmp_path):
    skill = tmp_path / "skills" / "rnaseq"
    skill.mkdir(parents=True)
    with pytest.raises(SkillPathError):
        resolve_reference(skill, "../../secrets.txt")
```

- [ ] 运行 `uv run --offline pytest tests/unit/extensions/test_skills.py -v -p no:cacheprovider`，预期新模块缺失。
- [ ] 按配置根的一层子目录发现 SKILL.md，用 safe YAML 解析 frontmatter，必需 name/description，可选 allowed_tools；不执行 YAML tag、模板或脚本。记录规格 §2 的 SkillRecord 字段，用户启用时绑定 expected_hash。引用文本仅限当前 Skill 内、最多深度 3、循环检测；UTF-8、64 KiB 单文件/128 KiB 每轮/最多三个 Skill。

```python
from pathlib import Path, PureWindowsPath


class SkillPathError(ValueError):
    pass


def resolve_reference(skill_directory: Path, relative_path: str) -> Path:
    if (Path(relative_path).is_absolute() or PureWindowsPath(relative_path).drive
            or ":" in relative_path or ".." in relative_path.replace("\\", "/").split("/")):
        raise SkillPathError("SKILL_PATH_REJECTED")
    root = skill_directory.resolve(strict=True)
    result = (root / relative_path).resolve(strict=True)
    if not result.is_relative_to(root):
        raise SkillPathError("SKILL_PATH_REJECTED")
    return result
```

- [ ] Skill 正文与已加载引用都作为冻结内容快照保存；记录入口 hash 及有序引用 hash，任一加载文件变化使组合 hash 变化并需重新启用。模型只看到已启用的名称/说明目录，明确请求后才加载正文。allowed_tools 与本地已授权集合取交集，不能扩大权限；没有 allowed_tools 表示不增加额外限制，不表示授权全部工具。
- [ ] 扩展测试覆盖重复名称、无 frontmatter、危险 YAML、非法 UTF-8、文件过大、引用深度/循环/符号链接、引用内容变更、禁用后不可新加载、旧 turn 保留旧快照、凭据模板原样文本不展开。Windows symlink 无权限可单独 skip，但 Linux CI 必须执行。测试全通过与共同门禁后提交：

```powershell
git add src/bioagent/extensions/__init__.py src/bioagent/extensions/models.py src/bioagent/extensions/skills.py src/bioagent/extensions/store.py src/bioagent/config.py .gitignore pyproject.toml uv.lock tests/unit/extensions/test_skills.py docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务28): 增加本地Skill发现校验与内容快照"
```

## 任务 29：MCP 配置与两种 transport

**依赖：** 28。
**创建：** `src/bioagent/extensions/mcp_client.py`；`tests/unit/extensions/test_mcp_client.py`、`tests/integration/test_mcp_transports.py`、`tests/fixtures/mcp/{server,child_process}.py`。
**修改：** `src/bioagent/extensions/{models,store}.py`、`src/bioagent/api/dependencies.py`、`pyproject.toml`、`uv.lock`。

- [ ] 写端点验证失败测试。`validate_http_endpoint(value)` 允许 localhost/127.0.0.1/[::1] HTTP，其他地址必须 HTTPS；禁止 userinfo、fragment，保留合法 path/query（query 不允许凭据）。

```python
import pytest
from bioagent.extensions.mcp_client import validate_http_endpoint


def test_plain_http_is_local_only():
    assert validate_http_endpoint("http://127.0.0.1:8765/mcp")
    with pytest.raises(ValueError, match="MCP_ENDPOINT_INVALID"):
        validate_http_endpoint("http://remote.example/mcp")
```

- [ ] 运行 `uv run --offline pytest tests/unit/extensions/test_mcp_client.py tests/integration/test_mcp_transports.py -v -p no:cacheprovider`，预期客户端与 fixture transport 尚不存在。
- [ ] 查看 MCP 官方正式 release 与对应版本客户端文档，用 `uv add mcp` 获取发布版并锁入 uv.lock，在文档记录实际版本和支持协议；不得把 main 分支 API 直接当已安装接口。公共 adapter 固定 `connect(config)`、`list_tools(server_id)`、`call_tool(server_id,name,arguments,timeout)`、`disconnect(server_id)`、`close()`，底层 SDK 类型只存在 adapter 文件内。测试通过工厂注入 fake session，另外使用真实 SDK 与本地 fixture server 验证两种 transport。
- [ ] stdio 配置绝对 executable/argv/cwd，进程 shell=False、最小系统环境加显式 secret refs；用户连接动作才启动，禁止根据模型文本安装或生成命令。连接最多 8 个、连接和发现各 10 秒、调用默认 60 秒/最高 300 秒/不超过 turn 剩余时间。HTTP 禁用重定向，secret header 仅发给确切 origin；日志与配置读取只返回 configured 标志。

```python
from urllib.parse import urlsplit


def validate_http_endpoint(value: str) -> str:
    parts = urlsplit(value)
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    valid = parts.scheme == "https" or (parts.scheme == "http" and local)
    if not valid or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("MCP_ENDPOINT_INVALID")
    return value
```

- [ ] fixture 提供 echo（只回显测试参数）、大结果、延迟、返回 isError、退出及派生子进程模式；使用临时端口。测试工具发现/协议协商、失败清理、超时/取消、2 MiB 限额、配置更改不污染在途连接、禁止继承模型 Key、无任意重定向、stdout 协议/stderr 脱敏、退出仅清理自己进程树。HTTP 请求体流式限额和 stdio 消息帧限额需在完整 JSON 分配前生效；若 SDK 缺少公开限额接口，在 adapter transport 层做有界读取，不只事后截断。
- [ ] 新测试全通过，执行 `uv run --offline pytest tests/unit/extensions tests/integration/test_mcp_transports.py -q -p no:cacheprovider` 与共同门禁，然后提交：

```powershell
git add src/bioagent/extensions/mcp_client.py src/bioagent/extensions/models.py src/bioagent/extensions/store.py src/bioagent/api/dependencies.py pyproject.toml uv.lock tests/unit/extensions/test_mcp_client.py tests/integration/test_mcp_transports.py tests/fixtures/mcp/server.py tests/fixtures/mcp/child_process.py docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务29): 接入MCP本地进程与HTTP客户端"
```

## 任务 30：工具 policy、schema 与一次性批准

**依赖：** 29。
**创建：** `src/bioagent/extensions/{policy,gateway}.py`、`src/bioagent/api/extension_routes.py`；`tests/unit/extensions/test_tool_policy.py`、`tests/integration/api/test_extensions.py`。
**修改：** `src/bioagent/extensions/{models,store}.py`、`src/bioagent/api/{app,dependencies}.py`、`pyproject.toml`、`uv.lock`（显式 JSON Schema 依赖）。

- [ ] 写默认权限不信任服务自报的测试。`initial_policy(annotations)` 总是 CONFIRM；只有本地用户配置可改变 policy。

```python
from bioagent.extensions.policy import ToolPolicy, initial_policy


def test_readonly_annotation_cannot_grant_permission():
    assert initial_policy({"readOnlyHint": True}) == ToolPolicy.CONFIRM
    assert initial_policy({"destructiveHint": False}) == ToolPolicy.CONFIRM
```

- [ ] 运行 `uv run --offline pytest tests/unit/extensions/test_tool_policy.py tests/integration/api/test_extensions.py -v -p no:cacheprovider`，预期策略/批准 API 不存在。
- [ ] 定义 ToolDescriptor 与 qualified name，输入 JSON Schema 本地验证，不允许远程 `$ref` 自动联网；schema 规范化 hash 加连接 revision/policy 构成 capability revision。保存 DENY/CONFIRM/ALLOW_READ；默认实现如下，annotations 仅展示：

```python
from enum import StrEnum


class ToolPolicy(StrEnum):
    DENY = "DENY"
    CONFIRM = "CONFIRM"
    ALLOW_READ = "ALLOW_READ"


def initial_policy(annotations: dict[str, object]) -> ToolPolicy:
    return ToolPolicy.CONFIRM
```

- [ ] 批准表保存随机 approval_id、call_id、conversation/turn、capability revision、规范化 arguments hash、expires_at、used_at；10 分钟过期，原子 `UPDATE ... WHERE used_at IS NULL AND expires_at > now` 消费，一次批准最多一次调用。参数/配置/schema 变化 409，不自动把旧 ALLOW_READ 转给新 schema；取消 turn 撤销等待批准，过期不能调用。analysis.approve 永不登记为工具。
- [ ] 挂载 Skill 根目录 GET/PATCH、列表/预览/启停与 MCP 配置/凭据/连接/工具 policy/批准 API（规格 §6），统一 CSRF/Host/Origin 保护。根目录只能由用户设置，根变更撤销受影响 Skill 的启用状态，模型工具目录不提供配置写接口。gateway 校验 policy→schema→批准→预算→调用，事件只包含脱敏参数与 hash；结构化结果若声明 output schema 则校验，isError 映射稳定失败，工具文本不能更新运行状态。
- [ ] 扩展测试覆盖伪造只读、不同 turn/参数/版本、过期、并发双批准、危险 schema/远程引用、工具名冲突、取消后批准、Key 不进 DB/事件/错误、2 MiB 结果与 unknown outcome 不重试。新测试全通过，共同门禁及 **28–30 整体复盘**后提交：

```powershell
git add src/bioagent/extensions/policy.py src/bioagent/extensions/gateway.py src/bioagent/extensions/models.py src/bioagent/extensions/store.py src/bioagent/api/extension_routes.py src/bioagent/api/app.py src/bioagent/api/dependencies.py pyproject.toml uv.lock tests/unit/extensions/test_tool_policy.py tests/integration/api/test_extensions.py docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务30): 建立MCP工具权限与一次性调用批准"
```

## 任务 31：对话中的 Skill 选择与工具循环

**依赖：** 30。
**创建：** `src/bioagent/workbench/tool_loop.py`、`tests/unit/workbench/test_tool_loop.py`、`tests/integration/api/test_workbench_tools.py`。
**修改：** `src/bioagent/workbench/{actions,turns,models}.py`、`src/bioagent/extensions/{gateway,store}.py`、`src/bioagent/api/extension_routes.py`、`src/bioagent/services/analysis.py`。

- [ ] 写确定性预算测试。`TurnBudget(max_actions,max_active_seconds)`、`consume(active_seconds)` 在动作开始前消耗额度，工具超时取剩余预算；超过抛 `TurnBudgetExceeded`。

```python
import pytest
from bioagent.workbench.tool_loop import TurnBudget, TurnBudgetExceeded


def test_budget_cannot_be_reset_by_tool_output():
    budget = TurnBudget(max_actions=2, max_active_seconds=120)
    budget.consume(active_seconds=1)
    budget.consume(active_seconds=1)
    with pytest.raises(TurnBudgetExceeded):
        budget.consume(active_seconds=0)
```

- [ ] 运行 `uv run --offline pytest tests/unit/workbench/test_tool_loop.py tests/integration/api/test_workbench_tools.py -v -p no:cacheprovider`，预期工具循环缺失。
- [ ] 动作扩展 mcp_call 和 load_skill；load_skill 只接受启用且在当前 capability snapshot 的 Skill ID，最多三项。先把可用工具和 Skill 摘要送模型，再按结构化动作进入 gateway。每个 turn 最多八次动作和 120 秒活动时长，等待用户暂停计时；模型重试与失败调用均消耗预算。预算和调用状态落盘，恢复不重发未知调用。

```python
from dataclasses import dataclass


class TurnBudgetExceeded(RuntimeError):
    pass


@dataclass
class TurnBudget:
    max_actions: int = 8
    max_active_seconds: float = 120
    actions: int = 0
    active_seconds: float = 0

    def consume(self, active_seconds: float) -> None:
        if active_seconds < 0:
            raise ValueError("negative duration")
        if (self.actions >= self.max_actions
                or self.active_seconds + active_seconds >= self.max_active_seconds):
            raise TurnBudgetExceeded("TURN_BUDGET_EXCEEDED")
        self.actions += 1
        self.active_seconds += active_seconds
```

实现循环还须实时计时并以剩余时间限制请求；上面核心累计器不能替代执行截止时间。
- [ ] 内置 geo.lookup/import、run.plan/status/artifacts 经统一 gateway；仍调用原确定性服务，下载/统计的确认边界保持。工具结果作为带来源的不可信数据，最多取 16 KiB 摘要进入下一轮，超长显示截断；不执行其“改系统提示/发密钥/已批准”内容。Skill 内容不做环境变量替换，实际加载 hash 与 model snapshot 写入 run agent_context。
- [ ] WAITING_USER 保存批准 call 关联；批准成功继续同一 turn，重复响应不重调。取消只停止本地等待/请求，远端结果未知显示 TOOL_OUTCOME_UNKNOWN；重启未结束 call 不自动重发。测试模型→Skill→只读 fixture→解释、CONFIRM 挡住调用、DENY 不进入目录、循环八次终止、恶意工具注入不产生批准、原 DESeq2 仍需人工审批、快照不会随设置修改。
- [ ] 新测试与 `uv run --offline pytest tests/unit/extensions tests/unit/workbench tests/integration/api -q -p no:cacheprovider` 全通过，共同门禁后提交：

```powershell
git add src/bioagent/workbench/tool_loop.py src/bioagent/workbench/actions.py src/bioagent/workbench/turns.py src/bioagent/workbench/models.py src/bioagent/extensions/gateway.py src/bioagent/extensions/store.py src/bioagent/api/extension_routes.py src/bioagent/services/analysis.py tests/unit/workbench/test_tool_loop.py tests/integration/api/test_workbench_tools.py docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务31): 接通Skill选择与受控MCP工具循环"
```

## 任务 32：扩展设置和调用确认卡

**依赖：** 31。
**创建：** `frontend/src/features/extensions/{SkillSettings,McpSettings,ToolPolicyEditor,ToolApprovalCard}.tsx`、`SkillSettings.test.tsx`、`McpSettings.test.tsx`、`ToolApprovalCard.test.tsx`。
**修改：** `frontend/src/api/{types,client}.ts`、`frontend/src/App.tsx`、`frontend/src/features/chat/ChatTimeline.tsx`、`frontend/src/styles.css`。

- [ ] 写批准卡展示目标且需显式点击测试。ToolApprovalCard 的 `request` 包含 id/tool/target/arguments/capabilityRevision/argumentsHash/expiresAt，`onDecide` 只在用户点击触发。

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ToolApprovalCard } from "./ToolApprovalCard";

it("shows the destination without approving on render", () => {
  const decide = vi.fn();
  render(<ToolApprovalCard request={{
    id: "approval-1", tool: "echo", target: "http://127.0.0.1:8765/mcp",
    arguments: { text: "hello" }, capabilityRevision: "r1",
    argumentsHash: "a".repeat(64), expiresAt: "2099-01-01T00:00:00Z"
  }} onDecide={decide} />);
  expect(screen.getByText("http://127.0.0.1:8765/mcp")).toBeVisible();
  expect(decide).not.toHaveBeenCalled();
});
```

- [ ] 运行 `npm --prefix frontend run test -- --run`，预期扩展组件缺失。
- [ ] Skills 页显示配置根、内容/引用预览、组合 hash、启停、扫描错误；修改文件提示重新启用。MCP 页提供两种 transport 分支表单、env/header 凭据引用、精确命令/endpoint 预览、连接/断开、协议与工具目录；点击连接前必须已有用户保存的配置，不根据聊天自动填可执行命令。
- [ ] ToolPolicyEditor 展示 schema 和数据去向，默认为每次确认；永久 ALLOW_READ 明确显示作用于哪个 capability revision。ToolApprovalCard 展示名称/目标/规范化参数、过期状态和批准/拒绝，禁用旧 revision 与重复点击。工具进度、错误、取消和 unknown outcome 文案准确，原始结果折叠且不执行 HTML。
- [ ] 组件测试覆盖 secret 不回显/写入后清空、参数改动旧批准失效、模型 Key 不用于 MCP、注入文本只作文本、等待时切换设置不改旧卡、服务断开重连、过期/拒绝、键盘和窄屏。执行 test/typecheck/build 全通过与共同门禁：

```powershell
npm --prefix frontend run test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build
git add frontend/src/features/extensions frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/App.tsx frontend/src/features/chat/ChatTimeline.tsx frontend/src/styles.css docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务32): 增加Skills与MCP设置及工具确认界面"
```

## 任务 33：扩展端到端、恢复和使用文档

**依赖：** 32。
**创建：** `tests/e2e/test_extensions_workflow.py`、`frontend/e2e/extensions.spec.ts`、`docs/extensions.md`、`examples/skills/bulk-rnaseq-review/SKILL.md`、`examples/mcp/readonly_server.py`。
**修改：** `README.md`、`docs/workbench.md`、`docs/architecture.md`、`SECURITY.md`、`.github/workflows/ci.yml`、`scripts/check.ps1`、`tests/unit/test_check_script.py`。

- [ ] 写跨重启批准不重放的端到端测试。使用任务 29 真实 SDK fixture server、Mock 模型、临时 DB，记录 call count；等待批准时 kill/recreate 应使旧批准失效，调用已发出但结果未保存时状态必须 UNKNOWN，不能自动再发。浏览器测试固定只读 echo 示例：

```typescript
import { test, expect } from "@playwright/test";

test("extension settings explain transport choice", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("tab", { name: "MCP", exact: true }).click();
  await expect(page.getByRole("button", { name: "添加 MCP 服务" })).toBeVisible();
});
```

- [ ] 运行 `uv run --offline pytest tests/e2e/test_extensions_workflow.py -v -p no:cacheprovider` 和 `npm --prefix frontend run e2e -- extensions.spec.ts`；先记录演示/恢复集成缺口，再补齐，不用删断言获得通过。
- [ ] 完成可复制的本地示例 Skill 与只读 MCP server（使用任务 29 锁定 SDK），明确 Skills 只是说明、MCP 返回不是统计证据。文档写入绝对程序路径/argv/env refs/HTTP endpoint 配置步骤、连接和权限、禁用/清理、版本兼容、限额及取消不能回滚远端的语义。示例数据全部合成，凭据字段只用环境变量名称。
- [ ] 端到端覆盖 stdio/HTTP 两种 transport、Skill 显式/模型选择、调用确认与拒绝、只读授权 schema 变化、模型切换、超时/取消/重启、恶意输出、无 Key 工作台可打开。检查示例服务关闭后无遗留自己启动的子进程；旧 Streamlit 与 GEO/R 路径继续通过。自动浏览器审批仅针对本地合成 fixture，不访问真实账户工具。
- [ ] CI 固定 SDK/Node/lockfile，执行本地 fixture 测试；在完整门禁执行以下命令，记录实际数量和所有 skip，不把 HTTP 成功等同科学成功：

```powershell
uv run --offline pytest tests/e2e/test_extensions_workflow.py -v -p no:cacheprovider
npm --prefix frontend run e2e
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run --offline pre-commit run --all-files
```

- [ ] **31–33 整体复盘**检查单 Agent 边界、无任意执行、无自动下载软件、无密钥进入证据、统计审批未被绕过。文档记录已验证客户端版本、已支持 transport 和真实手工演示结果；更新下一步，不自行扩大到新统计方法。

```powershell
git add tests/e2e/test_extensions_workflow.py frontend/e2e/extensions.spec.ts docs/extensions.md examples/skills/bulk-rnaseq-review/SKILL.md examples/mcp/readonly_server.py README.md docs/workbench.md docs/architecture.md SECURITY.md .github/workflows/ci.yml scripts/check.ps1 tests/unit/test_check_script.py docs/superpowers/plans/2026-09-08-extensions.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务33): 完成扩展工具端到端验收与使用文档"
```

## 计划自检

规格 §2 由 28/32，§3 由 29，§4 由 30/32，§5 由 31，§6 由 30–32，§7 由 33 覆盖。真实模型和真实账号外部服务不作为自动验收前置；已有统计结果必须继续通过原确定性 QC。
