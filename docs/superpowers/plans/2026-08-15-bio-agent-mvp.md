# Bio-Agent MVP 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 8 周内实现一个可公开演示、可测试、可审计的 bulk RNA-seq 双组 DESeq2 有监督 Agent。

**架构：** FastAPI 接收数据和任务，LangGraph 生成强类型计划并在执行前中断等待审批；获批后由 Job Runner、Execution Controller 和受控 R/DESeq2 Runner 完成确定性计算。SQLite 只保存工作流 checkpoint，科研运行历史由独立 artifact 目录和 manifest 保存，Streamlit 只通过 HTTP API 使用后端。

**技术栈：** Python 3.12、uv、Pydantic、LangGraph、LangChain OpenAI/Ollama、FastAPI、Streamlit、SQLite、R 4.5、DESeq2、renv、pytest、testthat、ruff、mypy、GitHub Actions。

---

## 0. 执行约定

- 从 `main` 创建并使用分支 `agent/bio-agent-mvp`。
- 每个任务只提交该任务列出的文件，以及本计划和 `docs/progress/current-state.md` 两个状态文件；不使用无差别的 `git add .`。
- Python 命令统一使用 `uv run`，R 命令统一使用 `Rscript`。
- 每个实现步骤遵循测试失败、最小实现、测试通过的顺序。
- 所有外部 API 测试使用 Mock，不把 DeepSeek Key 放入 CI。
- `BIO_AGENT_ARCHITECTURE_MEMORY.md` 是本地未跟踪参考文件，不加入任何提交。
- 每次 commit 前运行该任务的定向测试和 `git diff --cached --check`。

## 1. 目标文件结构与职责

```text
bio-agent/
├── .github/workflows/ci.yml                 # Python、R 和端到端 CI
├── docs/                                    # 架构、计划和使用文档
├── evals/cases.yaml                         # 固定 Agent 行为评测集
├── r/deseq2/
│   ├── functions.R                          # DESeq2 纯函数
│   └── run.R                                # JSON 参数驱动的唯一入口
├── r/tests/testthat/test-deseq2.R           # R 输入输出契约测试
├── src/bioagent/
│   ├── __init__.py                          # 包版本
│   ├── api/
│   │   ├── app.py                           # FastAPI 工厂
│   │   ├── dependencies.py                  # 服务依赖装配
│   │   └── routes.py                        # Dataset、Run、Artifact API
│   ├── artifacts/
│   │   ├── manager.py                       # 安全目录与文件哈希
│   │   └── manifest.py                      # 科研 provenance 模型与写入
│   ├── config.py                            # 环境配置
│   ├── datasets/
│   │   ├── parser.py                        # CSV/TSV 解析
│   │   ├── repository.py                    # dataset ID 到安全路径的映射
│   │   └── validator.py                     # 确定性数据校验
│   ├── domain/
│   │   ├── plans.py                         # 强类型分析计划
│   │   ├── qc.py                            # QC 规则与严重级别
│   │   └── runs.py                          # Run、Attempt 和审批状态
│   ├── execution/
│   │   ├── controller.py                    # 审批、幂等与工具调度
│   │   ├── job_runner.py                    # 本地单 Worker 抽象
│   │   └── r_runner.py                      # shell=False 的 Rscript 调用
│   ├── llm/
│   │   ├── factory.py                       # DeepSeek/Ollama 模型工厂
│   │   └── planner.py                       # 结构化计划生成
│   ├── reporting/
│   │   ├── generator.py                     # 确定性 HTML 报告
│   │   └── templates/report.html.j2         # 报告模板
│   ├── storage/
│   │   ├── checkpoint.py                    # LangGraph SQLite checkpointer
│   │   └── runs.py                          # run.json 状态仓库
│   ├── tools/
│   │   ├── registry.py                      # Tool Registry 加载与校验
│   │   └── deseq2.py                        # DESeq2 Python 工具适配器
│   └── workflow/
│       ├── graph.py                         # LangGraph 装配
│       ├── nodes.py                         # 单职责节点
│       └── state.py                         # JSON 可序列化状态
├── tests/
│   ├── e2e/test_bulk_workflow.py            # 完整 Mock LLM 工作流
│   ├── fixtures/                            # 小型固定数据
│   ├── integration/                         # API、R 和 LangGraph 测试
│   └── unit/                                # Python 单元测试
├── tool_specs/deseq2.yaml                   # DESeq2 能力、环境和产物契约
├── ui/streamlit_app.py                      # 纯 HTTP 客户端
├── .env.example                             # 无密钥配置示例
├── .gitignore                               # 环境、运行产物和密钥排除
├── .python-version                          # Python 3.12
├── pyproject.toml                           # 依赖和工具配置
├── README.md                                # 求职作品主页
├── renv.lock                                # R 依赖锁
└── uv.lock                                  # Python 依赖锁
```

## 2. 任务清单

### 任务 0：建立跨会话记忆与隔离工作区

**文件：**

- 创建：`.gitignore`
- 创建：`AGENTS.md`
- 创建：`docs/progress/current-state.md`
- 更新：`docs/superpowers/plans/2026-08-15-bio-agent-mvp.md`

- [x] **步骤 1：忽略项目本地 worktree 和本地架构参考文件**
- [x] **步骤 2：创建 `agent/bio-agent-mvp` 分支和 `.worktrees/bio-agent-mvp` worktree**
- [x] **步骤 3：建立会话开始、任务执行和会话结束协议**
- [x] **步骤 4：记录当前环境、验证结果和下一任务**

### 任务 1：建立 Python 3.12 项目与质量门禁

**文件：**

- 创建：`.python-version`
- 创建：`pyproject.toml`
- 扩展：`.gitignore`
- 创建：`.env.example`
- 创建：`README.md`
- 创建：`src/bioagent/__init__.py`
- 创建：`tests/unit/test_package.py`
- 生成：`uv.lock`

- [x] **步骤 1：安装 uv 并准备 Python 3.12**

运行：

```powershell
winget install --id=astral-sh.uv -e
uv python install 3.12
uv python pin 3.12
```

预期：`uv python find 3.12` 返回 uv 管理的 Python 3.12 路径，`.python-version` 内容为 `3.12`。

- [x] **步骤 2：创建先失败的包导入测试**

创建 `tests/unit/test_package.py`：

```python
import bioagent


def test_package_exposes_version() -> None:
    assert bioagent.__version__ == "0.1.0"
```

运行：`uv run pytest tests/unit/test_package.py -v`

预期：FAIL，报错无法导入 `bioagent`。

- [x] **步骤 3：创建项目配置与最小包**

`pyproject.toml` 使用以下核心配置：

```toml
[project]
name = "bio-agent"
version = "0.1.0"
description = "A reproducible human-in-the-loop bioinformatics agent"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.116,<1",
  "httpx>=0.28,<1",
  "jinja2>=3.1,<4",
  "langchain-ollama>=1,<2",
  "langchain-openai>=1,<2",
  "langgraph>=1,<2",
  "langgraph-checkpoint-sqlite>=3,<4",
  "pandas>=2.3,<3",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "python-multipart>=0.0.20,<1",
  "pyyaml>=6,<7",
  "streamlit>=1.48,<2",
  "uvicorn>=0.35,<1",
]

[dependency-groups]
dev = [
  "mypy>=1.17,<2",
  "pandas-stubs>=2.3,<3",
  "pre-commit>=4.3,<5",
  "pytest>=8.4,<9",
  "pytest-cov>=6.2,<7",
  "ruff>=0.12,<1",
  "types-PyYAML>=6,<7",
]

[build-system]
requires = ["uv_build>=0.11.32,<0.12"]
build-backend = "uv_build"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["bioagent"]
```

创建 `src/bioagent/__init__.py`：

```python
__version__ = "0.1.0"
```

创建最小 `README.md`：

```markdown
# Bio-Agent

A reproducible, human-in-the-loop bioinformatics agent for bulk RNA-seq analysis.

The MVP design is documented in `docs/superpowers/specs/2026-08-15-bio-agent-design.md`.
```

`.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.py[cod]
runs/
data/
checkpoints.sqlite*
.Rproj.user/
renv/library/
```

`.env.example`：

```dotenv
BIOAGENT_LLM_PROVIDER=deepseek
BIOAGENT_DEEPSEEK_API_KEY=
BIOAGENT_DEEPSEEK_BASE_URL=https://api.deepseek.com
BIOAGENT_DEEPSEEK_MODEL=deepseek-v4-flash
BIOAGENT_OLLAMA_BASE_URL=http://localhost:11434
BIOAGENT_OLLAMA_MODEL=qwen3:8b
BIOAGENT_API_BASE_URL=http://localhost:8000
BIOAGENT_RUNS_DIR=runs
BIOAGENT_DATA_DIR=data
BIOAGENT_CHECKPOINT_DB=checkpoints.sqlite
BIOAGENT_RSCRIPT=Rscript
```

- [x] **步骤 4：锁定依赖并验证包**

运行：

```powershell
uv lock
uv sync --dev
uv run pytest tests/unit/test_package.py -v
uv run ruff check .
uv run mypy src
```

预期：测试 1 PASS，ruff 和 mypy 退出码均为 0。

- [x] **步骤 5：Commit**

