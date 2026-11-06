# 本地文献 RAG 选型调研与需求记录

日期：2026-10-12。状态：选型建议与需求记录，尚未安装依赖或实现 RAG；任务 37 完成并验收后再开始 RAG 编号开发任务。

## 用户确认的要求

- 文献在本地，大多数为 PDF，包含图片和表格。
- 本地解析、本地保存原始文件、结构化结果和知识库索引。
- 问答使用工作台已配置的模型 API；知识库自身也提供检索与问答 API，供 Bio-Agent 和其他程序调用。
- 任务 37 先完成并验收，再进入 RAG 开发；沿用每模块独立任务、按编号验证和提交的方式。
- 新开发任务使用 GPT-6.1；只补关键、有意义的测试，不大量重复测试实现细节。

## 官方资料核验

以下结论来自官方仓库或官方文档，版本与输出 schema 在实际安装时仍需固定并验证。尚未对用户真实文献做解析质量比较，不能宣称任一方案在该语料上最佳。

| 项目 | 可复用部分 | 集成考虑 | 官方资料 |
| --- | --- | --- | --- |
| Docling | PDF 阅读顺序、版面、OCR、表格结构、图片/表格裁剪、结构化 JSON，可本地运行 | 优先候选；容易作为 Python 组件接入现有 FastAPI。代码 MIT，模型权重许可证另核验 | https://github.com/docling-project/docling |
| MinerU | 文档 OCR、复杂版面、表格/图像和定位信息 | 备选解析器；必须按固定版本核验安装要求和输出。官方当前许可证是基于 Apache 2.0 附加条件的 MinerU License，不能直接标为纯 Apache/MIT | https://github.com/opendatalab/MinerU |
| RAGFlow | 独立知识库服务、摄取、检索和管理能力 | 如果需要整套独立平台可考虑；其 Docker 起始推荐为 4 核、16 GB 内存、50 GB 磁盘，增加独立服务和维护负担 | https://github.com/infiniflow/ragflow |
| RAG-Anything | 基于 LightRAG 的文本/图像/表格等多模态处理框架，可配置 Docling/MinerU 等解析器 | 可参考或后续作为替代后端；引入图谱、LLM 摄取和视觉模型等额外依赖，第一版不默认整套接入；代码 MIT | https://github.com/HKUDS/RAG-Anything |
| Qdrant Python client | 本地持久化向量检索模式，不强制 Docker；后续可切换服务端 | 本地单后端进程知识库的候选，须串行管理实例生命周期；官方将 local mode 定位为开发/原型，规模增长后另行验收服务模式 | https://github.com/qdrant/qdrant-client |

关键补充官方资料：

- Docling 图像、表格裁剪及原页导出：https://docling-project.github.io/docling/_generated/examples/export_figures/
- Docling 本地预下载模型、显式启用远端服务：https://docling-project.github.io/docling/usage/advanced_options/
- Docling 本地/远端视觉增强：https://docling-project.github.io/docling/usage/enrichments/
- Docling 图片 OCR 默认不进入 HybridChunker，须显式设计图片内容的独立检索单元：https://docling-project.github.io/docling/_generated/examples/advanced_chunking_and_serialization/

## 推荐方案

优先以 Docling 作为可替换 PDF 解析组件，复用既有 FastAPI/React 工作台。原始文件和元数据存本地，分块使用章节/段落/表格/图片边界，使用本地 embedding 与关键词混合检索，再由当前轮模型根据命中证据回答。Qdrant local mode 是小规模本地索引候选；通过代表性 PDF 与真实本地依赖实验确定固定版本，再写实施计划。

备选一为 MinerU 替换解析器：主要用于经样本文献比较确认 Docling 漏读严重、版面处理不足的场景，不同时强制安装两套解析依赖。

备选二为 RAGFlow 独立服务：部署完整知识库，再接其 API。适合后续独立管理需求，但当前已有工作台和模型配置，首次集成会增加运行组件。

## PDF 内容与引用要求

