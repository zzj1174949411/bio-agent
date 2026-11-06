# GEO 数据接入

工作台支持从一个 `GSE[1-9][0-9]*` 编号开始发现系列和样本信息。系统只读取 NCBI GEO 的系列元数据和附属文件目录；用户必须在候选卡上明确选择一个矩阵文件，下载不会由模型生成的 URL 触发。

候选文件只在证据支持其为 gene × sample 原始 counts 时进入下载确认。NCBI-generated RNA-seq counts 和提交者明确标注的 raw counts 可以作为候选；TPM、FPKM、RPKM、normalized counts、芯片 series matrix、FASTQ 或按样本分散的文件不作为本流程输入。文件名包含 `count` 不能单独证明其类型。`UNKNOWN` 候选需要用户确认“未标准化的整数 raw counts”，然后仍需完成列到 GSM 的映射和分组确认。

映射页保留矩阵原始列、GSM、SOFT characteristics 和用户分组。用户选择 feature 列、样本列、两组、numerator/denominator 及排除样本；每组至少两个样本，比较方向显示为 numerator 相对 denominator。修改映射、来源 revision 或原始 SHA-256 后必须重新确认。标准化输入由共享 Dataset validator 检查，原始文件不会被改写。

来源缓存位于受控的 `data/sources/<source_id>/` 目录，包含 `source.json`、原始文件和标准化 counts/metadata。下载文件使用临时文件、流式 SHA-256 和原子发布；单文件、gzip 展开、矩阵规模、解析时间和磁盘预检均有独立上限，失败下载从头重试。缓存命中会重新核对本地字节；同一 URL 返回新内容时创建新的 source 记录。

创建分析 run 时，系统验证 source 与 dataset ID、revision 和原始 hash 一致，并将 raw、`source.json`、normalized counts 和 normalized metadata 复制到 run 的 `source/` 目录。每个副本都在 manifest 中登记 SHA-256；R 执行前后及完成态恢复都会重新校验这些文件，篡改或缺失会拒绝复用。来源记录和 source artifact 字段兼容没有 GEO 来源的旧 manifest。

结果下载先从 `GET /api/v1/runs/{run_id}/artifacts` 获取系统生成的不透明 artifact ID，再下载该 ID。接口不会把客户端提供的文件路径当作授权凭据，并会在发送前重算登记文件的哈希。完整来源 provenance 可通过 source artifacts 和 manifest 逐项离线核对。

Task27 的自动验收使用本地 synthetic family/counts fixture、Mock 模型和真实 R/DESeq2 release harness；不会访问公网 GSE 或读取真实 API Key。公开 GSE 只适合在明确候选、文件大小和映射后进行人工烟雾验证。