```powershell
git add .python-version pyproject.toml uv.lock .gitignore .env.example README.md src/bioagent/__init__.py tests/unit/test_package.py
git diff --cached --check
git commit -m "chore(基础): 初始化 Python 项目与质量工具"
```

### 任务 2：定义强类型计划、运行和 QC 模型

**文件：**

- 创建：`src/bioagent/domain/__init__.py`
- 创建：`src/bioagent/domain/plans.py`
- 创建：`src/bioagent/domain/runs.py`
- 创建：`src/bioagent/domain/qc.py`
- 创建：`src/bioagent/config.py`
- 创建：`tests/unit/domain/test_plans.py`
- 创建：`tests/unit/domain/test_runs.py`

- [x] **步骤 1：编写计划约束测试**

`tests/unit/domain/test_plans.py`：

```python
import pytest
from pydantic import ValidationError

from bioagent.domain.plans import AnalysisPlan, Comparison


def test_comparison_rejects_same_levels() -> None:
    with pytest.raises(ValidationError):
        Comparison(factor="condition", numerator="AD", denominator="AD")


def test_plan_has_only_supported_analysis_and_tool() -> None:
    plan = AnalysisPlan(
        dataset_id="b8b439c9-c576-4f87-ae41-69e0810c38c9",
        comparison=Comparison(factor="condition", numerator="AD", denominator="Control"),
    )
    assert plan.analysis_type == "bulk_differential_expression"
    assert plan.tool == "deseq2"
    assert plan.options.alpha == 0.05
```

运行：`uv run pytest tests/unit/domain/test_plans.py -v`

预期：FAIL，模块尚不存在。

- [x] **步骤 2：实现分析计划模型**

`src/bioagent/domain/plans.py` 定义：

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    numerator: str = Field(min_length=1)
    denominator: str = Field(min_length=1)

    @model_validator(mode="after")
    def levels_must_differ(self) -> "Comparison":
        if self.numerator == self.denominator:
            raise ValueError("numerator and denominator must differ")
        return self


class AnalysisOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alpha: float = Field(default=0.05, gt=0, lt=1)
    lfc_shrink: bool = True
    random_seed: int = Field(default=42, ge=0)


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    analysis_type: Literal["bulk_differential_expression"] = "bulk_differential_expression"
    tool: Literal["deseq2"] = "deseq2"
    dataset_id: str = Field(min_length=36, max_length=36)
    comparison: Comparison
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
```

- [x] **步骤 3：编写并实现状态转换测试**

`tests/unit/domain/test_runs.py` 断言：

```python
import pytest

from bioagent.domain.runs import RunStatus, ensure_transition


def test_running_requires_queued_state() -> None:
    ensure_transition(RunStatus.QUEUED, RunStatus.RUNNING)
    with pytest.raises(ValueError, match="invalid run transition"):
        ensure_transition(RunStatus.DRAFT, RunStatus.RUNNING)
