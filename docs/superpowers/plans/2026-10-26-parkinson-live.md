# Task50 DeepSeek 与真实帕金森矩阵端到端验收

> 使用 writing-plans、executing-plans、database-lookup 和 verification-before-completion。用户本轮明确授权使用已配置的 DeepSeek API 分析公开帕金森数据，取代此前本轮不进入50/不调用真实供应商的停止说明；旧文献评测额度和台账不变。

**目标：** 使用真实 DeepSeek、官方公开表达矩阵、现有确认/审批 API 和真实 Rscript，给出实际结果与可复查产物。

**架构：** 保持现有产品方法，独立 ignored data/task50 存储下载、聊天、checkpoint、run、审计和结果。读取现有配置及环境/系统凭据，仅在进程内使用，不复制凭据或改用户服务。手动验收脚本不替代生产 Planner，不 Mock 任何模型响应或 R 结果；HTTP hooks 只限制本次调用次数、输出与记录非敏感计数。

**技术栈：** 现有 Python/uv、GeoTransport/GeoDownloader、FastAPI TestClient、配置式 DeepSeek、Rscript/DESeq2。无依赖升级、FASTQ、新统计方法或任意用户代码。

## 范围、文件与验收

- `scripts/verify_parkinson_live.py`：显式 `--live`、独立调用审计、固定官方来源与样本选择、真实聊天/Planner、矩阵确认/审批/产物核验和结果解释；默认不能付费调用。
- `tests/unit/test_parkinson_live.py`：离线检查样本选择禁止重复供者/跨脑区、计数类型与来源不符拒绝、调用数限额、未显式 live 不发请求。先运行失败测试，再实施脚本；不向自动测试提供真实凭据。
- `docs/reviews/2026-10-26-task50-live.md`：官方来源、样本/处理/hash、模型与调用数、实际统计/图/报告、失败与限制；仅记录本次授权。
- 本计划及 `docs/progress/current-state.md`：唯一任务50的进度与收尾，完成后作48–50复盘。本地提交，不push/merge。

检索为定向选择一个数据集，非穷尽检索。最终采用GSE205450的NCBI统一HISAT2/featureCounts raw矩阵，119/150样本覆盖；只在可用覆盖中纳入CAU63名独立供者PD31/Control32，31不可用样本及56其他脑区样本明确审计。作者Salmon counts也下载核验但未用于本轮；GSE114918作者counts仅PD，GSE90514附表log/VST，均排除。未取整TPM/FPKM/log或估计小数。固定PD相对Control、alpha=.05/no shrink/seed42，不加fold筛选或新协变量方法；年龄、性别、RIN、样本覆盖和组织组成的未调整限制已写明。

- [x] 核实原始矩阵、官方处理历史、样本设计/独立性、具体纳入排除与下载SHA256，保存审计；CPU单数据集串行，资源探针备用读可用内存14.32GiB/磁盘62.09GiB。
- [x] 离线红灯后实现专用可复跑脚本，常规CI保持离线；显式live前不产生供应商调用。新增配置选择与人口学标签回归均先红灯。
- [x] 在隔离应用中复用当前DeepSeek配置，最多12次请求、每次输出最多1800 tokens、合计消息输入最多300000 UTF-8 bytes；实际累计5次/16308bytes，成功链路3次。不使用/重置旧49/50文献额度。不把byte限额称为token/费用保证，不保存HTTP鉴权头/密钥/私有推理。
- [x] 真实聊天讨论研究设计，人工式确认来源/分组；真实Planner生成待审批计划。输入hash、方向、参数已记录，审批前R调用0；按用户本轮分析授权批准一次。
- [x] 真实R完成，独立复算显著上/下调与有效padj、检查四图/QC/HTML报告/manifest全部24份登记hash；保留真实DeepSeek解释并作人工纠偏，没有冒充富集、因果或临床结果。审核展示图复用原R坐标和CSV，不改统计。
- [x] 离线15项/Ruff/mypy114及8hooks通过，真实结果与局限、48–50复盘已记录；明确暂存5份任务文件，收尾执行cached检查并本地提交，提交号/最终状态以Git为准。保留用户renv原SHA256，不动用户8000、根runs、旧台账。