- 保留原始 PDF 哈希、解析器版本、页码、区域坐标、章节、表格和图片 ID；页码统一为用户可见的 1-based PDF 页索引，另存文档印刷页码时清楚区分。
- 正文、表格结构及说明、图片/图注分别存储和检索；跨页表格保留分段页码与标题，不能丢掉表头、单位和脚注。
- 图片提取不等于视觉理解。默认不把 PDF 或图片发给云端解析/视觉服务；初始检索可使用图注及明确标记的 OCR。需要看图回答时，只有显式启用并配置视觉能力后才将命中图片发给相应模型；否则显示未进行视觉理解并保留原图入口。可选本地 VLM 的部署与硬件验收单独明确。
- 视觉生成描述必须标为派生说明，记录模型/配置 revision，不能冒充论文原文、精确图表数值或统计结果。
- 引用由服务端校验 document/chunk/page/element 归属和内容哈希；引用支持打开 PDF 对应页、图片裁剪和表格，用户可核查。
- 当前 `KnowledgeEvidence` 只有 hash/document/chunk/HTTPS URI，没有内容和本地引用能力。需要设计向后兼容的本地来源契约，使用服务端生成的 document ID/asset ID，不能伪造公网 URI、向前端暴露任意绝对文件路径或放宽到任意 file URL。
- 无证据时返回未检索到，不伪造页码、DOI 或论文内容。知识材料不是工具指令，也不能替代 counts 输入或 DESeq2 审批。

## 拟定 API 与工作流

以下为拟定服务契约，路径尚未实现，以后续已批准规格为准。

- 文献导入：浏览器上传/批量选择本地 PDF；后台 OCR/解析/索引有进度、取消、失败恢复和重复文件去重。未来若支持文件夹，只扫描用户明确选定根目录，不任意遍历电脑。
- `POST /api/v1/knowledge/search`：query、知识库范围及结果数量，返回相关原文、页码、章节、类型和图表资产引用；无需问答模型调用。
- `POST /api/v1/knowledge/ask`：question、知识库范围、model profile ID，返回答案与经过核验的引用，支持流式状态。使用任务 37 的页面配置，禁止另要求环境 Key。
- 文献、索引状态、PDF 与图表资源通过受控 ID 读取；接口可供外部本机程序调用，并提供 OpenAPI 和 curl/Python 示例。复用本地访问边界，不能为绕过 CSRF/CORS 而开放任意来源或公网监听；跨机器调用与多用户鉴权不是本阶段默认行为。
- 工作台提供知识库管理和聊天知识库选择；检索工具调用可观察，只有用户选中的库参与该轮检索。
- 本地 embedding 配置与问答模型区分；普通聊天 API 不保证提供 embedding，也不保证支持图片输入。问答只发送命中的必要片段，PDF 全文不自动上传。

## 开发顺序和验收

1. 先验收任务 37：核验提交、独立审阅 UI 与模型调用链，运行一组关键回归，确保上传/GEO 规划用该轮 profile。发现阻塞缺陷先修复，不并发修改同一工作区。
2. 再形成文献 RAG 规格与编号实施计划，覆盖摄取解析、检索/API、工作台问答与证据预览三个模块；每个编号任务单独开发和提交，每三任务整体复盘。
3. 解析验收使用具有明确授权的代表性样本：数字 PDF、扫描 PDF、双栏正文、图片/图注、表格与跨页表格。可量化比较文本顺序、表头/单位/脚注保留、页码/区域定位、处理时间和资源峰值。
4. 真正的 RAG 验收必须使用真实解析与真实本地向量检索，模型问答可 Mock；不能只用假解析或固定返回命中宣称知识库完成。缺少模型权重时明确报告并提供受控安装步骤。
5. 覆盖重复摄取、取消/重启、文档更新/移除后不可检索、跨库范围隔离、篡改引用和提示注入；不增加与实现一一对应的无意义测试。
6. 不读取用户的真实 Key，不自动调用付费 API。安装第三方依赖或下载模型遇沙盒限制按现有审批工具处理，不绕过限制。
