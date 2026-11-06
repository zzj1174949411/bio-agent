# GEO GSE 数据接入设计

**状态：** 属于用户已确认的工作台第二阶段；依赖任务 21。
**实现计划：** [任务 22–27](../plans/2026-09-08-geo.md)。

## 1. 成功流程

用户输入 GSE 编号或含一个 GSE 的自然语言目标 → 检索系列/样本元数据 → 列出可下载矩阵 → 用户选择候选并确认下载 → 下载与表头预览 → 用户确认样本映射和分组 → 确定性转换与 Dataset 验证 → 生成计划 → 用户批准 → 原 DESeq2/QC/报告。

支持 `GSE[1-9][0-9]*`，去除首尾空白并转大写；不接受 URL、FTP 命令或模型生成的下载地址。多个编号需要用户选择一个。GSM/SRR/PRJNA、单细胞、芯片和 FASTQ 返回明确范围说明，不自动发起上游流程。

## 2. 检索与候选

`geo/client.py` 通过 HTTPS 获取 GEO SOFT family 元数据（不包含表达表），并读取官方附属文件链接及 NCBI-generated raw counts 可用记录。保留 accession、GSM、物种、平台、样本标题和 characteristics 的原文与字段来源，不把重复 characteristics 覆盖成一个值。

候选只支持 `.csv`、`.tsv`、`.txt` 及对应 `.gz`，且是一个完整的 gene×sample 矩阵。NCBI-generated raw counts 与提交者明确注明 raw counts 的文件可成为候选；TPM/FPKM/RPKM、归一化 counts、series matrix 芯片表达值不能通过名称匹配就作为 raw counts。

`GeoCandidate` 字段：id、source_id、accession、url、file_name、size_bytes（可空）、data_kind、evidence、compression。data_kind 为 RAW_COUNTS / NORMALIZED / UNKNOWN / UNSUPPORTED。UNKNOWN 需要用户确认数据来源类型和列映射，不能让模型仅凭数值像整数就判定可用于 DESeq2。自动推荐不等于自动批准科学分组。

第一版不解 tar/zip、不自动拼接按样本分散的文件、不从 FASTQ 计算 counts。没有支持的候选返回 `GEO_NO_SUPPORTED_COUNTS`，展示官方记录链接及原因；不承诺所有 GSE 都可分析。

## 3. 下载和资源限制

只访问 `www.ncbi.nlm.nih.gov`、`ftp.ncbi.nlm.nih.gov` 的 HTTPS 443；HTTP/FTP 链接只在同一已允许主机可确定转换为 HTTPS 时转换。每个重定向重新验证 scheme/host/IP，最多 3 跳；禁止私网、loopback、link-local 和用户信息 URL。下载器直接连接已验证地址并验证 TLS 主机，避免先检查 DNS 再用未经检查的新解析。

无 Key 的 NCBI 请求全进程最多每秒 2 次，携带应用 User-Agent。GET 的网络错误、429、502/503/504 最多重试 2 次，Retry-After 上限 60 秒；404/不支持/解析错误不重试。

默认每个原始下载文件 100 MiB、解压后 200 MiB、100000 feature、2000 样本列、解析 30 秒、连接 10 秒、读取停顿 30 秒、总下载 300 秒。预检剩余磁盘空间至少为解压上限的两倍。超出限制失败并显示限制值，不截断数据继续分析。用户确认卡显示已知大小；未知大小标记为未知且仍受流量上限约束。

写入 `.part`，流式计算 SHA-256；完成且大小/内容校验通过后原子发布。gzip 受流式展开字节数限制。取消删除本次不完整 `.part`，保留下载事件；首版失败从头重下，不宣称支持 Range 断点续传。

## 4. 转换与分组

原始源文件永不修改。先用受限解析器探测分隔符/表头，用户选择 feature 列和样本列；确定性投影到标准 `feature_id` + sample IDs，不四舍五入、不把 TPM 转 counts、不合并重复 gene、不自动删除不匹配样本。

