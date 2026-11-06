# Skills 与 MCP 扩展设计

**状态：** 属于用户已确认的工作台第三阶段；依赖任务 27。
**实现计划：** [任务 28–33](../plans/2026-09-08-extensions.md)。

## 1. 能力与边界

Skills 是可启用的领域说明，MCP 是可配置的工具来源。二者通过同一个 ToolGateway 服务于已有单 Agent；不允许模型写任意命令，不允许工具返回内容充当系统规则，也不允许通用 MCP 结果直接冒充已验证的 DESeq2 产物。

首版支持用户已安装的本地 Skill 目录、MCP stdio 和 Streamable HTTP。支持导入/启停/查看，不提供自动安装市场、OAuth 授权浏览器、旧 HTTP+SSE transport、MCP sampling/elicitation/roots 暴露或通用 Python/R shell 工具。新增统计工具必须拥有独立 ToolSpec、输入输出校验和审批，不能只因 MCP 宣称 readOnly 就获执行权限。

## 2. Skills

从后端配置的 skill 根目录按一层子目录发现 `SKILL.md`；首选项目内 `.bioagent/skills`，根目录由用户设置且后端解析为绝对路径。不得跟随逃逸 symlink；只读取 Markdown/文本引用，不执行同目录脚本。引用使用相对路径，最大三层，禁止父路径逃逸和远程加载。

frontmatter 必需 `name`、`description`，可选 `allowed_tools`（命名空间工具名列表）。一个 SKILL.md 最大 64 KiB，单次注入内容最多 128 KiB；UTF-8 校验失败显示 `SKILL_INVALID`。allowed_tools 是请求的上限，不是授权，和用户启用工具集合取交集。

SkillRecord：id、name、description、root_id、relative_path、sha256、enabled、requested_tools。sha256 为入口与已解析文本引用的组合 hash；任一引用变化也使授权快照失效。只把启用 Skill 的 name/description 提供给能力选择器；用户可显式附加 Skill，模型也可请求加载已启用 Skill。每轮最多加载三项。文件 hash 改变后需重新展示变更并启用，旧 turn 使用已存储的快照，不悄悄换指令。

设置页显示来源、内容预览、hash、启停及校验错误；消息和 manifest agent_context 保存用到的 Skill 名称/hash。Skill 文本不能包含凭据模板展开；不将本机其他工具的全局 skill 目录自动导入。

## 3. MCP 配置与生命周期

McpServerConfig：id、label、transport、enabled、revision、stdio 或 http 配置。配置更改只影响新 turn；连接配置、工具 schema 和用户权限 hash 一起形成 capability revision。

- stdio：绝对 executable、参数数组、固定工作目录、允许的 env 引用；`shell=False`。用户点击“连接”前显示完整程序/参数/目录。不能从自然语言、Skill 或数据库文件生成 executable，不自动 `npx -y` 下载程序。
- HTTP：用户配置完整 http(s) endpoint，localhost HTTP 可用，其他地址要求 HTTPS。首次连接显示精确 host/port；重定向默认禁用，token 只发给配置目标，不向第三方转发。凭据沿用模型模块的独立 keyring 引用命名空间，不能通用透传模型 Key。
- 主进程拥有连接生命周期。连接和 list_tools 超时 10 秒、单次 call 默认 60 秒、最大 300 秒；最大 8 个连接、返回体 2 MiB。退出关闭本应用启动的子进程树，不杀用户预先存在的服务。
- SDK 客户端封装在 `extensions/mcp_client.py`，隔离协议变化；使用正式发布版本并写入 uv.lock。协商后的协议版本记录到连接信息，不能手写未经验证的新协议。

## 4. 工具目录与授权

`ToolDescriptor`：qualified_name、server_id、input_schema、schema_hash、description、policy。名称形式 `mcp.<server_id>.<tool_name>`；碰撞拒绝，不覆盖内置工具。

