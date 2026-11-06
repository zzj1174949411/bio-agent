# Task51 帕金森科研深化：父窗口验收

状态：真实分析与独立数值/科学/图表验收及最终Git门禁通过；本地提交号与提交后状态以Git日志为准。

## 授权与范围

用户在“多分析一些”后明确选择“深入科研结果：再做协变量校正、质量敏感性和通路分析”。这授权同一GSE205450队列的一次性科研扩展，不更改生产MVP双组统计契约。保留Task50真实DeepSeek/run；本轮不追加模型请求、读取Key或操作旧额度。没有依赖安装/升级、FASTQ、产品新统计、push/merge。

使用既有worktree/agent分支，基线8dd8b9e。父唯一Git提交者；一分工独占注释/ORA模块与资源，另一分工只读独立核查实际CSV，父做模型/报告。用户原renv改动保留，不加入任务。

## 固定设计与真实执行

- 新模型前写明10个公式/样本规则：全63原始、年龄/性别、再加RIN、主full再加PMI；同full公式的RIN≥5/≥6、年龄65–90、只移除唯一PMI45样本GSM6212963；另外双组/full统一关闭Cook替换和筛查的机制对照。探索性分析，非预注册；不按新结果挑模型或删点。
- 对照32、PD31，CAU63唯一供者；连续变量以全队列标准化，固定PD/Control、alpha .05、不收缩、不设倍数阈值，各子集仅去全零。full设计满秩6/6、条件数4.1262；所有协变量完整。RIN阈值子集48/42人；共同年龄54；PMI删除62。
- 原输入counts SHA a091e0602763c5fd3152f02ab50b05943e4d5e3495ca649ef717ab9cd09535c4；使用Task50审核后的完整metadata SHA f3daff8903294e1af1c0570629edcc4bb227cb271671f126984632e1d9b5e030。预先input-audit及后续逐文件核验保留在ignored data/task51。
- 真实Rscript串行10拟合退出0；产物data/task51/models-20261028。原始38937行按ID对齐，LFC/p/padj最大差均0。原Task50结果SHA7af6ee8367e49c64ec94997b515947af1bce9ca3f2b884b9a2a498eef7a3e541未变。

| 模型 | n | 上调 | 下调 | finite padj |
|---|---:|---:|---:|---:|
| 原双组 | 63 | 4127 | 4166 | 28365 |
| 年龄/性别 | 63 | 3956 | 3740 | 28255 |
| 再加RIN | 63 | 2327 | 2232 | 26858 |
| full主模型 | 63 | 2100 | 1955 | 26858 |
| RIN≥5 | 48 | 2411 | 2207 | 27521 |
| RIN≥6 | 42 | 1981 | 1930 | 25986 |
| 年龄65–90 | 54 | 2636 | 2656 | 26774 |
| 移除PMI45 | 62 | 2107 | 1889 | 26841 |
| 双组统一Cook | 63 | 4137 | 4164 | 28368 |
| full统一Cook | 63 | 2100 | 1955 | 26858 |

## 独立数值与方法复核

- 只读分工独立对全部十组CSV验证：full4055显著，四敏感性同向且各FDR≤.05交集2681（上1404/下1277）；4055主显著方向全保持。五模型共同finite范围25956。主结果无倍数门槛；|LFC|≥1的637只作补充描述。
- full与RIN5/RIN6/年龄/PMI的共同finite背景26729/25970/26672/26827，显著同向交集3486/2888/3663/3915；Spearman .9637/.9286/.9605/.9986。RIN6有39个主显著失去finite padj，不能误算成方向反转或假阳性。
- PMI删除对主显著LFC绝对变化中位.00429/95%分位.03456，未见单一样本主导总体结果；仍不是证明没有影响或完全稳健。
- 原默认双组359个基因替换异常计数；连续协变量full未替换。两统一处理full逐值相同，双组74个跨FDR/357个|ΔLFC|>.1。Entrez3067默认双组−1.63363→full+2.92355，看似唯一两者显著且反向；但它原先replaced=True，统一双组+2.46723且RIN5/6 FDR .0948/.1475，因此不能宣称协变量造成生物学反转。
- full gene_diagnostics.max_cooks来自DESeq2自动筛查字段，可为空；另从保存的dds cooks assay导出raw最大值，不能把NA当无高Cook。样本原始Cook/杠杆值已单独导出。
- RIN可能既是技术变量也是疾病组织相关变量，显著数减少不等于清除假阳性；bulk组织组成、未测混杂、选择覆盖偏倚和独立验证缺失均保留。VST PCA不是协变量残差PCA。

