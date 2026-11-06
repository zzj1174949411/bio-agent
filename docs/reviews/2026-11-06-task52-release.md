# Task 52 安装、个人 API 与发布验收

## 使用者安装

- 从 GitHub 默认分支克隆。Windows 启动脚本检查 checkout、前端构建、端口和项目 R 包，并向 uvicorn 传递恢复后的 R 库。分析 manifest 使用真实 Git 提交。
- 工作台可空配置启动。使用者在设置里保存自己的 DeepSeek、OpenAI 兼容或 Ollama 配置。DeepSeek 示例使用官方当前模型 ID `deepseek-flash`。系统凭据库不可用时，指南说明本地 DeepSeek 环境配置。
- 独立 Windows 克隆按 `uv.lock` 安装 124 个包（含开发工具），按 npm 锁文件安装 110 个包并构建前端。uv 离线首次缺缓存，联网按同一锁文件完成。
- Windows 恢复时，当前 CRAN 的锁定版 `RcppArmadillo 15.4.2-1` 二进制返回 404，renv 安装该包失败。用 Posit 2026-08-15 快照的同版本 Windows x64 二进制引导后，原锁文件恢复退出 0。实际可加载的 79 个包版本与锁文件逐一相同。Windows 本次获得的 Bioconductor 二进制有 16 条仓库标签为 `bioc-release.r-universe.dev`，严格 `renv::status()` 因来源标签报不同步。保留标签和锁文件原值。Rtools45 与固定快照的安装说明见 [首次运行](../getting-started.md)。

## 验证

- 用独立副本的旧 PowerShell 启动脚本回跑新断言，3 项按预期失败。修复后 5 项通过，覆盖 R 库传递、R 失败、端口已占用和 clone 检查。
- 干净克隆的启动及模型相关 pytest 共 55 项通过。实际 Windows PowerShell 启动在独立回环端口返回工作台 HTTP 200。新数据库中没有已配置凭据，能新建模型，探测在缺 Key 时返回 `MODEL_NOT_CONFIGURED`。Mock 测试验证凭据保存、脱敏、探测和删除。
- 干净克隆真实 R/DESeq2 两项端到端测试通过，覆盖有无效应量收缩、明确审批、报告、manifest 和产物哈希。R testthat 52 个断言通过。
- 前端 Vitest 23 个文件、55 项测试通过，类型检查和构建通过。npm 生产依赖审计报告 0 条，包含开发依赖的安装审计提示 5 条。锁文件保持原版本。
- Ruff 和 mypy（114 个源文件）通过。提交门禁及远端 CI 状态分别以 Git 记录与 GitHub Actions 为准。

## 发布边界

- 校验官方 Gitleaks 8.30.1 下载包 SHA-256。扫描本地 99 个既有提交，0 个密钥匹配。历史路径检查涵盖环境文件、SQLite、运行目录、研究数据、证书和私钥。
- 本地历史包含工作站路径和会话标识。清理源码快照后，以已有远端 `main` 为父创建快进发布提交。原开发历史留在本地，发布使用 GitHub no-reply 地址。推送前对最终提交历史和导出的跟踪文件再次扫描。
- `.env`、运行数据、数据库、用户凭据、本机模型及检查产物由忽略规则和发布树检查隔离。保留用户原有 `renv/activate.R` 改动的 SHA-256。此次使用 Mock 与无密钥启动，未发生模型服务请求。