NCBI gene annotation 不作为 counts 样本列；使用候选 schema 和明确列映射分离。GSM 与矩阵列精确匹配可自动建议；其他别名显示映射表并要求确认，一对一且不遗漏。metadata 的分组列可由模型建议，但必须显示原始证据并经用户确认。两组各至少两个样本；多组时用户显式选择纳入集合，并在来源记录保存被排除样本及选择，不能悄悄截取。

`SourceSelection` 包含 source_id、candidate_id、feature_column、sample_columns、sample_map、groups、numerator、denominator、revision。selection hash 绑定候选文件 hash 与映射，修改任何项增加 revision，旧确认 409。

标准化输出通过共享 `DatasetImportService`，保留已有上传的 10 MiB 限制；GEO 使用上述独立资源配置和相同数据校验器，不把大文件重新 POST 给自己的上传 API。用户上传行为不因 GEO 新限额而改变。

## 5. 存储和 provenance

`data/sources/<source_id>/` 保存 metadata.json、source.json、raw/ 和 normalized/。source.json 包含 accession、retrieved_at、最终 URL、HTTP ETag/Last-Modified（如有）、原始及标准化 hash、内容类型、解压方式、列/样本选择、确认时间和转换版本。

缓存键为 accession + URL + 原始 hash；命中仍验证本地字节。服务器同一 URL 内容变化建立新 source，不能覆盖旧来源。分析创建时复制已选择的标准化 inputs、source.json 和关联原始文件到 run 的受控 source/ 目录并登记 hash，下载 manifest 时可以核验来源。原始数据较大时 UI 明示完整包大小。

## 6. API 和状态

| 端点（前缀 /api/v1/geo） | 行为 |
| --- | --- |
| POST /sources `{accession}` | 202 source_id；后台检索 |
| GET /sources/{id} | 元数据、候选、错误码与状态 |
| POST /sources/{id}/imports `{candidate_id,revision}` | 202 import_id；确认下载 |
| GET /imports/{id} | 进度、预览/映射候选、状态 |
| POST /imports/{id}/selection | 保存确认后的 SourceSelection，202 验证 |
| POST /imports/{id}/cancel | 幂等取消 |

Import 状态：DISCOVERING → AWAITING_SELECTION → DOWNLOADING → AWAITING_MAPPING → VALIDATING → READY；任何阶段可 FAILED/CANCELLED。source 发现与 import 分开，READY 产生 dataset_id，不自动批准分析。

错误：GEO_ACCESSION_INVALID、GEO_NOT_FOUND、GEO_NO_SUPPORTED_COUNTS、GEO_RATE_LIMITED、DOWNLOAD_TOO_LARGE、DOWNLOAD_TIMEOUT、DOWNLOAD_HOST_REJECTED、SOURCE_CHANGED、GEO_SAMPLE_MAPPING_REQUIRED、GEO_COUNTS_INVALID。对话动作与设置页面共用同一服务，所有事件进入工作台 EventStore。

## 7. 验收

任务 22 检索与分类；23 下载和流式边界；24 映射、原始数据保护及 Dataset 入口；25 API/对话事件；26 浏览器数据选择；27 科学与来源端到端。

Mock 网络覆盖正常 SOFT、重复 metadata 字段、多个候选、TPM、FASTQ、404、429、私网重定向、超大 gzip、下载中断和缓存篡改。真实 R 使用保存的合成 counts，验证从 GSE fixture 经审批得到报告，所有 source/input/artifact hash 均一致。实际公开 GSE 烟雾测试只确认发现/下载/映射，下载前明确显示文件和大小，不依赖真实模型 Key。

## 8. 官方依据

- [GEO FAQ：processed 文件与 SRA raw reads](https://www.ncbi.nlm.nih.gov/geo/info/faq.html)
- [NCBI-generated RNA-seq counts](https://www.ncbi.nlm.nih.gov/geo/info/rnaseqcounts.html)
- [GEO 下载与格式](https://www.ncbi.nlm.nih.gov/geo/info/download.html)

NCBI 提供部分研究的 counts，不表示每个 GSE 都有适用矩阵。上述限额、确认与缓存策略是本项目的实现决定。
