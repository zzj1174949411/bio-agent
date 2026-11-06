# 文献评测协议

`example.json` 是两题合成契约示例。UUID/hash 为占位值，Beta 12.5 mg 为合成数据，不是专家论文标注，不用于真实质量结论。默认 dry-run 只读这个 JSON，不访问 API、PDF、模型或凭据。

正式集使用 `kind=formal`：同一批经授权文献、60题、六类各10题，预先锁定开发15/保留45。六类为 `single_fact`（单篇事实）、`table_numeric`（表格数值/单位）、`cross_paper`（跨文献比较）、`method_synthesis`（概念/方法综合）、`conditions_conflict`（条件差异/候选矛盾）、`unanswerable`（库内无答案）。覆盖中文问题与英文文献、图注/OCR；不要求尚未实现的视觉推理。初始语料目标10–20篇，代表性限制需记录。

每篇冻结 base/document ID、原文 source_sha256、parse/index revision。每题记录唯一 ID、split/category、question、answerable、人工核对的 reference_claims、local-evidence.v2 reference_evidence 和 rubric。正确证据要含 PDF 页、element/chunk ID 与 chunk SHA256；原文哈希和 chunk 哈希含义不同，不可互换。answerable=true 必须有参考事实与证据；无答案题二者为空，rubric 说明拒答依据。`extra=forbid`，重复 ID/问题文本、跨 split 重复、证据所属/revision 不符、正式集数量不符均拒绝。

标注者逐条核对必需事实、实验条件、数值/单位、可接受限定与原文页；至少由另一人工复核争议。锁定 JSON 后不根据保留集结果改题或调参；修改须建立新的 dataset_id，并报告新协议 hash。语义等价改写仍需人工检查，程序去重不证明没有泄漏。

生成请求仅有问题、冻结语料和生成控制，无参考答案。Wiki 构建输入导出仅包含 corpus，无任何开发/保留问题或答案；评测答案不得回写 Wiki。模块仍只支持 rag，wiki/hybrid 将明确报 MODE_NOT_IMPLEMENTED。

正式语料、标注、逐题答案、盲评和报告保存到 ignored `data/`，不提交文献或专家数据。运行、预算限制、人工盲评与配对命令见 [使用说明](../../docs/knowledge-evaluation.md)。
