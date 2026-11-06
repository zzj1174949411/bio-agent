# GEO 数据接入

工作台支持从关键词或一个明确的 `GSE[1-9][0-9]*` 编号开始。关键词搜索只调用官方 NCBI GEO catalog：用户或受限 `dataset_search` 动作可提供关键词，并可选物种、组织、测序技术筛选；每页最多 20 条、全部快照最多 100 条，下一页只能使用服务端签发且绑定 query hash 的游标。标题、摘要和 catalog 返回的其他文本都是不可信数据。

关键词结果只表示“需要检查”，不会创建 Dataset、开始下载、创建分析 run 或批准统计。研究者必须点击一个 GSE 的“检查可分析文件”，之后才进入既有精确 metadata 发现和候选文件卡。直接输入明确 GSE 仍可跳过关键词搜索，但同样不能跳过候选文件、raw-counts、样本映射和分析批准。

候选文件只在证据支持其为 gene × sample 原始 counts 时进入下载确认。NCBI-generated RNA-seq counts 和提交者明确标注的 raw counts 可以作为候选；TPM、FPKM、RPKM、normalized counts、芯片 series matrix、FASTQ 或按样本分散的文件不作为本流程输入。文件名包含 `count` 不能单独证明其类型。`UNKNOWN` 候选需要用户确认“未标准化的整数 raw counts”，然后仍需完成列到 GSM 的映射和分组确认。

映射页保留矩阵原始列、GSM、SOFT characteristics 和用户分组。用户选择 feature 列、样本列、两组、numerator/denominator 及排除样本；每组至少两个样本，比较方向显示为 numerator 相对 denominator。修改映射、来源 revision 或原始 SHA-256 后必须重新确认。标准化输入由共享 Dataset validator 检查，原始文件不会被改写。

来源缓存位于受控的 `data/sources/<source_id>/` 目录，包含 `source.json`、原始文件和标准化 counts/metadata。关键词选择形成的 provenance 包括 search ID、规范化 query hash、provider、selected accession、selection revision、检索时间和命中 evidence hash；创建 source 时必须与权威搜索仓库中短暂的 `SELECTING` 快照逐字段一致，发布时又必须与最终 `SELECTED` 快照逐字段一致。它和自己的规范化 SHA-256 才会写入 `source.json`；每次读取含 provenance 的 source 都重读权威 `SELECTED` 快照，不能把重新计算过的自洽 source JSON 当作权威。下载文件使用临时文件、流式 SHA-256 和原子发布；单文件、gzip 展开、矩阵规模、解析时间和磁盘预检均有独立上限，失败下载从头重试。缓存命中会重新核对本地字节；同一 URL 返回新内容时创建新的 source 记录。

创建分析 run 时，系统验证 source 与 dataset ID、revision 和原始 hash 一致，并将 raw、`source.json`、normalized counts 和 normalized metadata 复制到 run 的 `source/` 目录。每个副本都在 manifest 中登记 SHA-256；如果 source 有已验证的关键词 provenance，Controller 只从该 `source.json` 复制到 `RunManifest.search_provenance`。R 执行前、完成态复用及恢复会重新校验 source artifact、provenance hash，并再次与持久化 `SELECTED` 搜索快照逐字段比对；篡改 query、选择或 accession 即使重算 provenance hash 也会拒绝复用。来源记录和 source artifact 字段兼容没有 GEO 来源、也没有搜索 provenance 的旧 manifest。

结果下载先从 `GET /api/v1/runs/{run_id}/artifacts` 获取系统生成的不透明 artifact ID，再下载该 ID。接口不会把客户端提供的文件路径当作授权凭据，并会在发送前重算登记文件的哈希。完整来源 provenance 可通过 source artifacts 和 manifest 逐项离线核对。

Task27 的自动验收使用本地 synthetic family/counts fixture、Mock 模型和真实 R/DESeq2 release harness；不会访问公网 GSE 或读取真实 API Key。公开 GSE 只适合在明确候选、文件大小和映射后进行人工烟雾验证。