```

`src/bioagent/domain/runs.py` 使用 `StrEnum` 定义设计规格中的全部状态，并用显式字典限制允许转换。`src/bioagent/domain/qc.py` 定义 `QCStatus`、`QCIssue(code, status, message, evidence)` 和 `QCReport`。

- [x] **步骤 4：实现环境配置**

`src/bioagent/config.py`：

```python
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIOAGENT_", env_file=".env", extra="ignore")
    llm_provider: Literal["deepseek", "ollama"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    api_base_url: str = "http://localhost:8000"
    runs_dir: Path = Path("runs")
    data_dir: Path = Path("data")
    checkpoint_db: Path = Path("checkpoints.sqlite")
    rscript: str = "Rscript"
```

- [x] **步骤 5：运行测试和静态检查**

运行：

```powershell
uv run pytest tests/unit/domain -v
uv run ruff check src/bioagent/domain src/bioagent/config.py tests/unit/domain
uv run mypy src
```

预期：全部 PASS，ruff 和 mypy 退出码为 0。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/domain src/bioagent/config.py tests/unit/domain
git diff --cached --check
git commit -m "feat(领域模型): 添加分析计划与运行状态契约"
```

### 任务 3：实现 Dataset 存储、解析和确定性校验

**文件：**

- 创建：`src/bioagent/datasets/__init__.py`
- 创建：`src/bioagent/datasets/parser.py`
- 创建：`src/bioagent/datasets/repository.py`
- 创建：`src/bioagent/datasets/validator.py`
- 创建：`tests/fixtures/counts_valid.csv`
- 创建：`tests/fixtures/metadata_valid.csv`
- 创建：`tests/unit/datasets/test_parser.py`
- 创建：`tests/unit/datasets/test_validator.py`
- 创建：`tests/unit/datasets/test_repository.py`

- [x] **步骤 1：创建最小固定数据**

`tests/fixtures/counts_valid.csv`：

```csv
feature_id,AD_1,AD_2,AD_3,CTRL_1,CTRL_2,CTRL_3
GENE_1,120,111,130,20,18,22
GENE_2,55,49,52,51,50,54
GENE_3,0,0,0,0,0,0
```

`tests/fixtures/metadata_valid.csv`：

```csv
sample_id,condition
AD_1,AD
AD_2,AD
AD_3,AD
CTRL_1,Control
CTRL_2,Control
CTRL_3,Control
```

- [x] **步骤 2：编写解析和校验失败测试**

测试必须覆盖：自动识别逗号/制表符、重复 feature ID、负值、非整数、样本集合不匹配、分组缺失、所选 factor 多于 2 个水平、少于 2 个重复、恰好 2 个重复和全零 feature。

关键测试：

```python
from pathlib import Path

from bioagent.datasets.parser import load_dataset
from bioagent.datasets.validator import validate_dataset
from bioagent.domain.plans import Comparison


def test_valid_dataset_warns_only_for_removed_zero_features() -> None:
    dataset = load_dataset(
        Path("tests/fixtures/counts_valid.csv"),
        Path("tests/fixtures/metadata_valid.csv"),
    )
    report = validate_dataset(
        dataset,
        Comparison(factor="condition", numerator="AD", denominator="Control"),
    )
    assert report.is_valid
    assert report.zero_feature_count == 1
    assert report.counts.index.tolist() == ["GENE_1", "GENE_2"]
```

运行：`uv run pytest tests/unit/datasets -v`

预期：FAIL，dataset 模块尚不存在。

- [x] **步骤 3：实现明确的解析契约**

`parser.py` 定义 `ParsedDataset(counts, metadata)`，使用扩展名选择 `sep`，设置 `feature_id` 和 `sample_id` 为索引；不根据内容猜测矩阵方向。

`validator.py` 返回浅层不可变的 `DatasetValidation`，包含清洗后的 counts、按 counts 顺序重排的 metadata、`QCReport` 和 `zero_feature_count`。冻结 dataclass 只阻止字段重新赋值，不使内部 pandas DataFrame 深度不可变；执行边界不得信任旧快照。所有错误使用稳定代码，例如 `DUPLICATE_FEATURE_ID`、`NON_INTEGER_COUNT`、`SAMPLE_SET_MISMATCH`、`LOW_REPLICATE_NUMBER`。

- [x] **步骤 4：实现安全 DatasetRepository**

`repository.py` 的公共接口：

```python
from pathlib import Path
from uuid import UUID, uuid4


class DatasetRepository:
    _ALLOWED_SUFFIXES = {".csv", ".tsv"}

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        counts_bytes: bytes,
        metadata_bytes: bytes,
        counts_suffix: str,
        metadata_suffix: str,
    ) -> str:
        if counts_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("unsupported counts suffix")
        if metadata_suffix not in self._ALLOWED_SUFFIXES:
            raise ValueError("unsupported metadata suffix")
        dataset_id = str(uuid4())
        dataset_dir = (self._root / dataset_id).resolve()
        if self._root not in dataset_dir.parents:
            raise ValueError("invalid dataset path")
        dataset_dir.mkdir()
        (dataset_dir / f"counts{counts_suffix}").write_bytes(counts_bytes)
        (dataset_dir / f"metadata{metadata_suffix}").write_bytes(metadata_bytes)
        return dataset_id

    def paths(self, dataset_id: str) -> tuple[Path, Path]:
        normalized_id = str(UUID(dataset_id))
        dataset_dir = (self._root / normalized_id).resolve()
        if self._root not in dataset_dir.parents:
            raise ValueError("invalid dataset id")
        counts = next(dataset_dir.glob("counts.*"))
        metadata = next(dataset_dir.glob("metadata.*"))
        return counts, metadata
```

实现要求：UUID4 作为目录名；扩展名仅允许 `.csv` 和 `.tsv`；不使用上传文件名；解析后的路径必须位于 `root.resolve()` 下；写入后计算 SHA-256。

- [x] **步骤 5：运行完整数据测试**

运行：

```powershell
uv run pytest tests/unit/datasets -v
uv run pytest tests/unit/datasets --cov=bioagent.datasets --cov-report=term-missing
uv run ruff check src/bioagent/datasets tests/unit/datasets
uv run mypy src
```

预期：全部 PASS，所有规格中的输入错误均有稳定错误码。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/datasets tests/fixtures tests/unit/datasets
git diff --cached --check
git commit -m "feat(数据): 添加测序矩阵解析与确定性校验"
```

### 任务 3.1：阶段审查修复 Dataset 与 QC 边界

**文件：**

- 修改：`.gitignore`
- 修改：`src/bioagent/datasets/repository.py`
- 修改：`src/bioagent/datasets/validator.py`
- 修改：`src/bioagent/domain/qc.py`
- 修改：`tests/unit/datasets/test_repository.py`
- 修改：`tests/unit/datasets/test_validator.py`
- 修改：`tests/unit/domain/test_runs.py`
- 修改：`docs/superpowers/plans/2026-08-15-bio-agent-mvp.md`
- 修改：`docs/progress/current-state.md`

- [x] **步骤 1：用失败测试复现 3 个阶段审查问题**

分别确认：重复 selected factor 会触发 pandas 裸 `ValueError`、篡改 dataset 文件后仓库仍返回路径、`QCReport.status` 可与 issues 的最高严重级别不一致且可在构造后被改坏。

- [x] **步骤 2：实现稳定的 metadata 列名与文件完整性校验**

重复 metadata 列统一返回 FAIL issue `DUPLICATE_METADATA_COLUMN`，并在访问 factor 前确认它恰好出现 1 次。`DatasetRepository.paths()` 与 `hashes()` 每次读取都重新计算 counts 和 metadata 的 SHA-256；不匹配时抛出 `DatasetIntegrityError`，不把篡改后的文件交给解析或执行层。

- [x] **步骤 3：强制 QC 聚合不变量并明确浅层不可变边界**

`QCReport` 在构造时要求 status 等于 issues 的最高严重级别，并冻结 report、issue 及 issues tuple；公开 `model_copy(update=...)` 也必须重新校验且保留 shallow/deep copy 语义，防止构造后或复制时破坏该不变量。`.coverage` 加入忽略规则。`DatasetValidation` 只承诺容器级浅层不可变；后续执行边界必须重新解析仓库文件、复算哈希并重新运行确定性 validator。

- [x] **步骤 4：运行定向与完整质量门禁**

```powershell
uv run pytest tests/unit/datasets/test_validator.py tests/unit/datasets/test_repository.py tests/unit/domain/test_runs.py -v -p no:cacheprovider
uv run pytest -v -p no:cacheprovider
uv run ruff check .
uv run mypy src
git diff --check
```

预期：测试、ruff、mypy 和 Git whitespace 检查全部退出 0。

- [x] **步骤 5：Commit**

```powershell
git add .gitignore src/bioagent/datasets/repository.py src/bioagent/datasets/validator.py src/bioagent/domain/qc.py tests/unit/datasets/test_repository.py tests/unit/datasets/test_validator.py tests/unit/domain/test_runs.py docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "fix(任务3.1): 加固数据完整性与 QC 不变量"
```

### 任务 4：实现 Artifact Store 与 provenance manifest

**文件：**

- 创建：`src/bioagent/artifacts/__init__.py`
- 创建：`src/bioagent/artifacts/manager.py`
- 创建：`src/bioagent/artifacts/manifest.py`
- 创建：`tests/unit/artifacts/test_manager.py`
- 创建：`tests/unit/artifacts/test_manifest.py`

- [x] **步骤 1：编写路径与哈希测试**

```python
from pathlib import Path

import pytest

from bioagent.artifacts.manager import ArtifactManager


def test_artifact_id_cannot_escape_run_directory(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    with pytest.raises(ValueError, match="invalid artifact id"):
        manager.resolve(run_id, "../../secret.txt")


def test_manifest_uses_relative_paths_and_hashes(tmp_path: Path) -> None:
    manager = ArtifactManager(tmp_path)
    run_id = manager.create_run()
    result = manager.write_bytes(run_id, "results/table.csv", b"gene,padj\nA,0.01\n")
    assert result.relative_path == "results/table.csv"
    assert len(result.sha256) == 64
```

运行：`uv run pytest tests/unit/artifacts -v`

预期：FAIL，artifact 模块尚不存在。

- [x] **步骤 2：实现运行目录和安全解析**

`ArtifactManager` 创建设计规格中的 `input/`、`plans/`、`attempts/` 和 `report/`。所有写入都通过 `write_bytes` 或 `write_json`；`resolve` 拒绝绝对路径、`..` 和越界路径。

- [x] **步骤 3：实现 manifest 模型与原子写入**

`manifest.py` 使用 Pydantic 定义 `ArtifactRecord`、`ApprovalRecord`、`AttemptRecord` 和 `RunManifest`。写入流程先写 `manifest.json.tmp`，再用 `Path.replace()` 原子替换。manifest 必须包含设计规格第 10 节列出的全部字段。

- [x] **步骤 4：运行测试**

运行：

```powershell
uv run pytest tests/unit/artifacts -v
uv run ruff check src/bioagent/artifacts tests/unit/artifacts
uv run mypy src
```

预期：全部 PASS，路径穿越测试被拒绝。

- [x] **步骤 5：Commit**

```powershell
git add src/bioagent/artifacts tests/unit/artifacts
git diff --cached --check
git commit -m "feat(产物): 添加运行目录与可审计 manifest"
```

### 任务 4.1：阶段审查修复——加固路径与 manifest 不变量

**文件：**

- 创建：`src/bioagent/artifacts/paths.py`
- 修改：`src/bioagent/artifacts/manager.py`
- 修改：`src/bioagent/artifacts/manifest.py`
- 修改：`tests/unit/artifacts/test_manager.py`
- 修改：`tests/unit/artifacts/test_manifest.py`

- [x] **步骤 1：以失败回归测试复现阶段审查问题**

为 `ArtifactManager` 和 `ArtifactRecord` 参数化覆盖 Windows 保留设备名、NTFS ADS、非法字符、控制字符，以及尾随空格或点；为 `RunManifest` 覆盖深层原位修改、写盘前重新验证，以及顶层状态、QC、结束时间与当前 attempt 冲突。

- [x] **步骤 2：共用安全相对路径校验**

集中校验 POSIX 相对路径、路径穿越和 Windows 文件名规则，manager 与 manifest 模型不再维护两套规则。

- [x] **步骤 3：加固 manifest 深层不变量与写盘边界**

将输入哈希、软件版本和 comparison 转换为不可原位修改的验证后快照；原子写入前从全部字段重建并验证 `RunManifest`，阻止绕过构造校验的内存修改落盘。

- [x] **步骤 4：约束顶层状态与当前 attempt 一致**

`status`、`qc` 和 `ended_at` 必须分别等于 `attempt_id` 指向 attempt 的对应字段。

- [x] **步骤 5：运行完整质量门禁**

```powershell
uv run pytest tests/unit/artifacts -v -p no:cacheprovider
uv run pytest -p no:cacheprovider
uv run ruff check .
uv run mypy src
git diff --check
```

结果：artifact 定向测试 73 passed；完整测试 131 passed；ruff、mypy 和 diff 检查全部通过。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/artifacts/paths.py src/bioagent/artifacts/manager.py src/bioagent/artifacts/manifest.py tests/unit/artifacts/test_manager.py tests/unit/artifacts/test_manifest.py docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "fix(任务4.1): 加固产物路径与 manifest 不变量"
```

### 任务 5：实现可独立验证的 R/DESeq2 工具

**文件：**

- 创建：`r/deseq2/functions.R`
- 创建：`r/deseq2/run.R`
- 创建：`r/tests/testthat.R`
- 创建：`r/tests/testthat/helper-source.R`
- 创建：`r/tests/testthat/test-deseq2.R`
- 创建：`tool_specs/deseq2.yaml`
- 创建：`tests/fixtures/counts_deseq2.csv`
- 创建：`tests/fixtures/metadata_deseq2.csv`
- 创建：`tests/fixtures/deseq2_parameters.json`
- 生成：`.Rprofile`
- 生成：`renv/activate.R`
- 生成：`renv/settings.json`
- 生成：`renv.lock`

- [x] **步骤 1：初始化隔离的 R 环境**

运行：

```powershell
Rscript -e "if (!requireNamespace('renv', quietly=TRUE)) install.packages('renv', repos='https://cloud.r-project.org')"
Rscript -e "renv::init(bare=TRUE)"
Rscript -e "renv::install(c('jsonlite','ggplot2','pheatmap','testthat','BiocManager'))"
Rscript -e "BiocManager::install(c('DESeq2','apeglm'), ask=FALSE, update=FALSE)"
Rscript -e "renv::snapshot(prompt=FALSE)"
```

预期：`renv.lock` 记录 R 4.5.2、DESeq2、apeglm、jsonlite、ggplot2、pheatmap 和 testthat。

- [x] **步骤 2：编写失败的 R 契约测试**

`r/tests/testthat/test-deseq2.R` 使用固定种子生成 200 个基因、AD/Control 各 3 个样本的整数矩阵，并断言：

```r
test_that("DESeq2 comparison direction is numerator over denominator", {
  fixture <- make_bulk_fixture(seed = 42L)
  result <- run_deseq2(
    counts = fixture$counts,
    metadata = fixture$metadata,
    factor = "condition",
    numerator = "AD",
    denominator = "Control",
    alpha = 0.05,
    lfc_shrink = TRUE
  )
  expect_true(all(c("feature_id", "log2FoldChange", "pvalue", "padj") %in% names(result$table)))
  expect_gt(result$table["GENE_001", "log2FoldChange"], 0)
})
```

运行：`Rscript -e "testthat::test_dir('r/tests/testthat')"`

预期：FAIL，`make_bulk_fixture` 和 `run_deseq2` 尚不存在。

`r/tests/testthat/helper-source.R` 从 helper 自身位置向上定位项目根目录，再加载 `r/deseq2/functions.R`，因此不依赖 testthat 改变后的工作目录。

- [x] **步骤 3：实现 DESeq2 纯函数**

`functions.R` 必须导出 4 个精确接口：

- `validate_deseq2_inputs(counts, metadata, factor, numerator, denominator)`：成功时返回 `invisible(TRUE)`，失败时使用稳定错误码调用 `stop()`。
- `run_deseq2(counts, metadata, factor, numerator, denominator, alpha, lfc_shrink)`：返回命名 list，字段固定为 `dds`、`table`、`normalized_counts`、`pca`、`size_factors` 和 `summary`。
- `write_deseq2_outputs(result, output_dir)`：写入 Tool Registry 声明的全部 CSV、JSON、PNG 和 PDF 文件，并返回相对路径字符向量。
- `make_bulk_fixture(seed=42L)`：返回固定 200 基因、6 样本的 `counts` 和 `metadata`，其中 `GENE_001` 在 AD 组上调。

固定实现行为：metadata 按 counts 列顺序重排；所选 factor 在 MVP 中必须恰好包含 2 个水平；denominator 通过 `relevel()` 设为 reference；使用 `results(dds, contrast=c(factor, numerator, denominator), alpha=alpha)`；启用 shrink 时从 `setdiff(resultsNames(dds), "Intercept")` 取得唯一 coefficient 并调用 `lfcShrink(type="apeglm")`；结果表按 `padj`、`pvalue` 稳定排序；输出 normalized counts、PCA 坐标、全部结果、显著结果、size factors 和 session info。

- [x] **步骤 4：实现唯一 Rscript 入口**

`run.R` 只接收 1 个 JSON 参数文件路径，检查字段白名单并调用纯函数。它创建 PNG/PDF 图和 `execution_summary.json`，发生错误时写入 stderr 并以非 0 退出；不解析或执行 JSON 中的代码和路径表达式。使用 `make_bulk_fixture(seed=42L)` 生成并提交 2 个 CLI fixture CSV，`deseq2_parameters.json` 只引用这 2 个固定输入和测试输出目录。

- [x] **步骤 5：定义 Tool Registry 条目**

`tool_specs/deseq2.yaml` 明确：`schema_version: "1.0"`、固定入口 `r/deseq2/run.R`、超时 1800 秒、输入类型、计划参数、必需产物、运行前规则和运行后规则。不登记 edgeR、富集或任意脚本执行能力。

- [x] **步骤 6：运行 R 测试与命令行烟雾测试**

运行：

```powershell
Rscript -e "testthat::test_dir('r/tests/testthat')"
Rscript r/deseq2/run.R tests/fixtures/deseq2_parameters.json
```

预期：testthat 0 failures；烟雾测试生成全部必需产物，进程退出码为 0。

- [x] **步骤 7：Commit**

```powershell
git add r/deseq2 r/tests tool_specs/deseq2.yaml renv.lock renv/activate.R renv/settings.json .Rprofile tests/fixtures/counts_deseq2.csv tests/fixtures/metadata_deseq2.csv tests/fixtures/deseq2_parameters.json
git diff --cached --check
git commit -m "feat(DESeq2): 添加受控差异分析工具"
```

### 任务 6：实现 Tool Registry、R Runner 和确定性输出 QC

**文件：**

- 创建：`src/bioagent/tools/__init__.py`
- 创建：`src/bioagent/tools/registry.py`
- 创建：`src/bioagent/tools/deseq2.py`
- 创建：`src/bioagent/execution/__init__.py`
- 创建：`src/bioagent/execution/r_runner.py`
- 创建：`tests/unit/tools/test_registry.py`
- 创建：`tests/unit/execution/test_r_runner.py`
- 创建：`tests/integration/test_deseq2_runner.py`

- [x] **步骤 1：编写 Registry 和命令安全测试**

```python
from pathlib import Path

from bioagent.execution.r_runner import RCommand


def test_r_command_is_argument_vector_without_shell() -> None:
    command = RCommand.build(
        project_root=Path.cwd(),
        rscript="Rscript",
        entrypoint=Path("r/deseq2/run.R"),
        parameters=Path("runs/id/parameters.json"),
    )
    assert command.argv[0] == "Rscript"
    assert Path(command.argv[1]).is_absolute()
    assert command.argv[1].endswith("r\\deseq2\\run.R") or command.argv[1].endswith("r/deseq2/run.R")
    assert Path(command.argv[2]).is_absolute()
    assert command.argv[2].endswith("runs\\id\\parameters.json") or command.argv[2].endswith("runs/id/parameters.json")
    assert not hasattr(command, "shell_command")
```

Registry 测试还要拒绝未知 YAML 字段、绝对入口路径、`..` 路径和未声明产物。

运行：`uv run pytest tests/unit/tools tests/unit/execution -v`

预期：FAIL，相应模块尚不存在。

- [x] **步骤 2：实现版本化 ToolSpec**

`registry.py` 用 Pydantic 解析 YAML，返回不可变 `ToolSpec`；启动时验证入口位于项目根目录且所有产物路径均为相对路径。`ToolRegistry.get("deseq2")` 是 MVP 唯一成功查询。

- [x] **步骤 3：实现 RRunner**

`r_runner.py` 先将 Registry 中的固定入口相对项目根目录解析为绝对路径，再使用 `subprocess.run(argv, shell=False, cwd=attempt_dir, timeout=spec.timeout_seconds, capture_output=True, text=True, check=False, env=minimal_env)`。参数 JSON 路径也在调用前解析；stdout 和 stderr 分别写入 artifact 日志；超时、取消、非 0 退出码映射为稳定错误类型。

- [x] **步骤 4：实现 DESeq2 输出适配与 QC**

`tools/deseq2.py` 将 `AnalysisPlan` 转成参数 JSON，只写入受控输入和 attempt 路径；运行后检查必需文件、CSV 列、结果行数、NA padj 比例、PCA 坐标和 `execution_summary.json`。NA padj 比例产生 `WARN`，缺失产物产生 `FAIL`。

- [x] **步骤 5：运行 Mock 单元测试与真实 R 集成测试**

运行：

```powershell
uv run pytest tests/unit/tools tests/unit/execution -v
uv run pytest tests/integration/test_deseq2_runner.py -v
uv run ruff check src/bioagent/tools src/bioagent/execution tests/unit/tools tests/unit/execution
uv run mypy src
```

预期：全部 PASS；真实集成测试的 log2 fold change 方向与 R 基准一致。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/tools src/bioagent/execution tests/unit/tools tests/unit/execution tests/integration/test_deseq2_runner.py
git diff --cached --check
git commit -m "feat(执行): 添加安全 R Runner 与结果校验"
```

### 任务 7：实现 DeepSeek/Ollama 工厂与结构化 Planner

**文件：**

- 创建：`src/bioagent/llm/__init__.py`
- 创建：`src/bioagent/llm/factory.py`
- 创建：`src/bioagent/llm/planner.py`
- 创建：`tests/unit/llm/test_factory.py`
- 创建：`tests/unit/llm/test_planner.py`

- [x] **步骤 1：编写无 Key 与 Mock 计划测试**

```python
import pytest

from bioagent.config import Settings
from bioagent.llm.factory import create_chat_model


def test_deepseek_requires_key() -> None:
    settings = Settings(llm_provider="deepseek", deepseek_api_key=None)
    with pytest.raises(ValueError, match="DeepSeek API key is required"):
        create_chat_model(settings)
```

Planner 测试使用实现 `with_structured_output` 的 FakeChatModel，断言输出只能是 `AnalysisPlan`，未知 metadata level 会在确定性验证阶段被拒绝。

- [x] **步骤 2：实现模型工厂**

`factory.py`：DeepSeek 使用 `ChatOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, model=settings.deepseek_model, timeout=60, max_retries=2)`；Ollama 使用 `ChatOllama(base_url=settings.ollama_base_url, model=settings.ollama_model)`。工厂不创建自定义 Provider 继承树，不记录 SecretStr 内容。

- [x] **步骤 3：实现受约束 Planner**

`planner.py` 的输入只包含用户目标和经过清洗的数据摘要，不包含上传文件的自由文本。系统提示明确支持范围、比较方向和禁止事项；调用 `model.with_structured_output(AnalysisPlan)`；第一次 schema 失败时追加 Pydantic 错误并重试 1 次。

- [x] **步骤 4：运行测试**

运行：

```powershell
uv run pytest tests/unit/llm -v
uv run ruff check src/bioagent/llm tests/unit/llm
uv run mypy src
```

预期：全部 PASS；测试期间无网络请求。

- [x] **步骤 5：Commit**

```powershell
git add src/bioagent/llm tests/unit/llm docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务7): 添加可切换模型与结构化分析计划"
```

### 任务 8：实现 LangGraph 审批状态机与 SQLite checkpoint

**文件：**

- 创建：`src/bioagent/workflow/__init__.py`
- 创建：`src/bioagent/workflow/state.py`
- 创建：`src/bioagent/workflow/nodes.py`
- 创建：`src/bioagent/workflow/graph.py`
- 创建：`src/bioagent/storage/__init__.py`
- 创建：`src/bioagent/storage/checkpoint.py`
- 创建：`src/bioagent/storage/runs.py`
- 创建：`tests/unit/workflow/test_graph.py`
- 创建：`tests/integration/test_checkpoint_resume.py`

- [x] **步骤 1：编写“未审批不执行”测试**

```python
from langgraph.checkpoint.memory import InMemorySaver

