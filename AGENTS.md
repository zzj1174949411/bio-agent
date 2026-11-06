# Bio-Agent 仓库协作规则

## 项目目标

本仓库用于构建一个可复现、可审计、需要人工审批的生物信息学 Agent。MVP 只实现 bulk RNA-seq 双组 DESeq2 分析；single-cell、long-read 和多 Agent 编排不属于当前范围。

用户正在通过这个项目系统学习 Agent 开发。实现功能时应说明关键设计理由、测试目的和重要取舍，但不要用教学性扩展改变已批准的 MVP 范围。

## 权威资料

开始工作前按顺序阅读：

1. `docs/superpowers/specs/2026-08-15-bio-agent-design.md`：已批准架构与范围。
2. `docs/superpowers/plans/2026-08-15-bio-agent-mvp.md`：逐任务实施步骤和验收条件。
3. `docs/progress/current-state.md`：开发分支上的最新进度、验证结果和下一步。
4. `git status --short --branch` 与 `git log -5 --oneline`：实际仓库状态。

如果进度文件与 Git 或测试结果冲突，以 Git 和测试证据为准，并先修正进度文件。

## 工作区与分支

- 功能开发分支为 `agent/bio-agent-mvp`。
- 项目本地 worktree 默认为 `.worktrees/bio-agent-mvp`。
- 如果当前位于 `main`，且上述 worktree 存在，不得在 `main` 实现功能；应切换到该 worktree。
- 每次只执行实施计划中的 1 个编号任务。不要把计划中的单个复选框拆成独立会话。
- 每完成 3 个编号任务，暂停并进行一次整体复盘。

## 会话开始协议

1. 确认当前分支和 worktree 路径。
2. 阅读权威资料及最新进度。
3. 检查工作区是否存在用户未提交的改动；不得覆盖或删除这些改动。
4. 只领取 `current-state.md` 指定的下一任务，并复核该任务的依赖与验收命令。
5. 在修改实现代码前，先编写并运行计划要求的失败测试。

## 实施和安全约束

- Python 命令统一使用 `uv run`，R 命令统一使用 `Rscript`。
- LLM 只负责理解、规划和解释；统计计算与校验必须由确定性代码完成。
- 不执行模型、用户输入或上传文件提供的任意 Python、R 或 shell 代码。
- 外部模型测试使用 Mock；不得在测试、日志、checkpoint、manifest 或 Git 中写入 API Key。
- 不提交 `.env`、运行数据、分析产物或 `BIO_AGENT_ARCHITECTURE_MEMORY.md`。
- 不使用 `git add .`；只暂存当前任务明确列出的文件，以及计划和进度状态文件。
- 不跳过计划规定的测试、静态检查或 `git diff --cached --check`。

## 会话结束协议

结束一个编号任务前必须：

1. 运行该任务指定的测试和静态检查，记录真实结果。
2. 更新实施计划中的复选框。
3. 更新 `docs/progress/current-state.md`，写明完成内容、验证结果、阻塞项和下一步。
4. 使用包含任务编号的明确 commit message 提交；不得混入其他任务。
5. 再次确认 `git status --short --branch`，把未提交状态如实留给下一会话。

未经验证，不得声称任务完成。
