# Task52 安全推送与可共享安装计划

**授权：** 用户要求将项目推送到其 GitHub bio-agent，避免上传敏感信息，并让其他使用者配置自己的 API；直接在本会话完成，不重复请求已授予的发布授权。

**目标：** 验证完整待推历史、修复新用户首启、提供清晰个人 API 配置说明，并安全更新远端默认分支。

**架构：** 保留系统凭据库与本地环境配置，不导出本机 profile、数据、聊天或模型。沿用 clone 获取真实 Git provenance，不伪造 ZIP 的提交身份。统计和模型执行契约不变。

**文件：** scripts/start-workbench.ps1、tests/unit/test_workbench_start.py、README.md、docs/getting-started.md、docs/workbench.md、.env.example、.gitignore、frontend/src/features/models/ModelSettings.tsx、本计划、docs/reviews/2026-11-06-task52-release.md、docs/progress/current-state.md 与原型计划中的本机路径清理。

- [x] 对旧 PowerShell 启动脚本跑失败测试，覆盖项目 R 库传递、R 包失败和 clone 检查。
- [x] 修复启动脚本，更新 clone、构建、R 恢复和个人 API 说明。环境模板只供本机按需使用。
- [x] 校验 Gitleaks 8.30.1 官方 checksum，并扫描完整本地历史。核对敏感运行文件路径。
- [x] 独立 Windows 克隆锁定安装、空配置启动、保存 profile 与缺 Key 验证通过。完成 Mock 模型和真实 R 的受审批链路、相关 pytest、前端、R 及静态检查。
- [x] 记录验证和局限，按本计划暂存任务文件并准备快进发布。发布提交使用已清理的任务树及现有远端 `main` 父提交。最终历史和跟踪树扫描、远端 SHA 与 CI 以发布执行记录为准。

**验收命令：** `uv run --no-sync --offline pytest tests/unit/test_workbench_start.py tests/unit/models tests/integration/api/test_model_profiles.py -q`。前端运行 `npm --prefix frontend run test -- --run`、`typecheck` 和 `build`。Python 运行 Ruff 和 `mypy src/bioagent`。Git 提交前通过 `pre-commit run --all-files` 和 `git diff --cached --check`。干净克隆和安全扫描记录写入父验收。

- [x] 公开前复现并修复基础安装下的 CI 套件选择和 PDF 可选依赖类型检查，复跑启动与配置相关测试。公开候选从已清理历史构建，原私有记录独立保留。
