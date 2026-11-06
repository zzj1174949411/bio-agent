# 安装与首次运行

安装 Git、uv、Node.js 22.12+ 和 R 4.5.2，并确保相应命令在 PATH 中。uv 管理 Python 3.12，renv 按锁文件恢复 Bioconductor 3.22 和 DESeq2 1.50.2 等 R 包。首次安装需要访问 GitHub、PyPI、npm、CRAN 和 Bioconductor，R 包可能需要编译。[R 依赖锁文件](../renv.lock)

通过 `git clone` 下载。分析 manifest 会记录 Git 提交，GitHub 的源码 ZIP 缺少这项信息。

## Windows（PowerShell）

安装 uv，并重新打开 PowerShell 使 PATH 生效。命令来自 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)：

```powershell
winget install --id=astral-sh.uv -e
```

下载并启动 [CRAN R 4.5.2 安装包](https://cran.r-project.org/bin/windows/base/old/4.5.2/)；以下使用默认安装目录：

```powershell
Invoke-WebRequest https://cran.r-project.org/bin/windows/base/old/4.5.2/R-4.5.2-win.exe -OutFile "$env:TEMP/R-4.5.2-win.exe"
Start-Process -FilePath "$env:TEMP/R-4.5.2-win.exe" -Wait
$env:PATH = "C:\Program Files\R\R-4.5.2\bin;" + $env:PATH
Rscript --version
```

R 包需要源码编译时，安装 [Rtools45](https://cran.r-project.org/bin/windows/Rtools/rtools45/rtools.html)，使用官方页面的安装包及默认目录。自定义 R 安装目录时，相应调整 PATH。每个启动 API 的新终端都需要可找到正确版本的 `Rscript`。

```powershell
git clone https://github.com/zzj1174949411/bio-agent.git
Set-Location bio-agent
uv python install 3.12
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
Rscript -e "renv::restore(prompt = FALSE)"
powershell -ExecutionPolicy Bypass -File scripts/start-workbench.ps1
```

首次从项目目录运行 Rscript 时，`.Rprofile` 使用提交的 `renv/activate.R` 引导安装项目所需 renv。若自动引导受网络策略阻挡，先按网络错误修复源或代理，再重新执行恢复。不要通过全局更新包来绕过锁文件。

Windows x64 如果在恢复 `RcppArmadillo 15.4.2-1` 时遇到当前 CRAN 二进制不可用，且尚未配置 Rtools45，可从 Posit 的固定日期快照装入同版本二进制，再继续恢复。以下命令在仓库根目录运行。[Posit 二进制包说明](https://packagemanager.posit.co/__docs__/admin/serving-binaries.html)

```powershell
Rscript -e "f <- file.path(tempdir(), 'RcppArmadillo_15.4.2-1.zip'); download.file('https://packagemanager.posit.co/cran/2026-08-15/bin/windows/contrib/4.5/RcppArmadillo_15.4.2-1.zip', f, mode='wb'); lib <- renv::paths[['library']](); install.packages(f, repos=NULL, type='win.binary', lib=lib); stopifnot(packageDescription('RcppArmadillo', lib.loc=lib, fields='Version') == '15.4.2-1'); renv::restore(prompt=FALSE)"
```

启动脚本会检查项目 R 包并把库路径传给分析子进程。端口 8000 已占用时可追加 `-Port 8010`，随后打开对应地址。

## Linux（Ubuntu 24.04，Bash）

安装 uv 和 Python。其他发行版需要替换系统依赖安装命令，见 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
```

下面从 [CRAN R 4.5.2 源码](https://cran.r-project.org/src/base/R-4/) 安装到用户目录，避免系统仓库的 R 版本与锁文件不同。编译选项与依赖依据 [R 安装手册](https://cran.r-project.org/doc/manuals/r-release/R-admin.html)，此命令用于无桌面的分析服务；安装系统编译依赖需要 sudo 权限：

```bash
sudo apt-get update
sudo apt-get install -y build-essential gfortran pkg-config curl git \
  libreadline-dev libpcre2-dev libcurl4-openssl-dev libssl-dev libxml2-dev \
  zlib1g-dev libbz2-dev liblzma-dev libicu-dev libpng-dev libjpeg-dev \
  libtiff-dev libcairo2-dev libxt-dev libdeflate-dev libzstd-dev libuv1-dev
mkdir -p "$HOME/.local/src"
cd "$HOME/.local/src"
curl -fLO https://cran.r-project.org/src/base/R-4/R-4.5.2.tar.gz
tar -xzf R-4.5.2.tar.gz
cd R-4.5.2
./configure --prefix="$HOME/.local/R/4.5.2" --with-x=no --with-tcltk=no
make -j2
make install
export PATH="$HOME/.local/R/4.5.2/bin:$PATH"
Rscript --version
```

确认配置结果包含 Cairo/PNG 支持，以便生成 PNG。已安装 R 4.5.2 时可跳过编译，直接检查版本。

```bash
cd "$HOME"
git clone https://github.com/zzj1174949411/bio-agent.git
cd bio-agent
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
Rscript -e 'renv::restore(prompt = FALSE)'
export R_LIBS="$(Rscript -e 'cat(renv::paths$library())' | tail -n 1)"
Rscript -e 'stopifnot(as.character(getRversion()) == "4.5.2"); library(DESeq2); library(apeglm); stopifnot(capabilities("png"))'
uv run uvicorn bioagent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

## 配置模型

启动后打开本地工作台，在“设置 → 模型与 API → 新模型”填写名称、接口协议、API Base URL、模型 ID 和自己的 API Key。以 DeepSeek 为例，选择 DeepSeek 协议，Base URL 填 `https://api.deepseek.com`，模型填 `deepseek-flash`。保存后点“探测连接”，再回到聊天输入区选择该模型。OpenAI 兼容服务使用服务商提供的地址与模型，Ollama 的 Key 留空。页面设置即时生效，密钥存入系统凭据库。[本地工作台](http://127.0.0.1:8000/) · [模型配置说明](../README.md#模型与-api-配置)

Linux 桌面可使用已解锁的 Secret Service 或 KWallet。系统凭据库不可用时，可为 DeepSeek 使用本机 `.env`，重启后在工作台选 `Environment / deepseek`。旧 Streamlit 和无 profile 的 API 也使用这组配置。已有 `.env` 时用编辑器更新，首次使用可从示例复制。[环境模板](../.env.example)

```dotenv
BIOAGENT_LLM_PROVIDER=deepseek
BIOAGENT_DEEPSEEK_API_KEY=
BIOAGENT_DEEPSEEK_BASE_URL=https://api.deepseek.com
BIOAGENT_DEEPSEEK_MODEL=deepseek-flash
```

Key 填在本地空值处，不要放进命令历史、截图或提交。模型与请求方式参照 [DeepSeek 官方文档](https://api-docs.deepseek.com/)。没有 Key 时可先按 [演示指南](demo.md) 创建固定 Mock Planner 工厂；普通应用不会自动降级为 Mock。

Ollama 为可选 provider。先依照 [官方快速开始](https://docs.ollama.com/quickstart) 安装并启动本地服务，然后运行 `ollama pull qwen3:8b`，将 `.env` 改为：

```dotenv
BIOAGENT_LLM_PROVIDER=ollama
BIOAGENT_OLLAMA_BASE_URL=http://localhost:11434
BIOAGENT_OLLAMA_MODEL=qwen3:8b
```

该配置不保证所选模型可靠遵循计划 schema；仍需审阅计划。项目自动测试使用 Mock，不下载模型或调用真实服务。

旧 Streamlit 可在 API 已启动后另开终端运行：

```text
uv run streamlit run ui/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

浏览 [Streamlit](http://localhost:8501)、[Swagger](http://localhost:8000/docs)、[health](http://localhost:8000/health) 与 [ready](http://localhost:8000/ready)。端口改变时，在 `.env` 同步设置 `BIOAGENT_API_BASE_URL` 并重启 UI。`--reload` 适合本地开发；分析执行中不要修改服务源码，重启会中断内存队列。

## 首次分析

1. 新建项目和聊天，选择已配置的模型。点输入框“＋ → 导入分析数据”，选择示例 counts 和 metadata。[示例 counts](../tests/fixtures/counts_deseq2.csv) · [示例 metadata](../tests/fixtures/metadata_deseq2.csv)
2. 发送“使用 DESeq2 比较 AD 相对 Control，分组列 condition”。核对方案中的组别、方向和阈值，确认后批准执行。
3. 完成后在聊天里打开 QC、结果表、图和报告。需要离线保存时，按演示指南下载关联文件和 manifest。[演示下载流程](demo.md)

只有一份原始 counts 时，可在“＋ → 上传单表达矩阵”指定样本和分组。也可通过 GEO 查找公开矩阵。[单矩阵指南](single-matrix.md) · [GEO 指南](geo.md)

counts 必须是有限、非负、R integer 范围内的整数。样本集合须完全匹配，选定分组列恰好两个水平且每组至少 2 个样本。metadata 的其他列不会自动加入设计。

## 运行检查

Windows 在上述环境中运行全量门禁：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv run pre-commit run --all-files
```

Linux 可安装 PowerShell 后执行 `pwsh -File scripts/check.ps1`，或用以下等价分步命令；`R_LIBS` 应已按前文导出：

```bash
uv sync --frozen --dev
uv run ruff check .
uv run mypy src
uv run pytest tests/unit tests/integration tests/evals -k 'not test_real_deseq2_runner_preserves_ad_vs_control_direction' -q
Rscript -e 'renv::restore(prompt = FALSE)'
Rscript -e 'stopifnot(isTRUE(renv::status()$synchronized))'
Rscript r/tests/testthat.R
uv run pytest tests/integration/test_deseq2_runner.py::test_real_deseq2_runner_preserves_ad_vs_control_direction tests/e2e -v
uv run pre-commit run --all-files
```

## 排错

| 现象 | 下一步 |
| --- | --- |
| UI 提示无法连接 API | 确认 API 终端仍运行、端口和 `BIOAGENT_API_BASE_URL` 一致，恢复服务后刷新 |
| `/health` 成功而 `/ready` 失败 | 检查本地 Key 配置、Rscript PATH、Git checkout 与运行目录；readiness 不验证真实模型联网 |
| 创建计划失败 | 确认模型名、凭据、服务可达性与目标范围；无 Key 的演示使用专门 Mock 工厂 |
| `SECRET_STORE_UNAVAILABLE` | 解锁系统凭据库后重新保存，或用本机 `.env` 的 DeepSeek 环境配置 |
| R 找不到 DESeq2/apeglm | 在根目录重新恢复 renv，并在启动 API 的同一终端导出 `R_LIBS` |
| R 包版本不一致 | 检查 `Rscript --version` 与 `renv::status()`；对照当前 attempt 的 `session_info.txt` |
| 运行失败并返回 `REPORT_FAILED` | 报告与当前运行的身份、计划、QC 或产物证据不一致，或生成/写入失败；保留文件，检查对应 attempt 与 manifest，不将已有统计文件视作完整成功运行 |
| 上传返回 413 / 408 | 按 [默认上传限制](../SECURITY.md#上传限制) 缩小输入；不支持直接上传大型 FASTQ |
| 点击取消后 R 仍占用资源 | 取消是协作式；等待当前 R 返回或达到固定超时，不把取消当作立即杀进程 |

安装命令按官方资料编写；各平台实际验收状态和已知环境限制以 [当前进度](progress/current-state.md) 为准。
