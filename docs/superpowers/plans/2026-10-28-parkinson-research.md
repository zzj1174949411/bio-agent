# Task51 帕金森科研深化分析计划

> 用户明确选择“深入科研结果：再做协变量校正、质量敏感性和通路分析”。使用 statistical-analysis、scientific-critical-thinking、pathway-enrichment、writing-plans 与完成前验证；两个独立分工负责只读方法审查、官方注释/Reactome及离线ORA。父窗口唯一Git索引/提交者。

**目标：** 对Task50同一GSE205450尾状核63供者研究，区分原始差异、协变量调整和质量敏感性下仍保留的信号，并给出可核验基因与通路结果。

**架构：** 一次性科研分析脚本及ignored data/task51产物；不改变生产MVP的双组DESeq2契约、工具目录或审批逻辑，不接入新统计功能。用户本轮对科研方法的明确授权优先于此前停止51/不做新统计的交接。保留Task50全部原始数据/run/模型回复。无需新付费LLM请求，不读凭据、不使用旧额度，不安装/升级依赖。

**技术栈：** 已有Rscript/DESeq2/jsonlite/ggplot2，Python uv/pandas/numpy/scipy，官方NCBI/Reactome静态资源，R base图或ggplot2。无FASTQ、单细胞、任意用户代码或临床诊断。

## 文件分工与门禁

- 父：`scripts/parkinson_models.R`（固定科研设计、DESeq2/诊断）、`scripts/parkinson_research.py`（输入hash核验、模型比较、注释/ORA、报告）、`scripts/parkinson_figures.R`（统计产物绘图）、`tests/unit/test_parkinson_research.py`、`r/tests/testthat/test-parkinson-research.R`、本计划、current-state和`docs/reviews/2026-10-28-task51-research.md`。
- 注释分工独占：`scripts/parkinson_functional.py`、`tests/unit/test_parkinson_functional.py`、ignored `data/task51/resources/`。先离线红灯再实现；只用官方资源，版本/URL/时间/hash可查，原资源不提交。
- 方法审查只读；不跑R、不写Git或源码。所有写者停写后父复验和提交，不并发改共享索引。

## 本轮分析前固定的比较

这是基于既有结果/QC后提出的探索性分析，非预注册确认性研究。以下规则在查看新的调整模型结果前固定，不按显著基因多少挑模型或样本。

1. 原始复现：全63，`~condition`，沿用默认DESeq2与alpha .05/no shrink/seed42；与Task50结果按ID对齐比较数值容差rtol1e-8/atol1e-10。
2. 递进调整：全63，`~age_z+sex+condition`；再加`rin_z`；主模型再加`pmi_z`。所有连续变量从全队列中心/标准化，PD相对Control。核实无缺失、满秩、条件数、协变量分布/病例对照支持范围。疾病持续时间、痴呆和用药为疾病后变量且对照中未定义，不盲目调整。
3. 主模型质量敏感性：预定RIN>=5（48人，PD21/Control27）及>=6（42人，PD18/Control24），保留同一公式。
4. 主模型附加影响诊断：年龄共同范围65..90；以及只移除预先识别的唯一PMI45小时样本GSM6212963。不是根据DE或PCA极端程度自动删样本，完整样本主分析始终保留。
5. Cook机制对照：原默认双组允许离群计数替换，而连续协变量模型机制不同。单独追加unadjusted与full两模型统一`minReplicatesForReplace=Inf, cooksCutoff=FALSE`，核对同处理下的变化；清楚标为补充影响诊断，不把关闭保护后的结果冒充稳健验证。每模型导出replace/NA/maxCooks/filterThreshold信息。

共10个固定拟合，串行执行。主结果使用默认full；其它均敏感性/诊断，不将最显著一个称“最佳”。RIN可能是技术混杂，也可能与疾病/组织退变相关，调整可能过度；并列报告。

## 结果与通路

- 样本QC：库大小、检测基因、size factors、VST PCA/解释方差、PCA与年龄/RIN/PMI/文库大小的探索性相关、Cook距离/杠杆值。人口学描述不混称临床效应。
- 模型对比：每模型上/下调、有效padj与过滤、LFC相关/方向、显著集合重叠；同时报告共同finite padj范围内的比较，避免把过滤阈值变化当生物学差异。主模型效应量/95% Wald区间与完整统计CSV、排名及重点PD基因表。
- 注释：保留Entrez ID为主键，符号/名称/类型为查得注释；重复符号不合并，未映射和撤销ID明确记录。重点面板在查看结果前固定SNCA/LRRK2/PRKN/PINK1/PARK7/VPS35/GBA1，以及TH/DDC/SLC6A3/SLC18A2等表达展示；遗传风险不等于该脑区RNA必须差异。
- Reactome ORA：人类、Entrez、主模型上/下调分别分析；候选背景为本模型finite padj且可Reactome映射的基因，通路背景内size10..500，全部eligible term包括零重叠一起做BH，方向为独立检验族。另在跨模型共同背景中核查通路稳定性。保存完整表、重叠基因、背景和资源版本/hash，不声称GSEA、通路活性或因果；通路冗余只作展示去重、不删除检验结果。
- 生成可读多图HTML/Markdown报告、模型/质量/基因/通路CSV和独立artifact hash清单；旧统计/图/报告不覆盖。

## 顺序与验收

- [x] 编写并运行离线失败测试：元数据缺失/重复供者/设计秩、固定质量阈值、ID对齐比较、ORA/BH/背景契约；只对实际方法边界测试，不依赖真实Key或公网CI。
- [x] 核验已有输入/源hash并下载官方注释与Reactome快照；冻结新分析设计和审计。
- [x] 真实R串行拟合与原始数值复现通过；完整导出诊断，失败不伪造或自动换方法。
- [x] 完成注释、主模型/敏感性/共同背景ORA与生物学复核，目视图表，记录保留和不稳定信号。
- [x] 父独立检查原输入/结果与全部登记hash、测试与全仓静态/八hooks/cached门禁；更新进度/计划并明确暂存本任务文件，本地提交，不push/merge。

保留用户renv SHA256 `A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`，不动用户8000/根runs/旧模型台账，不自行新增52。