from bioagent.workflow.graph import build_graph


def test_graph_interrupts_before_execution(fake_planner, spy_executor) -> None:
    graph = build_graph(fake_planner, spy_executor, InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}
    result = graph.invoke({"run_id": "run-1", "user_goal": "AD vs Control"}, config)
    assert result["status"] == "AWAITING_APPROVAL"
    assert spy_executor.call_count == 0
```

另一个测试使用 `Command(resume={"action": "approve", "plan_revision": 1})` 恢复，并断言 executor 仅调用 1 次。

- [x] **步骤 2：定义 JSON 可序列化 WorkflowState**

`state.py` 只保存字符串、数字、布尔、字典和列表；DataFrame、Path、模型对象和 subprocess 句柄不得进入 checkpoint。状态包含 run ID、dataset ID、用户目标、计划 JSON、计划版本、审批、attempt ID、run status、QC 和错误。

- [x] **步骤 3：实现单职责节点与显式路由**

节点顺序：`load_summary → plan → validate_plan → approval_interrupt → execute → validate_outputs → report → complete`。错误路由按稳定错误类型进入 `await_user` 或 `failed`；没有返回 `plan` 的无限循环边。

- [x] **步骤 4：实现 checkpoint 与 RunRepository**

`checkpoint.py` 返回 `SqliteSaver`，数据库只保存 LangGraph 状态。`storage/runs.py` 原子读写 `runs/<run_id>/run.json`，作为 API 查询索引；科研证据仍以 manifest 为准。

- [x] **步骤 5：运行中断恢复测试**

运行：

```powershell
uv run pytest tests/unit/workflow tests/integration/test_checkpoint_resume.py -v
uv run ruff check src/bioagent/workflow src/bioagent/storage tests/unit/workflow
uv run mypy src
```

预期：全部 PASS；同一 thread ID 可跨 graph 实例恢复，审批前 executor 调用数为 0。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/workflow src/bioagent/storage tests/unit/workflow tests/integration/test_checkpoint_resume.py
git diff --cached --check
git commit -m "feat(工作流): 添加审批中断与持久化恢复"
```

