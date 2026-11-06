# Skills 与 MCP 本地扩展指南

本页描述 Task33 验证过的本地扩展路径。Skills 只提供说明文字，MCP 只提供经过策略和调用批准的工具；MCP 返回内容不是 DESeq2 统计证据，也不会改变原有分析审批。

## 安全边界和版本

- 当前实现保持单 Agent、本地单用户边界。模型不能写任意 Python、R、shell，也不能提供要执行的 MCP 命令；应用不会自动安装软件或使用 `npx -y` 下载程序。
- MCP Python SDK 固定为 `mcp==2.2.0`（见 `pyproject.toml` 与 `uv.lock`），支持 stdio 和 Streamable HTTP。旧 HTTP+SSE、OAuth、sampling、elicitation 和 roots 不在范围内。
- 每个 turn 最多 8 个 Skill/MCP 动作，活动时间最多 120 秒；连接和工具发现超时 10 秒，调用默认 60 秒、上限 300 秒，结果上限 2 MiB。批准卡 10 分钟过期且只能消费一次。
- 取消不能承诺回滚远端副作用；已发出但未保存结果会标记 `TOOL_OUTCOME_UNKNOWN`，不会自动重试。进程重启会撤销等待中的批准并将未完成 turn 标为中断失败。

## Skill 配置

在工作台的“设置”入口打开 Skills。根目录必须是绝对路径；应用只读取每个一级目录中的 `SKILL.md` 和该 Skill 内相对引用的 Markdown/文本文件，不跟随逃逸 symlink，不执行同目录脚本。入口文件最大 64 KiB，每轮注入最多 128 KiB，最多加载三个 Skill。

可复制的合成示例位于 `examples/skills/bulk-rnaseq-review/SKILL.md`。它只是审阅提示，不会执行分析。扫描后先检查组合 SHA-256，再显式启用；文件或引用变化会使旧启用状态失效，必须重新启用。禁用、删除目录或改换根目录后应重新扫描，并确认工作台显示的校验错误。

## MCP stdio

1. 启动本地应用并打开“设置”→“MCP”。
2. 选择 `stdio`，填写绝对 `executable`、逐项 `argv` 和固定工作目录。界面的 argv 文本框每行表示一个完整参数，因此包含空格的 Windows 路径不会被再次拆分。例如 executable 可填写 `C:\\Python312\\python.exe`，argv 两行分别填写 `C:\\repo with spaces\\examples\\mcp\\readonly_server.py` 和 `stdio`；不要填写 shell 字符串。
3. 如需凭据，只填写独立的环境引用名称；凭据值只在保存请求中发送，保存后输入框会清空。模型 Key 不会作为 MCP 凭据复用。
4. 新配置点击“添加 MCP 服务”；选择已有配置后表单会载入其当前 revision，修改后点击“保存 MCP 服务”。检查完整命令预览，再点击“连接”。连接会协商并显示协议版本、发现工具目录；服务断开后必须重新显式连接。

可复制 fixture：

```powershell
$python = (Get-Command python).Source
uv run python examples/mcp/readonly_server.py stdio
```

上面的 server 只读地回显合成文本，不读取数据文件、不启动子进程，也不产生统计结果。实际配置时将 `$python` 和示例脚本绝对路径分别放入 executable/argv；不要让聊天文本填充这些字段。

## Streamable HTTP

用户先在本地终端启动示例：

```powershell
$port = 8765
uv run python examples/mcp/readonly_server.py http $port
```

MCP 设置中选择 `Streamable HTTP`，填写完整 endpoint，例如 `http://127.0.0.1:8765/mcp`，确认页面显示的 host/port 与目标一致后保存，再连接。localhost 可使用明文 HTTP；其他主机必须使用 HTTPS。应用禁用重定向，不把 token 转发到第三方；凭据只保存独立 ref，不写入 SQLite、事件、checkpoint、manifest、日志或模型上下文。

## 权限、批准和清理

工具目录默认是 `CONFIRM`。只有用户明确审阅工具名称、目标、schema 和数据去向后，才可把只读工具改为 `ALLOW_READ`；schema、连接或 capability revision 改变会撤销旧权限和批准。`DENY` 工具不会提供给模型。

每次 `CONFIRM` 调用都会在对话中显示目标、规范化参数、参数 hash、capability revision 和过期时间。只有显式点击批准或拒绝才会继续；过期、旧 revision、参数改变、重复点击或重启后的旧卡都会失败。原始 MCP 文本在界面中作为不可信的折叠文本显示，不执行 HTML，也不改变 run 状态。

完成演示后点击“断开”，再停止示例 server；应用只清理自己启动的 stdio 子进程，不终止用户预先存在的进程。删除配置会停用服务但保留审计记录。确认端口、`python` 子进程和工作区临时目录均已清理。

## 统计与证据边界

Skill 不能替代数据校验或人工分析审批。MCP 的“read-only”声明只是展示信息，不会自动获得执行权限；MCP 结果不能冒充 counts、QC、DESeq2 结果或 manifest artifact。bulk RNA-seq 统计仍必须经过固定工具、原有计划 revision/hash、R 执行和确定性 QC。真实模型 API、真实 MCP 账户和真实凭据联调由用户后续在本地明确配置，不是自动验收前置。