## 来源覆盖

官方NCBI119/150矩阵；CAU75原样本中缺Control8/PD4。缺失Control年龄中位74.5、可用68.5；缺失PD RIN4.9、可用6.1，不假定随机缺失。原SOFT的同供者PD_10另一脑区PUT GSM6212998记Control、CAU GSM6212997记PD；所选CAU未受该跨脑区冲突影响，未自动更改或混入PUT。

原论文：https://www.nature.com/articles/s41467-023-39652-6；官方GEO：https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE205450。作者Salmon/limma/GSVA与本轮NCBI HISAT2/featureCounts/DESeq2/Reactome ORA不同，不称精确论文复现或独立队列验证。

## 官方注释与Reactome

- GRCh38.p13静态注释首次ConnectError、加GSE参数后HTTPError；官方human gene_info首次SSL失败，重试HTTP200。采用当前官方NCBI Gene快照，Last-Modified 2026-10-27，194025唯一Entrez、5199342 bytes、SHA8a1c9ab8b86a1b924d0af9e48ddd818f2d715857212d474a318eb8026585f17b。不是原始p13冻结注释，不改原始计数或统计；38937行中37227获得注释、1710保留未映射ID。11预定面板均映射，符号重复不合并。
- Reactome接口下载前后均98；全表97248132 bytes、SHA272ca73c16eb285be1698e07c81912335a1d3804e125f789f5160dff150be243。实际全表首次直接导入红灯REACTOME_HUMAN_ID_INVALID，父核实224个人类行是22种序列accession，不能当Entrez。原行另存，明确派生人类Entrez表157414行/11470基因/2861通路、18891247 bytes、SHA769e5efc33088ef388e1205bc3023abf17b93a593fb520811d1f7d81d3f62936，过滤过程/hash审计完整。
- native主背景9978个finite padj且Reactome可映射基因，上/下候选746/1000；各1687条eligible通路包含零命中，BH后103/154。八模型共同背景9877、各1681通路，上/下独立族；主full与四敏感性均达FDR的条目73/12，层级重叠不当独立机制。
- 六个解释例子在看结果后选取，不缩小检验族：金属离子响应、染色质组织、HSF1依赖转录，及较低的有氧呼吸总通路、突触后信号、胆固醇合成；native/common口径分别注明。呼吸总通路68/257、native q3.798e-11，RIN6共同q8.98e-4；突触后34/197、native q.01574、RIN6共同q2.93e-7。若干蛋白酶体子条目RIN6不再达FDR，不泛称所有下调条目稳健。
- 11个预定PD面板主模型全部未过FDR；SNCA q.1665、TH .05585、LRRK2 .06275，未借名义p或95%区间冒充全基因显著。HSPA6/HSPB1/HSPA1A/HSPA1B四敏感性均显著同向；HSPA6 LFC3.4825（约11.2倍）是可跟进的应激关联，不声称PD特异或因果。CD274基因本身q.2854，即使其命名通路显著也不能称CD274上调；HIV/SARS条目不当感染证据。

## 产物与独立验收

