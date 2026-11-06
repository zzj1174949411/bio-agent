# Task45 文献分块与证据选择实现计划

> 使用 writing-plans 制定，使用 executing-plans 在当前聊天执行唯一编号任务。用户已批准先修改并比较效果；不再次请求设计批准。

**目标：** 保留 Docling，改进正文/表格分块与混合证据选择，以原三篇论文、十道 development 题做真实本地前后对照。

**架构：** 新索引显式记录分块算法版本，旧索引继续读原格式，只有显式重建才迁移。使用已安装 E5 tokenizer 对归一化元素分块，正文同节合并并保存全部元素的精确片段及位置，表格按完整行携带表头/图注/脚注；不猜测 Docling 未关联的信息。原文候选优先，Wiki 补充在字节预算内选入，不用固定六条交替淘汰原文。

**技术栈：** Python/uv、Pydantic、现有 Docling/E5 tokenizer、Qdrant、SQLite。

## Task45（唯一任务）

文件：`src/bioagent/knowledge/{chunks,retrieval_models,retrieval,hybrid,embedding,index_catalog,wiki}.py`；必要的回源 API；`tests/unit/knowledge/test_{chunks,hybrid,evaluation}.py`（复用既有retrieval/Wiki/API回归）；`scripts/compare_literature_retrieval.py`；本计划、使用说明、review、current-state。

- [x] 锁定旧基线：仅复制 ignored `data/task44/real-pilot/knowledge` 中三份来源及旧索引/真实 Wiki 到独立 `data/task45/comparison/old/knowledge`。锁定 sources、pilot-notes、dataset 的 SHA256、代码 commit；用旧实现真实 E5/Qdrant 运行 rag/hybrid，各十题，保存最终 context、逐题耗时、字节及精确参考片段覆盖。不得加载 profile/Key、创建付费台账或修改原库。
- [x] 写并运行聚焦红灯：正文同节/句子/token 上限与多元素归属；表格完整行和元数据；混合保留第4–6原文且预算/Wiki比例有效；旧哈希兼容、显式重建撤销。命令 `uv run --extra rag --offline pytest tests/unit/knowledge/test_chunks.py tests/unit/knowledge/test_hybrid.py tests/unit/knowledge/test_retrieval.py -q -p no:cacheprovider --basetemp data/task45/red`，实际红灯及沙盒socketpair中止记录见review；后续使用获准本地执行验证。
- [x] 最小实现：生产使用固定 E5 tokenizer 计数，目标400、上限450 token（含章节及上下文；前缀/特殊符号仍低于512）；极长句用token计数二分原文字符边界、优先词边界，直接切原文而不解码重写Unicode。表格过大完整行保留并标记超窗，绝不切坏行。短 OCR 图标签不单独冒充正文，同页同节短正文合并；没有真实位置的元素不索引。新来源片段含element/location/hash，旧字段仍作首来源导航锚点，新增来源集合供实际核验与回源。算法版本及来源字段进入哈希，旧摘要默认字段不改变旧 digest。
- [x] 对照A：同一旧索引/旧真实Wiki，只改变候选合并；原始top6保持，追加去重Wiki来源，预算仍24000，Wiki≤1/4；记录06/09保留与实际来源贡献。对照B：从同一缓存解析创建独立 `data/task45/comparison/new/knowledge`，只显式重建三份索引，跑新RAG十题，比较同top6和24000预算。禁止复制修改旧Wiki引用伪装新Wiki，不做完整新Wiki语义声明。
- [x] 用source SHA、element/page与精确原文区间映射锁定参考，不用旧随机chunk UUID作gold。报告全部十题、可答九题和无答案题、每题参考片段分子/分母、未映射/失败、表格数值/单位/表头、重复/孤立标签和耗时/输入bytes。参考不进入检索、调参或Wiki构建；不反复根据结果调题。检索覆盖不等于答案正确；无答案题不按关键词判拒答。
- [x] 验证受影响 pytest（knowledge/retrieval、workbench knowledge、Wiki与检索API）、`uv run --offline ruff check .`、`uv run --offline mypy src`；无UI变更仅必要契约typecheck，不跑浏览器。完成 `uv run --offline pre-commit run --all-files`、明确暂存、`git diff --cached --check`。
- [x] 更新本计划、使用说明、`docs/reviews/2026-10-21-task45.md` 与 current-state，记录真实结果/限制及父会话已批准的后续任务方向。本记录与实现作同一任务45编号commit收尾，随后停止，不代做47、不push/merge或自动跟进，保留renv原SHA256及根runs。

## 公平性与取舍

Docling 的原生 HybridChunker 要求重建 DoclingDocument，并默认根据自身 tokenizer/序列化重组表格；当前权威解析是带 hash 的 parsed.v1，引用和撤销使用本地元素。因此优先复用现有 E5 tokenizer 对归一化元素做小适配，保留精确片段，不迁移解析器或引入新依赖。实施前检查已安装能力，不因默认chunker丢失本地来源归属。

新分块会撤销旧 Wiki，A/B分开：A验证合并，B验证分块。完整新分块+真实新Wiki+真实答案需独立调用预算；旧49/50不追加。不把旧回答、Mock或上下文覆盖冒充新答案准确率，不改正式60题及45保留集。

## 执行记录

旧同节合并与旧混合函数各有1 failed红灯，最终受影响集合113 passed in37.57s；2026-10-22恢复后不重做真实前后评测，新跑同集合113 passed in58.06s。Ruff、mypy112 source files、前端typecheck通过；明确暂存18个任务45文件后，pre-commit八项hooks全部通过，cached检查退出0。单独保留用户renv原改动，Task46设计不回退；逐题结果及限制见review，本地原始输入/输出均ignored。
