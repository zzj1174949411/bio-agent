# 文献混合检索（任务 44–45）

工作台“对话知识库”下选择原文 RAG 或原文 + Wiki 混合。每个对话独立保存选择，旧对话和旧 Ask 请求默认 `rag`；`wiki` 只供 API/评测消融使用。选择知识库不会把普通聊天、GEO 或分析规划强制变为文献问答。

提交聊天时冻结模式、库范围、已发布原文 index revision、当前 Wiki generation/page 集合和模型配置。模型的 `knowledge_ask` 只能提供问题，不能改变模式、库或服务器路径。新增文献/后来构建的 Wiki 不会扩展已提交轮次；删除、重建、页面撤销或 generation 改变会在生成、历史读取、来源预览及 SSE 重放时校验。

## 路由和预算

- `rag`：沿用 BM25 + 本地 E5/Qdrant 原文检索。
- `hybrid`：独立检索 CURRENT Wiki（BM25 + 复用本地 E5），通过同库页面引用及导航链接直接取回原文。先按原文搜索排名选入，再补充按 chunk ID 去重的 Wiki 来源。每路仍默认 top6，最终并集按字节选择，不再用固定六条交替淘汰原文。
- `wiki`：只检索 Wiki 和直接解析其来源/链接，不调用正文 search。保留真实原文回源证据，不能当作原文 RAG 搜索的另一名称。

总上下文默认 24000 UTF-8 bytes，评测由锁定协议指定同一个上限；这是 JSON 上下文对象的字节，完整系统/问题消息另受评测输入限额约束。先给原文路径能装入预算的候选留出空间，Wiki 导航只使用剩余预算且最多占总上限四分之一；原文也可使用未被 Wiki 占用的空间。原文 chunk 和限定条件不截断；Wiki 按完整陈述选入。最终只保留其全部引用原文确实送入模型的陈述，重算实际上下文和审计。派生整理不算独立研究，事实/数值的最终引用只能是模型实际获得、仍存活的 PDF 原文 chunk。

正常混合聊天没有有效 Wiki 时明确退回原文 RAG，显示 requested/actual mode 和 fallback_reason；回退重新只选原文搜索候选。实验模式禁止这种回退，缺 Wiki/预算不足失败保留在分母。没有 Wiki 不会影响纯 RAG。

回答卡展示实际模式、回退、原文/Wiki 候选数、Wiki 回源数、实际送入数量/字节与派生导航。Ask 记录同时保存 sent chunk/page IDs，可核查检索命中和模型实际输入之间的差异。引用归属/hash/存活校验不保证语义蕴含，科学条件和数值须核对原文。图片仍只有图注/OCR，`visual_semantics=not_performed`。

Task45 的 `audit.selection_version=original-first-budget-v2`，新增 `original_search_sent`（实际选入且来自原文搜索的块）、`linked_only_sent`（仅由 Wiki 引入的块）、`duplicate_candidates`（两路合并时重复的 chunk ID 数）。旧记录保持旧版本标签；新增计数默认0只表示旧记录未保存该分项，不能推断历史真实贡献为零。这里去重的是同一来源块，不把不同元素中的相似文字冒充同一来源；图注/OCR语义重复仍可能存在。

## API 示例

写请求沿用 bootstrap cookie 与 X-CSRF-Token，ID 均来自服务器；下面省略真实 UUID。

```json
POST /api/v1/knowledge/ask
{"question":"两篇论文的方法条件有何不同？","knowledge_base_ids":["BASE_UUID"],"model_profile_id":"PROFILE_UUID","mode":"hybrid"}

POST /api/v1/knowledge/search
{"query":"方法与研究条件","knowledge_base_ids":["BASE_UUID"],"top_k":6,"mode":"hybrid"}

PATCH /api/v1/workbench/conversations/CONVERSATION_UUID
{"knowledge_mode":"hybrid"}
```

Ask GET/SSE 和聊天来源预览仍走原有受控端点。没有 URL/path 输入，没有原始 token 直传；完整引用校验后才展示答案。失效时移除答案、原文、派生导航并过滤旧 answer.delta/completed。不同对话切换后的迟到预览响应被忽略。

## 运行与验证

安装/权重准备见 `knowledge-ingestion.md`、`knowledge-retrieval.md`，Wiki 显式构建见 `knowledge-wiki.md`。生产 UI 需要重新 build，启动本地服务时可使用已配置环境的 `scripts/start-workbench.ps1 -Build`。现有8000服务不会由验收脚本停止或替换。

```powershell
# 独立真实本地链路，LLM 全为内存 Mock
uv run --extra rag --offline python scripts/verify_literature_hybrid.py --output data/task44/acceptance
npm --prefix frontend run build
uv run --extra rag --offline python scripts/serve_literature_workbench.py --data data/task44/ui --port 4184
# 另一个终端
$env:BIOAGENT_REAL_HYBRID_UI='1'
npm --prefix frontend run e2e -- --grep 'real hybrid chat'
```

三模式评测与盲评见 `knowledge-evaluation.md`。`scripts/run_literature_pilot.py` 默认不调用模型；`--live` 必须已有语料/目的地/预算授权。它复制公开 profile 及不透明凭据引用到隔离库，Key 仅由正常后端适配器在内存解析；不改用户 profile/知识库、不输出 Key。全局 JSON 台账在每次调用前持久预留，失败/超时不退还，未知供应商传输后停止，不自动重试/换模型。已有调用的目录拒绝自动重跑，不能换目录绕过授权总预算。

```powershell
uv run --extra rag --offline python scripts/run_literature_pilot.py --live --sources data/task44/pilot-preparation/sources.json --questions data/task44/pilot-preparation/pilot-notes.json --profile-db data/workbench.sqlite --profile-id PROFILE_UUID --output data/task44/real-pilot
```

该小试验为三篇真实论文、10道 development 问题，先人工核对参考、隔离解析/index 后重映射引用。最多50次包含探测/Wiki/三组问答，单次输出2000 token；输入消息内容每次32000 bytes、累计1600000 bytes。DeepSeek使用官方 max_tokens/thinking 参数，不能承诺未知输入 tokenizer 或计费金额上界。完整60题不在此授权内。实际结果与限制见 current-state 及42–44复盘，Mock成功和合法引用都不能证明混合更准。
