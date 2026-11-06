# 真实公开矩阵验收：GSE60450

本例用于检验现有非配对双组DESeq2工程链路。使用研究者提供的基因read counts，不处理FASTQ；Planner/聊天模型为Mock，统计与绘图使用真实Rscript。固定参数为Lactating相对Virgin、condition、alpha=0.05、lfc_shrink=false、random_seed=42，必须显式批准。

## 来源与适用性

[官方研究GSE60450](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE60450)比较FVB/N雌性小鼠乳腺的基底/腔面细胞与三个发育阶段，每个阶段两只小鼠。样本记录说明直接流式分选乳腺细胞，CASAVA 1.8.2 basecalling，subread 1.4.4对齐mm10/GRCm38，Rsubread featureCounts按Entrez Gene ID和NCBI注释汇总reads；文件含Gene ID、基因长度与基因read数。其raw依据来自这些处理记录，不来自整数外观或文件名。

本例只比较基底细胞的未孕与泌乳2天两个阶段，不比较同一小鼠的基底/腔面配对细胞。两个阶段来自不同小鼠，每组两个独立生物重复；不是技术重复。全部入选样本为GPL13112/Illumina HiSeq 2000，计数表所示同flowcell BC2CTUACXX、L002，官方记录同raw file batch date。生理阶段还可能伴随年龄和细胞组成差异，此简单双组分析不作因果推断。

| 官方样本 | 矩阵列前缀 | 官方条件 | 确认组 |
|---|---|---|---|
| [GSM1480297](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM1480297) | MCL1-DG | Basal virgin #1 | Virgin |
| [GSM1480298](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM1480298) | MCL1-DH | Basal virgin #2 | Virgin |
| [GSM1480301](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM1480301) | MCL1-DK | Basal 2 dL #1 | Lactating |
| [GSM1480302](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM1480302) | MCL1-DL | Basal 2 dL #2 | Lactating |

脚本逐列匹配官方Sample_description的完整名称，并核对GSM、平台、basal特征和发育阶段；不按前缀猜组。排除GSM1480291–296的腔面细胞与GSM1480299–300的妊娠基底细胞，共8个，均写入审计。`Length`是基因长度注释，不作为样本。上传保留全部原始12个样本和27,179个基因，再由用户式确认明确选择4列；不按结果删样本，不作低表达过滤、ID转换或count取整。R入口既有全零基因去除和独立过滤仍须查看日志与QC。

## 下载证据与复跑

[官方作者矩阵](https://ftp.ncbi.nlm.nih.gov/geo/series/GSE60nnn/GSE60450/suppl/GSE60450_Lactation-GenewiseCounts.txt.gz)于2026-10-23 08:38:00 UTC经既有GeoDownloader下载：513,592 bytes，SHA256 `906b6ec4c33e95ca0ba454a3e0d07ad74e9cb7528ee38b89a9b122f5674a5f0d`；仅gzip解压为1,340,161 bytes TSV。官方Last-Modified为2014-08-15 18:25:10 GMT。原始bytes未改写。

[官方完整SOFT](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE60450&targ=all&form=text&view=brief)于2026-10-23 08:35:56 UTC下载：6,981,314 bytes，SHA256 `35a1950322dccaa555d13108492ab5b981cef51b7cd2d8de59658d2051cd4549`，包含12个样本及处理历史；完整快照含平台表，因此远大于样本表。缓存及下载audit.json仅位于ignored `data/task49/research/`。固定hash不符时拒绝继续，需人工重新核查来源，脚本不会自动接受更新。

在仓库worktree运行（输出目录必须是新的，以保留旧证据）：

```powershell
uv --cache-dir data/task48/uv-cache run --no-sync --offline python scripts/verify_public_matrix.py --download --output data/task49/independent-public-check
uv --cache-dir data/task48/uv-cache run --no-sync --offline python scripts/verify_public_matrix.py --output data/task49/independent-cache-check
```

uv的`--offline`仅控制包解析，脚本的显式`--download`才授权固定官方GEO网络请求。缺缓存时默认报CACHE_MISSING，不隐式联网；缓存篡改报CACHE_HASH_MISMATCH。`--cache`可指定已核验缓存目录。首次下载使用既有DNS固定/allowlist/大小及hash受控下载，不扩大主机范围。

带`--download`时，真实HTTP API依次搜索、选择、来源发现、请求下载、人工式映射确认；原`resume_geo_ready`回调通过AnalysisService绑定来源并生成待审批run，脚本直接复用这个run，批准/状态/产物均走HTTP API。另一条路径通过真实单文件上传/分组确认API自动生成metadata与待审批run。两条路径各明确批准一次后执行真实R，比较实际结果数值；不是模拟浏览器调用R。去掉`--download`只验收锁定官方缓存经单文件API到R的路径，不宣称当次GEO联网通过。常规pytest只用小型离线fixture，不访问公开数据。

脚本核验批准前零R调用/零attempt，实际结果CSV、四类图、QC/HTML报告、manifest登记哈希及输入绑定；摘要计数从结果表复算。`acceptance.json`保存映射、排除项、输入行数、run、摘要、R调用数、联网标记和双路径数值一致性；`geo-audit.json`保存实际搜索/来源/下载/映射状态。完整科研运行位于输出目录的`runs/`。

## 解释边界

本例每组仅两个独立重复，达到现有最低要求但应显著保留样本量警告，优选更多独立样本的正式研究。比较是生理阶段差异，不能推广为治疗效应、临床结论或任意研究任务能力。双路径DESeq2数值一致是工程一致性，非独立统计金标准，也不等于复现作者论文全部模型/过滤/比较。没有真实模型、公网任意格式兼容或知识检索效果声明。具体通过结果与失败尝试见`docs/reviews/2026-10-23-task49.md`。

实际例中按所选4样本全零规则移除7,132行，保留20,047行；有效padj为16,160，上调2,794/下调2,953（padj<=0.05，不加fold阈值）。最终QC为WARN，包含全零移除数量、每组2样本及3,887个NA padj；修复后的复跑另记录pvalue缺失0个，不仅凭缺失情况归因于独立过滤。这些是当次具体数据/参数的观测，不是预设生物学真值。manifest、R stderr及报告均须保留QC证据。CSV浏览器预览在窄列中会换行，完整数值应下载核对；现有PCA长原始样本标签可能裁切，完整样本ID与坐标保留于pca.csv/来源映射，不视为投稿级排版验收。

父窗口独立实测、并行审查修复及失败复验记录见 `docs/reviews/2026-10-23-task49-parent.md`。