### 任务 9：实现 Execution Controller 与本地单 Worker

**文件：**

- 创建：`src/bioagent/execution/controller.py`
- 创建：`src/bioagent/execution/job_runner.py`
- 创建：`tests/unit/execution/test_controller.py`
- 创建：`tests/unit/execution/test_job_runner.py`
- 修改：`src/bioagent/workflow/nodes.py`
- 修改：`tests/unit/workflow/test_graph.py`
- 修改：`tests/integration/test_checkpoint_resume.py`

- [x] **步骤 1：编写审批、plan hash 与幂等测试**

关键断言：未审批计划被拒绝；修改计划后旧审批无效；相同 `plan_hash` 且产物完整时不再次调用 R；失败 attempt 不覆盖之前日志；Job Runner 的 `submit` 立即返回 job ID。

```python
def test_controller_reuses_completed_identical_plan(controller, approved_plan, spy_tool) -> None:
    first = controller.execute(approved_plan)
    second = controller.execute(approved_plan)
    assert first.attempt_id == second.attempt_id
    assert spy_tool.call_count == 1
```

- [x] **步骤 2：实现规范化 plan hash**

先用 `plan.model_dump(mode="json", exclude_none=True)` 得到字典，再用 `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 生成规范 JSON 和 SHA-256；审批记录同时保存 plan revision 和 plan hash。Controller 在任何文件或进程操作前验证二者一致。

- [x] **步骤 3：实现 ExecutionController**

Controller 负责解析安全路径、创建 attempt、生成参数 JSON、调用 Registry 工具、运行输出 QC、更新 run 状态和 manifest。每次进入执行边界都必须通过 `DatasetRepository.paths()` 重新核对文件 SHA-256，再从磁盘重新解析并调用 `validate_dataset()`；不得复用或信任之前返回的 `DatasetValidation` 快照。它不包含 LLM、HTTP 或 Streamlit 逻辑。

- [x] **步骤 4：实现 LocalJobRunner**

使用 `ThreadPoolExecutor(max_workers=1)` 包装外部 R subprocess；公共接口为 `submit(run_id, callable) -> job_id`、`status(job_id)` 和 `cancel(job_id)`。每个 worker 内重新取得自己的 repository/checkpoint 资源，不复用 FastAPI request scope 对象。

- [x] **步骤 5：运行测试**

运行：

```powershell
uv run pytest tests/unit/execution -v
uv run ruff check src/bioagent/execution tests/unit/execution
uv run mypy src
```

预期：全部 PASS；幂等测试只执行 1 次工具调用。

- [x] **步骤 6：Commit**

```powershell
git add src/bioagent/execution tests/unit/execution
git diff --cached --check
git commit -m "feat(调度): 添加幂等执行控制与本地任务队列"
```

### 任务 10：实现 FastAPI 资源接口

**文件：**

- 创建：`src/bioagent/api/__init__.py`
- 创建：`src/bioagent/api/app.py`
- 创建：`src/bioagent/api/dependencies.py`
- 创建：`src/bioagent/api/routes.py`
- 创建：`tests/integration/api/test_datasets.py`
- 创建：`tests/integration/api/test_runs.py`
- 创建：`tests/integration/api/test_artifacts.py`

- [x] **步骤 1：编写 API 失败测试**

使用 `TestClient` 验证：合法上传返回 dataset ID；样本不匹配返回 422 和稳定错误码；创建 run 返回 `AWAITING_APPROVAL`；批准返回 HTTP 202；未审批产物返回 409；artifact 路径穿越返回 404；`/health` 与 `/ready` 分别反映进程和依赖状态。

```python
def test_run_requires_approval_before_execution(client, dataset_id) -> None:
    response = client.post(
        "/api/v1/runs",
        json={"dataset_id": dataset_id, "goal": "compare AD with Control"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "AWAITING_APPROVAL"
```

- [x] **步骤 2：实现应用工厂和依赖装配**

`create_app(settings, overrides=None)` 创建 FastAPI；所有 repository、planner、graph、controller 和 job runner 从 `dependencies.py` 注入。测试通过 overrides 注入 Mock，不读取真实 Key。

- [x] **步骤 3：实现设计规格中的 API**

实现 dataset 上传/校验、run 创建/查询/计划、审批/取消、artifact 列表/下载、health/ready。上传设置明确的最大字节数；下载使用 artifact ID 查 manifest，不接受路径参数。

- [x] **步骤 4：运行 API 测试与 OpenAPI 检查**

运行：

```powershell
uv run pytest tests/integration/api -v
uv run python -c "from bioagent.api.app import create_app; assert '/api/v1/runs' in create_app().openapi()['paths']"
uv run ruff check src/bioagent/api tests/integration/api
uv run mypy src
```

预期：全部 PASS，OpenAPI 包含全部 MVP 路径。

- [x] **步骤 5：Commit**

```powershell
git add src/bioagent/api tests/integration/api
git diff --cached --check
git commit -m "feat(API): 添加数据、审批与产物接口"
```

### 任务 11：实现确定性报告和受约束摘要

**文件：**

- 创建：`src/bioagent/reporting/__init__.py`
- 创建：`src/bioagent/reporting/generator.py`
- 创建：`src/bioagent/reporting/templates/report.html.j2`
- 创建：`tests/unit/reporting/test_generator.py`

- [x] **步骤 1：编写离线报告测试**

```python
def test_report_builds_without_llm(report_generator, validated_run) -> None:
    html = report_generator.render(validated_run, narrative=None)
    assert "AD relative to Control" in html
    assert "QC: WARN" in html
    assert "DESeq2" in html
    assert "LLM narrative unavailable" in html
```

测试还要断言所有统计数字来自结构化 summary，HTML 转义用户文本，artifact 链接为相对路径。

- [x] **步骤 2：实现确定性报告模型与模板**

`generator.py` 只接受 `RunManifest`、`QCReport` 和经过验证的结果 summary。模板固定渲染方法、比较方向、样本数、阈值、QC、软件版本、图和下载链接。

- [x] **步骤 3：增加可选 LLM 摘要**

摘要输入为白名单 JSON：比较方向、样本数、显著基因数量、QC issue 和前 10 个结果。返回值是纯文本；模型失败时记录 WARN 并生成完整确定性报告。摘要不得修改表格或数字。

- [x] **步骤 4：运行测试**

运行：

```powershell
uv run pytest tests/unit/reporting -v
uv run ruff check src/bioagent/reporting tests/unit/reporting
uv run mypy src
```

预期：全部 PASS；没有 API Key 也能生成报告。

- [x] **步骤 5：Commit**

```powershell
git add src/bioagent/reporting tests/unit/reporting
git diff --cached --check
git commit -m "feat(报告): 添加离线可用的分析报告"
```

### 任务 12：实现 Streamlit HTTP 客户端

**文件：**

- 创建：`ui/streamlit_app.py`
- 创建：`tests/unit/ui/test_streamlit_app.py`

- [x] **步骤 1：编写 Streamlit 页面烟雾测试**

使用 `streamlit.testing.v1.AppTest` 和 Mock HTTP client，断言侧栏包含 New Analysis、Plan Review、Run Monitor、Results、Run History；上传页面没有直接导入 `bioagent.workflow` 或 `bioagent.execution`。

- [x] **步骤 2：实现 API client 与 Session State**

`streamlit_app.py` 仅通过 `httpx.Client(base_url=settings.api_base_url, timeout=30)` 调用 API。Session State 保存 dataset ID、run ID、plan revision 和页面选择，不保存 DataFrame、API Key 或模型对象。

- [x] **步骤 3：实现 5 个 MVP 页面**

New Analysis 展示上传和校验；Plan Review 明确显示 numerator 相对 denominator 并提供批准/修改/拒绝；Run Monitor 轮询状态并支持取消；Results 展示 QC、PNG、报告和下载；Run History 列出 manifest 摘要。

- [x] **步骤 4：运行 UI 测试**

运行：

```powershell
uv run pytest tests/unit/ui -v
uv run streamlit run ui/streamlit_app.py --server.headless true
```

预期：测试 PASS；Streamlit 启动后健康检查成功且没有直接访问 R 或 LangGraph。

- [x] **步骤 5：Commit**

```powershell
git add ui/streamlit_app.py tests/unit/ui/test_streamlit_app.py
git diff --cached --check
git commit -m "feat(界面): 添加分析审批与结果展示页面"
```

### 任务 12.1：实现项目级运行历史 API

**设计规格：** `docs/superpowers/specs/2026-09-04-project-run-history-api-design.md`

**文件：**

- 修改：`src/bioagent/storage/runs.py`
- 修改：`src/bioagent/api/routes.py`
- 修改：`ui/streamlit_app.py`
- 创建：`tests/unit/storage/test_runs.py`
- 创建：`tests/unit/storage/__init__.py`
- 修改：`tests/integration/api/test_runs.py`
- 修改：`tests/unit/ui/test_streamlit_app.py`
- 修改：`docs/superpowers/specs/2026-09-04-project-run-history-api-design.md`
- 修改：`docs/superpowers/plans/2026-08-15-bio-agent-mvp.md`
- 修改：`docs/progress/current-state.md`

- [x] **步骤 1：编写 RunRepository 枚举失败测试**

创建 `tests/unit/storage/test_runs.py`，使用真实临时目录覆盖空目录、更新时间排序、损坏 index 隔离和 UUID4 边界：

```python
def test_list_entries_orders_valid_runs_and_isolates_corrupt_index(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")
    older = str(uuid4())
    newer = str(uuid4())
    corrupt = str(uuid4())
    repository.write(older, {"run_id": older, "dataset_id": str(uuid4()), "status": "FAILED"})
    repository.write(newer, {"run_id": newer, "dataset_id": str(uuid4()), "status": "RUNNING"})
    os.utime(tmp_path / "runs" / older / "run.json", (1, 1))
    os.utime(tmp_path / "runs" / newer / "run.json", (2, 2))
    corrupt_dir = tmp_path / "runs" / corrupt
    corrupt_dir.mkdir()
    (corrupt_dir / "run.json").write_text("not-json", encoding="utf-8")

    entries, issues = repository.list_entries()

    assert [entry.run_id for entry in entries] == [newer, older]
    assert [(issue.run_id, issue.code) for issue in issues] == [
        (corrupt, "RUN_INDEX_INVALID")
    ]
```

测试还要断言非 UUID 目录被忽略，解析后越过 `runs_dir` 的目录不能被读取；若 Windows 环境不允许创建测试 symlink，则只跳过该 symlink 用例，不跳过其他路径测试。

- [x] **步骤 2：运行 Repository 测试并确认红灯**

运行：

```powershell
uv run --offline pytest tests/unit/storage/test_runs.py -v -p no:cacheprovider
```

预期：FAIL，`RunRepository` 尚无 `list_entries()`，`RunIndexEntry` 和 `RunIndexIssue` 尚不存在。

- [x] **步骤 3：实现安全的运行索引枚举**

在 `src/bioagent/storage/runs.py` 增加冻结结果类型和只读方法：

```python
@dataclass(frozen=True)
class RunIndexEntry:
    run_id: str
    state: dict[str, JsonValue]
    updated_at: datetime


@dataclass(frozen=True)
class RunIndexIssue:
    run_id: str
    code: Literal["RUN_INDEX_INVALID"] = "RUN_INDEX_INVALID"


def list_entries(self) -> tuple[tuple[RunIndexEntry, ...], tuple[RunIndexIssue, ...]]:
    entries: list[RunIndexEntry] = []
    issues: list[RunIndexIssue] = []
    if not self._runs_dir.exists():
        return (), ()
    for candidate in self._runs_dir.iterdir():
        try:
            run_id = validate_run_id(candidate.name)
        except ValueError:
            continue
        try:
            state = self.read(run_id)
            updated_at = datetime.fromtimestamp(
                (self._run_dir(run_id) / "run.json").stat().st_mtime,
                tz=timezone.utc,
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            issues.append(RunIndexIssue(run_id=run_id))
            continue
        entries.append(RunIndexEntry(run_id=run_id, state=state, updated_at=updated_at))
    entries.sort(key=lambda item: (-item.updated_at.timestamp(), item.run_id))
    issues.sort(key=lambda item: item.run_id)
    return tuple(entries), tuple(issues)
```

实现不能返回主机路径或原始异常文本。运行步骤 2 的命令，预期全部 PASS。

- [x] **步骤 4：编写全局运行列表 API 失败测试**

扩展 `tests/integration/api/test_runs.py`，用真实 `RunRepository` 和 `ArtifactManager` 断言：

```python
def test_project_run_history_lists_all_states_and_filters_by_status(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path / "runs")
    failed_id = _write_run(repository, status="FAILED")
    running_id = _write_run(repository, status="RUNNING")
    with TestClient(_app(tmp_path, extra_overrides={"run_repository": repository})) as client:
        all_runs = client.get("/api/v1/runs")
        running = client.get("/api/v1/runs", params={"status": "RUNNING"})

    assert all_runs.status_code == 200
    assert {item["run_id"] for item in all_runs.json()["runs"]} == {
        failed_id,
        running_id,
    }
    assert [item["run_id"] for item in running.json()["runs"]] == [running_id]
```

另加完成态 manifest 一致、manifest 缺失/身份不一致、损坏 `run.json` 不阻塞其他项、非法状态返回 422，以及响应不包含 `user_goal`、`plan`、绝对路径或原始异常的测试。

- [x] **步骤 5：运行 API 测试并确认红灯**

运行：

```powershell
uv run --offline pytest tests/integration/api/test_runs.py -v -p no:cacheprovider
```

预期：新增列表测试 FAIL，`GET /api/v1/runs` 尚不存在或不满足列表契约；现有单 run 测试保持 PASS。

- [x] **步骤 6：实现摘要模型、manifest 核验和列表路由**

在 `src/bioagent/api/routes.py` 增加严格响应模型：

```python
class RunListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str
    dataset_id: str
    status: RunStatus
    qc_status: QCStatus | None = None
    plan_revision: int | None = None
    attempt_id: str | None = None
    index_updated_at: datetime
    completed_at: datetime | None = None
    evidence_status: Literal["VERIFIED", "INDEX_ONLY", "INVALID"]


class RunListIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    run_id: str
    code: Literal["RUN_INDEX_INVALID", "RUN_MANIFEST_INVALID"]
```

新增 `GET /api/v1/runs`。它使用 `RunRepository.list_entries()`，按可选 `status: RunStatus | None` 过滤合法摘要；完成态通过 `RunManifest` 重验 run、dataset、attempt、status 和 QC，一致时返回 `VERIFIED` 与 manifest `ended_at`，否则保留该 run、标记 `INVALID` 并追加 `RUN_MANIFEST_INVALID`。未完成态标记 `INDEX_ONLY`。任何响应都不包含路径或原始异常。

运行步骤 5 的命令和：

```powershell
uv run --offline python -c "from bioagent.api.app import create_app; assert '/api/v1/runs' in create_app().openapi()['paths']"
```

预期：API 测试全部 PASS，OpenAPI 包含列表路径。

- [x] **步骤 7：编写 Streamlit 全局历史失败测试**

修改 `tests/unit/ui/test_streamlit_app.py`：删除依赖 `run_ids` Session State 的旧历史测试，改为 Mock 项目列表 API：

```python
def test_run_history_loads_project_runs_without_session_run_ids() -> None:
    run_id = "b8b439c9-c576-4f87-ae41-69e0810c38c9"
    dataset_id = "61d32f63-7c68-41df-814e-296fc47b5730"
    attempt_id = "b99fb530-a935-45d8-8ccd-c5c01c07354d"
    transport = MagicMock(spec=httpx.Client)
    transport.get.return_value = _response(
        {
            "runs": [
                {
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "status": "COMPLETED",
                    "qc_status": "PASS",
                    "plan_revision": 2,
                    "attempt_id": attempt_id,
                    "index_updated_at": "2026-09-04T08:30:00+00:00",
                    "completed_at": "2026-09-04T08:29:58+00:00",
                    "evidence_status": "VERIFIED",
                }
            ],
            "issues": [],
        }
    )
    with patch("httpx.Client", return_value=transport):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.sidebar.radio[0].set_value("Run History").run()

    assert not app.exception
    assert any(run_id in element.value for element in app.markdown)
    transport.get.assert_called_with("/api/v1/runs")
    assert "run_ids" not in app.session_state.filtered_state
```

补充选择 run、状态过滤和 `RUN_MANIFEST_INVALID` 展示测试。选择 run 后只允许更新 `run_id` 与 `plan_revision`，不得把完整列表写入 Session State。

- [x] **步骤 8：运行 Streamlit 测试并确认红灯**

运行：

```powershell
uv run --offline pytest tests/unit/ui/test_streamlit_app.py -v -p no:cacheprovider
```

预期：新增测试 FAIL，因为 `ApiClient.list_runs()` 不存在且 Run History 仍依赖 `run_ids`。

- [x] **步骤 9：实现项目历史页面并移除会话历史缓存**

在 `ui/streamlit_app.py` 增加：

```python
def list_runs(self, status: str | None = None) -> dict[str, object]:
    if status is None:
        response = self._client.get("/api/v1/runs")
    else:
        response = self._client.get("/api/v1/runs", params={"status": status})
    return self._json(response)
```

Run History 每次渲染调用 `list_runs()`，显示摘要、evidence 状态和结构化 issues，并提供“Open run”按钮。删除 `run_ids` Session State、`_remember_run()` 和相关缓存逻辑；选择历史 run 时只写入当前 `run_id` 与 `plan_revision`。运行步骤 8 命令，预期全部 PASS。

- [x] **步骤 10：运行 Task 12.1 定向验收**

运行：

```powershell
uv run --offline pytest tests/unit/storage/test_runs.py tests/integration/api/test_runs.py tests/unit/ui/test_streamlit_app.py -v -p no:cacheprovider
uv run --offline ruff check src/bioagent/storage/runs.py src/bioagent/api/routes.py ui/streamlit_app.py tests/unit/storage tests/integration/api/test_runs.py tests/unit/ui
uv run --offline mypy src
uv run --offline python -c "from bioagent.api.app import create_app; assert '/api/v1/runs' in create_app().openapi()['paths']"
```

再以 headless 模式启动 Streamlit 并请求 `/_stcore/health`。预期：定向测试、Ruff、mypy、OpenAPI 和健康检查全部退出 0。

- [x] **步骤 11：运行完整门禁、更新状态并 Commit**

运行：

```powershell
uv run --offline pytest -q -p no:cacheprovider
uv run --offline ruff check .
uv run --offline mypy src
git diff --check
```

更新本任务复选框和 `docs/progress/current-state.md`，记录红灯、绿灯、完整验证、阻塞项和下一任务 Task 13。只暂存本任务文件：

```powershell
git add src/bioagent/storage/runs.py src/bioagent/api/routes.py ui/streamlit_app.py tests/unit/storage/__init__.py tests/unit/storage/test_runs.py tests/integration/api/test_runs.py tests/unit/ui/test_streamlit_app.py docs/superpowers/specs/2026-09-04-project-run-history-api-design.md docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "feat(任务12.1): 添加项目级运行历史 API"
```

### 任务 13：建立 Agent eval 与端到端验收

**文件：**

- 创建：`evals/cases.yaml`
- 创建：`tests/evals/test_planner_cases.py`
- 创建：`tests/e2e/test_bulk_workflow.py`
- 创建：`tests/e2e/test_recovery.py`

- [x] **步骤 1：写入固定 eval cases**

`evals/cases.yaml` 至少包含 8 个具名案例：正常比较、比较方向歧义、未知分组、多因素请求、自动换工具请求、跳过审批请求、非法 JSON 修复和文件内提示注入。每个案例明确期望 `plan`、`reject` 或 `clarify`，以及 executor 期望调用次数。

- [x] **步骤 2：编写参数化 Agent 行为测试**

```python
@pytest.mark.parametrize("case", load_eval_cases())
def test_planner_policy(case, eval_harness) -> None:
    result = eval_harness.run(case)
    assert result.outcome == case.expected_outcome
    assert result.executor_calls == case.expected_executor_calls
```

未审批和不支持请求的 `expected_executor_calls` 必须为 0。

- [x] **步骤 3：编写端到端测试**

端到端测试使用固定数据、FakeChatModel、真实 LangGraph、真实 SQLite、真实 R Runner 和临时 artifact 目录。断言：审批前暂停；批准后完成；比较方向正确；所有必需产物存在；manifest 哈希正确；重新调用相同计划不执行第二次 R。

- [x] **步骤 4：编写崩溃恢复测试**

第一次执行在创建 attempt 后注入失败；重新构建 graph 并使用同一 thread ID 恢复。断言旧日志仍存在、新 attempt ID 不同、成功 manifest 指向新 attempt、失败日志未被覆盖。

- [x] **步骤 5：运行验收测试**

运行：

```powershell
uv run pytest tests/evals -v
uv run pytest tests/e2e -v
uv run pytest --cov=bioagent --cov-report=term-missing
```

预期：全部 PASS；未审批场景 R 调用次数为 0；端到端场景生成完整 artifact 包。

- [x] **步骤 6：Commit**

```powershell
git add evals tests/evals tests/e2e
git diff --cached --check
git commit -m "test(评测): 添加 Agent 策略与端到端验收"
```

### 任务 14：配置 CI、开发命令与安全检查

**文件：**

- 创建：`.github/workflows/ci.yml`
- 创建：`.pre-commit-config.yaml`
- 创建：`scripts/check.ps1`
- 创建：`tests/unit/test_check_script.py`（脚本失败退出与 CI 配置回归）
- 创建：`r/dependencies.R`（声明静态扫描无法识别的动态 apeglm 依赖）
- 修改：`renv.lock`（补记既有 renv 1.2.4 及其已验证哈希，不升级统计包）

- [x] **步骤 1：创建本地统一检查脚本**

`scripts/check.ps1` 使用 `$ErrorActionPreference = "Stop"`，依次运行 `uv sync --frozen --dev`、ruff、mypy、Python 单元/集成测试、`renv::restore()` 状态检查和 testthat。任一命令失败时脚本立即退出非 0。

实现补充：默认 `-Suite All`，CI 可选 `Python` 或 `R`。Python suite 包含 Mock 集成和 Agent eval；R suite 先恢复并严格核验 renv，再运行 testthat、真实 DESeq2 集成和端到端测试。14 项回归测试覆盖八个外部命令阶段的失败停止、工作目录、分组、CI 缓存/权限、hook 固定版本和 renv 引导版本。

- [x] **步骤 2：配置 pre-commit**

`.pre-commit-config.yaml` 固定 ruff 与基础文件检查版本；不自动提交修复。运行：

```powershell
uv run pre-commit install
uv run pre-commit run --all-files
```

预期：全部 hook 通过。

- [x] **步骤 3：创建 GitHub Actions**

CI 使用 Windows 和 Ubuntu Python 3.12 矩阵执行 Python 静态检查和 Mock 测试；独立 Ubuntu job 安装 R、恢复 `renv.lock`、运行 testthat 和 DESeq2 集成测试；端到端 job 不读取 Secrets。缓存键分别使用 `uv.lock` 和 `renv.lock` 哈希。

实现补充：独立 `r-e2e` job 合并真实 R 与端到端验证，设置 `R_LIBS` 以供独立 attempt 目录下的 RRunner 使用。工作流仅有 `contents: read` 权限，checkout 不保留凭据。远端运行在任务 15 推送后验收，本任务不推送。

- [x] **步骤 4：运行本地完整检查**

运行：`powershell -ExecutionPolicy Bypass -File scripts/check.ps1`

预期：ruff、mypy、pytest、testthat 均退出 0。

- [x] **步骤 5：Commit**

```powershell
git add .github/workflows/ci.yml .pre-commit-config.yaml scripts/check.ps1 tests/unit/test_check_script.py r/dependencies.R renv.lock docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "ci(任务14): 添加跨语言测试与安全门禁"
```

### 任务 15：完成 README、演示和发布验收

**文件：**

- 修改：`README.md`
- 创建：`docs/getting-started.md`
- 创建：`docs/architecture.md`
- 创建：`docs/demo.md`
- 创建：`docs/assets/demo.gif`
- 创建：`SECURITY.md`
- 创建：`LICENSE`
- 修改：`.gitignore`、`.github/workflows/ci.yml`（远端 R fs 系统依赖修复）
- 修改：`renv.lock`（保留包版本，规范 Bioconductor 仓库字段以通过跨平台严格恢复检查）
- 用户实际启动故障修复：`src/bioagent/llm/factory.py`、`src/bioagent/llm/planner.py`；对应 `tests/unit/llm/test_factory.py`、`tests/unit/llm/test_planner.py`、`tests/evals/test_planner_cases.py`、`tests/e2e/test_bulk_workflow.py`，显式 function calling 并关闭 DeepSeek thinking，修复真实 HTTP 400 造成的无计划 409。
- 用户 shrink=true 质检故障修复：`r/deseq2/functions.R`、`r/tests/testthat/test-deseq2.R`、`tests/e2e/test_api_release.py`、`src/bioagent/reporting/templates/report.html.j2`；保留原始 Wald 检验列并明确收缩后效应量的语义，验证两条 shrink 路径。
- 发布验收必要修复：`src/bioagent/reporting/workflow.py`、`src/bioagent/workflow/graph.py`、`src/bioagent/api/dependencies.py`、`src/bioagent/api/routes.py`、`src/bioagent/execution/controller.py`、`src/bioagent/storage/runs.py`
- 对应回归：`tests/e2e/test_api_release.py`、`tests/unit/reporting/test_workflow.py`、`tests/integration/api/test_artifacts.py`、`tests/integration/api/test_runs.py`、`tests/unit/execution/test_controller.py`、`tests/unit/storage/test_runs.py`、`tests/unit/test_check_script.py`（远端 Windows UTF-8 读取修复）

验收发现原报告节点尚未接入生成器、manifest 不可下载，以及报告发布前恢复假成功和 Windows 索引读写竞争；上述修复仍属任务 15 已批准的发布验收范围，不增加分析类型。README/GIF 如实标记当前手工审批尚未完成。


- [x] **步骤 1：编写面向招聘者的 README**

README 依次包含：一句话价值、实际文件 `docs/assets/demo.gif`、核心能力、架构 Mermaid、科学边界、安全边界、快速开始、DeepSeek/Ollama 配置、运行测试、示例产物、路线图和许可证。`docs/demo.md` 记录 GIF 的录制步骤和命令；不得宣称未通过验收的功能。

- [x] **步骤 2：编写可复制的启动文档**

`docs/getting-started.md` 给出 Windows 与 Linux 的 uv、Python 3.12、R、renv 安装和启动命令：

```powershell
uv sync --frozen --dev
Rscript -e "renv::restore()"
Copy-Item .env.example .env
uv run uvicorn bioagent.api.app:create_app --factory --reload
uv run streamlit run ui/streamlit_app.py
```

- [x] **步骤 3：编写架构、安全与演示文档**

`docs/architecture.md` 说明责任边界、状态机和 provenance；`SECURITY.md` 说明无任意代码执行、上传限制、密钥报告方式和非临床用途；`docs/demo.md` 使用固定 fixture 完整走一遍上传、审批、运行、QC 和下载。

- [ ] **步骤 4：执行发布级验证**

运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
git diff --check
git status -sb
```

手工验收：在无 DeepSeek Key 时完成 Mock 演示；关闭 API 后 Streamlit 显示可操作错误；下载包能在新临时目录核对全部 SHA-256。用户于 2026-09-08 明确决定先跳过真实模型 API 实验、后续自行接入，因此真实 DeepSeek 结构化计划联调移至后续，不再阻塞本阶段。

预期：自动检查全部通过；本阶段保留的手工验收 3 项均通过；Git 状态只包含本任务计划列出的文件。

当前：本地流程已接通并通过自动门禁，后端关闭提示已通过真实浏览器验收。Mock 手工演示停在审批门，具体审批被自动审查拒绝；新目录手工下载验收和审批后 GIF 尚未完成。真实模型联调按用户决定延后，不再要求 Key。步骤 4 不勾选，不能用自动测试替代剩余真实手工验收。


- [x] **步骤 5：Commit**

```powershell
git add .github/workflows/ci.yml README.md docs/getting-started.md docs/architecture.md docs/demo.md docs/assets/demo.gif SECURITY.md LICENSE .gitignore src/bioagent/reporting/workflow.py src/bioagent/workflow/graph.py src/bioagent/api/dependencies.py src/bioagent/api/routes.py src/bioagent/execution/controller.py src/bioagent/storage/runs.py tests/e2e/test_api_release.py tests/unit/reporting/test_workflow.py tests/integration/api/test_artifacts.py tests/integration/api/test_runs.py tests/unit/execution/test_controller.py tests/unit/storage/test_runs.py tests/unit/test_check_script.py docs/superpowers/plans/2026-08-15-bio-agent-mvp.md docs/progress/current-state.md
git diff --cached --check
git commit -m "fix(任务15): 接通报告发布并补齐发布文档"
```

- [ ] **步骤 6：推送分支并创建 Draft PR**

运行：

```powershell
git push -u origin agent/bio-agent-mvp
gh pr create --draft --base main --head agent/bio-agent-mvp --title "feat: 完成 Bio-Agent bulk RNA-seq MVP" --fill
```

预期：GitHub 创建 Draft PR；CI 全部通过且手工验收完成后再考虑 Ready for review，不直接合并失败的检查。

已创建 [Draft PR #1](https://github.com/zzj1174949411/bio-agent/pull/1)。首次远端 Windows CI 暴露测试默认编码问题，修复后 Windows/Ubuntu Python 均通过；R 恢复进一步暴露 fs 缺少 libuv 系统依赖，已补齐。随后 PR Windows 的后台完成测试超出两秒预算；延迟实验确认任务仍正常完成，改为 30 秒有界等待后实验和 23 项 API runs 回归通过。步骤 6 在最新提交全部 CI 通过前保持未勾选。

R 安装修复后的严格状态检查发现 16 个 Bioconductor 包残留镜像 Repository 字段；已规范为 Bioconductor 3.22，保持版本不变。本地 15 项门禁测试、restore 和严格 status 通过，继续核验最终远端结果。

当前远端仍为 `c4f0960`；本地 `5ffc51d`、`caeb339` 的推送在重新核验自有私有仓库与 ADMIN 权限后仍被自动审批审查拒绝，等待用户明确授权该目的地和待推送提交。未绕过，步骤 6 继续未勾选。

## 3. 规格覆盖矩阵

| 设计规格 | 实现任务 |
|---|---|
| 目标、原则、MVP 范围 | 任务 1、15 |
| 总体架构与责任边界 | 任务 6–12 |
| 用户流程 | 任务 8–12 |
| 输入数据契约 | 任务 3 |
| 分析计划契约 | 任务 2、7 |
| Tool Registry 与执行控制 | 任务 5、6、9 |
| 状态与错误恢复 | 任务 2、8、9、13 |
| Artifact 与 provenance | 任务 4、6、9 |
| 报告设计 | 任务 11 |
| API 与界面 | 任务 10、12 |
| 安全边界 | 任务 3、4、6、9、10、14 |
| LLM 接入 | 任务 7 |
| 工程结构 | 任务 1–15 |
| 测试与评测 | 每个任务的 TDD 步骤、任务 13–14 |
| 8 周交付与公开发布 | 任务 1–15 |

## 4. 8 周执行映射

| 周次 | 任务 | 周末可运行结果 |
|---|---|---|
| 第 1 周 | 任务 1–2 | Python 3.12 工程、强类型计划和状态模型 |
| 第 2 周 | 任务 3–4 | 可上传、校验并生成安全运行目录的数据核心 |
| 第 3 周 | 任务 5–6 | 不依赖 LLM 的 DESeq2 端到端执行与 QC |
| 第 4 周 | 任务 7–8 | 可生成计划、暂停审批并恢复的 Agent |
| 第 5 周 | 任务 9–10 | 后台执行、幂等控制和完整 API |
| 第 6 周 | 任务 11–12 | 报告与 Streamlit 演示闭环 |
| 第 7 周 | 任务 13–14 | Agent eval、恢复测试和 GitHub Actions |
| 第 8 周 | 任务 15 | 招聘者可阅读、可运行、可演示的 GitHub 项目 |

## 5. 最终完成条件

- `powershell -ExecutionPolicy Bypass -File scripts/check.ps1` 退出码为 0。
- 固定端到端数据产生 DESeq2 结果、4 类图、QC、日志、报告和 manifest。
- 未审批、不支持、提示注入和非法 schema 场景的 R 调用次数为 0。
- 同一输入、计划和环境的统计结果可复现，比较方向始终一致。
- GitHub Actions 在没有任何 LLM Secret 的情况下通过。
- README 的每条功能声明都有测试或演示证据。
- Draft PR 的自动检查全部通过，且没有把 `.env`、运行数据、API Key 或本地参考文件提交到 Git。

## 6. 执行参考

- [uv Windows 安装](https://docs.astral.sh/uv/getting-started/installation/)
- [uv Python 版本管理](https://docs.astral.sh/uv/guides/install-python/)
- [uv packaged application](https://docs.astral.sh/uv/concepts/projects/init/)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [DeepSeek API](https://api-docs.deepseek.com/zh-cn/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [Streamlit testing](https://docs.streamlit.io/develop/api-reference/app-testing)
- [DESeq2 官方手册](https://bioconductor.org/packages/release/bioc/manuals/DESeq2/man/DESeq2.pdf)
- [renv restore](https://rstudio.github.io/renv/reference/restore.html)
