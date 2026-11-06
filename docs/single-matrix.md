# 单表达矩阵到双组 DESeq2（任务48）

在已有聊天选择模型后，点输入框“＋ → 上传单表达矩阵”。只需一份 UTF-8 CSV/TSV，不要求事先把ID列命名为feature_id，也不用另制metadata。

1. 上传后在对话查看原始哈希、行列数、表头及前五行。确认行是基因还是样本；行是样本时可显式转置。选择基因ID列，去掉注释列或不纳入样本的勾选。
2. 逐个填写纳入样本的条件名称，指定实验组相对对照组。必须恰好两组、每组至少两个样本。系统不会从列名猜分组。ID不能空/重复，当前接受字母、数字、下划线、点、冒号、竖线、加减号，不做基因ID映射。
3. 明确数据类型为未归一化raw counts，填写来源/处理历史及研究要求。整数外观不证明raw；TPM/FPKM/log/未知不能取整进入DESeq2。数值必须有限、非负整数且不超过R integer上限；NA、小数和代码文本拒绝。
4. 点“确认分组并生成待审批方案”。服务端生成标准counts和metadata，加入本聊天并使用所选模型的Planner创建既有分析计划；会再次确定性核对dataset及比较方向。模型改变已确认方向会失败，不能静默执行不同比较。
5. 审阅真实比较和参数，勾选确认后明确批准，才会进入原Rscript/DESeq2。拒绝/停止运行仍使用原取消接口。结束后消息显示真实状态、QC、图表、结果表和报告；点文件在右侧阅读。单矩阵卡还提供从已校验结果表计算的摘要及“继续追问本次结果”，将实际摘要放入草稿，用户可编辑后发送。

确认记录不可原位修改；改变列/分组/来源需取消旧待审批方案后重新上传形成新确认，不能复用旧批准。完全相同确认重复请求返回同一dataset/run，不同payload或旧revision稳定拒绝。草稿原始bytes、哈希、确认JSON、生成counts/metadata哈希、dataset/turn/run关联保存在本地`matrices.sqlite`；已确认状态切聊天/重启后可恢复。未确认的本地表单编辑不宣称已保存，刷新需重新填写。

原始上传以SQLite独立保留；run manifest继续保存规范counts/metadata输入哈希，审计记录把原始SHA与这些哈希、run关联。当前没有原始矩阵单独导出/跨机备份包；保留data目录才能追溯完整来源。旧成对导入在“＋ → 导入分析数据”中继续可用，GEO/知识库流程不变。矩阵不会加入文献索引。

上传沿用10MiB、100000行、10000列与10秒解析限制。解析/转置在固定spawn worker中执行，512MiB RSS采样限制；超时终止worker，转置后同样限制列数。大结果通过有界临时JSON传递，只在Pipe传递小状态，拒绝超过100MiB输出；这不是操作系统安全沙箱。规范化逐行检查期限，再复用原DatasetImportService的有界验证与科学QC。HTTP保持Host/Origin/CSRF，矩阵读写绑定owner及聊天，API不接收服务器路径或代码。

API入口为 `/api/v1/workbench/conversations/{chat}/matrices`，POST multipart `file`上传，GET恢复最近草稿；`/{id}?direction=genes_rows|samples_rows`预览；`/{id}/confirm`接受revision/direction/id_column/sample_columns/groups/numerator/denominator/data_type/source/goal/profile_id；`/{id}/results`只从该确认所属的实际完成run计算结果摘要。错误为`detail.code`，没有证据时不伪造分析结论。

验证命令、合成真实R一致性结果和局限见任务48计划及复核记录。自动模型为Mock，真实统计只用合成counts；不代表真实模型、公开研究设计或任意任务Agent已验收。FASTQ、其他统计、配对/协变量、TPM差异分析、富集和通用附件均不在本任务范围。