- 完整结果在ignored `data/task51/research-20261028/`：自包含`parkinson-research.html`、Markdown、人工审核的interpretation.md、基因/11基因面板/逐模型稳定性/QC/来源覆盖/18组ORA/代表通路/背景CSV和artifact_manifest。R模型/原始诊断在`data/task51/models-20261028/`；R sessionInfo与Python runtime版本均记录。
- 7组PNG/PDF：质量分布、VST PCA、模型/敏感性、效应量/火山、PD面板Wald区间、30基因热图、Reactome。父逐一目视；发现火山图NA行影响坐标范围、热图标题和长通路标签裁切，修正只绘finite padj、设置边距/换行/图例后重新绘图再目视。未重拟合模型、删除基因或改阈值。
- 两路独立科学/方法审查先后核验全部统计与实际注释，最终HTML/Markdown/解读数值通过；未发现高可信阻断问题。审查覆盖模型与ORA脚本、实际表及3类图；父另看全部7图。
- 父ignored `data/task51/verify_final.py`独立使用SciPy hypergeom和false_discovery_control（不调用产物ORA/BH实现）复算18个检验族全部p/q/重叠成员/背景集合、10模型和全部144登记产物hash、资源实际hash、11面板、7PNG/PDF，退出0。第一版探针误要求原表行序相同，先断言失败；改为按ID排序后逐列严格0容差一致，再通过；不是修改统计以迎合探针。另一审查独立复算native全部p/q最大差3.33e-16。

## 测试与门禁

- Python原比较/ID/方向红灯为模块不存在，随后3项通过；新input hash冻结红灯为ImportError（verify_inputs缺失），实现后4项通过/1.85s。
- R元数据缺失/重复供者、秩与固定阈值测试：3 tests/8 assertions通过；使用test_file结果failed/error显式断言，避免R test_file仅打印失败仍exit0。
- ORA模块红灯ModuleNotFoundError后，实现与边界扩展最终13项通过；父增加共同背景/Entrez保留/阈值等号跨模块测试。最终`uv --cache-dir data/task48/uv-cache run --no-sync --offline pytest tests/unit/test_parkinson_live.py tests/unit/test_parkinson_research.py tests/unit/test_parkinson_functional.py -q -p no:cacheprovider --basetemp data/task51/final-regression --tb=short`：**30 passed in3.34s**。最终R新文件**3 tests/8 assertions/0 failures/0 errors**。
- 全仓Ruff通过（旧pytest目录ACL warning保留）；裸`mypy`按packages配置发现安装包py.typed不可用，未改生产配置；按仓库已用命令`mypy src/bioagent`为**114 source files通过**。R保留Windows locale及包构建版本warnings，真实拟合和绘图均退出0，无隐藏失败或自动换法。
- 复跑顺序：先固定输入审核；`Rscript --vanilla scripts/parkinson_models.R data/task50/live-20261026-03/matrix-upload.tsv data/task50/review-20261026/samples.csv NEW_MODELS`；然后`uv run python scripts/parkinson_research.py --models NEW_MODELS --annotation data/task51/resources/Homo_sapiens.gene_info.gz --reactome data/task51/resources/Reactome98_Homo_sapiens_entrez.tsv --resource-audit data/task51/resources/resources-audit.json --output NEW_ANALYSIS`；`Rscript --vanilla scripts/parkinson_figures.R NEW_MODELS NEW_ANALYSIS`；可加入审核解读文件后同一Python命令仅保留models/output并加`--finalize`。R设置RENV_CONFIG_AUTOLOADER_ENABLED=FALSE及既有R_LIBS；Python按上述uv离线环境。新模型/分析目录必须不存在，报告finalize只写新分析目录，不覆盖Task50。
- 最终明确暂存10份Task51源码/测试/审查/进度文件，八项pre-commit全仓hooks全部Passed，`git diff --cached --check`退出0；默认沙盒缓存数据库/索引不可写，按工具升级权限后成功，未改变检查内容。renv SHA仍A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A，未入暂存。研究数据、下载、运行产物和模型原记录不入Git，不自动新增52。