政策只来自本地用户配置：DENY / CONFIRM / ALLOW_READ。初始为 CONFIRM；MCP 自报的 readOnly/destructive 仅供展示。用户允许某工具长期 ALLOW_READ 时必须审阅名称、server 目标、schema 和可能读取/外发的数据；能力 hash 变化撤销先前允许。

待批准调用绑定 conversation、turn、server revision、tool schema hash、规范化参数 hash、过期时间（10 分钟）和随机 approval_id。修改参数、连接或 schema 后旧批准 409；批准只能执行一次。DENY 工具不发给模型。内置分析审批始终走原 AnalysisPlan，不受 MCP 工具政策覆盖。

调用前本地 JSON Schema 校验，调用后检查 isError/结构化结果 schema，捕获超时/取消/未知结果。未知结果不自动重试。收到工具“已完成分析”文本不改变 run 状态。工具返回文本作为不可信数据，只有明确选择的小段内容进入下一模型轮次。

## 5. 调度和审计

每个工具调用使用独立 call_id，事件记录请求时间、namespace、revision、schema/参数 hash、决策、开始/结束、错误码。参数内容按敏感字段策略脱敏；密钥只由连接客户端注入 headers/env，从不写入事件或模型上下文。

ToolGateway 连接内置 geo.lookup/import、run.plan/status/artifacts 与启用的 MCP 工具。analysis.approve 不是可提供给模型的工具。每轮沿用 8 次动作和 120 秒活动预算；MCP 超时最大值不得超过 turn 剩余预算。

取消等待批准的 turn 使批准失效；取消进行中的 MCP 请求尽力发送取消并停止本地等待，记录 `TOOL_CANCELLED` 或 `TOOL_OUTCOME_UNKNOWN`，不承诺远端副作用已回滚。重启未完成调用标记未知，不自动重发。

## 6. API 与工作台

前缀 `/api/v1/extensions`：

| 端点 | 行为 |
| --- | --- |
| GET/PATCH /skill-roots | 列表 / 用户修改扫描根；模型动作不可调用 |
| GET /skills；POST /skills/rescan | 脱敏列表 / 扫描用户配置根 |
| GET /skills/{id}；PATCH /skills/{id} | 文本预览 / `{enabled,expected_hash}` |
| GET/POST /mcp/servers | 列表 / 新建配置 |
| PATCH/DELETE /mcp/servers/{id} | 更新/停用删除配置，不删审计记录 |
| PUT/DELETE /mcp/servers/{id}/credential | 独立凭据存储 |
| POST /mcp/servers/{id}/connect；POST /disconnect | 显式连接/断开 |
| GET /tools；PATCH /tools/{qualified_name} | 工具列表 / 本地 policy |
| POST /calls/{id}/decision | `{approval_id,decision,capability_revision,arguments_hash}` |

设置页有 Skills、MCP、模型三个入口。对话中展示待授权卡、工具名/目标/参数、执行状态、摘要和错误。不得把 JSON token 直接放进 URL；流式事件沿用 A 阶段 SSE。

## 7. 验收与任务映射

28 Skills 加载/hash/启停；29 stdio/HTTP 客户端和假 server；30 schema、policy 与一次性批准；31 对话工具循环；32 设置与审批卡；33 端到端/恢复/文档。

自动测试在本地启动无外部网络的 fixture MCP server，覆盖两种 transport、工具发现和调用；schema 变化、注入文本、伪造 readonly、过期批准、不同参数、取消、服务断开和超大结果均有失败用例。模型调用 Mock；不能用真实账号服务作 CI 依赖。真实手工验收仅连接明确选定的本地只读 fixture 工具。

## 8. 依据

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP 客户端](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/index.md)
- [已批准工作台基础设计](2026-09-08-workbench-design.md)

授权策略、限额与 Skill 格式兼容范围由本项目定义，不声称实现任意 Agent 产品的完整插件生态。
