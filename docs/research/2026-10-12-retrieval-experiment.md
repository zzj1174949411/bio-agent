# Task 39：Windows 本地 embedding、Qdrant 与 API 实验

日期：2026-10-12。环境：当前 Windows、uv 管理的 Python 3.12、CPU 推理；与 Task 38 同机。样本仅为仓库脚本自制的三份短 PDF，共四页；未读取用户文献或真实 API Key，问答模型仅 Mock。

## 官方依据和固定文件

- [E5 模型卡](https://huggingface.co/intfloat/multilingual-e5-small/blob/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)：多语言、MIT、384 维、query:/passage: 前缀、attention mean pooling、L2 normalize，512 token 上限。
- [官方 Transformers 离线安装说明](https://huggingface.co/docs/transformers/v4.57.1/installation)：本地文件及 local_files_only。工程固定实际安装版本 4.57.6，不执行 trust_remote_code，不加载 pickle 权重。
- [Qdrant Python 客户端](https://github.com/qdrant/qdrant-client)：path 本地持久化模式；[固定 1.15.1 包信息](https://pypi.org/project/qdrant-client/1.15.1/) 为 Python >=3.9、通用 py3 wheel，337,331 bytes，wheel SHA256 `2b975099b378382f6ca1cfb43f0d59e541be6e16a5892f282a4b8de7eff5cb63`。
- 同时检查安装包的 local_collection.py/persistence.py/qdrant_local.py：固定版持久化使用 pickle，Cosine 内存归一化与持久化原值不同，且 Qdrant 自身锁在加载之后获取。因此工程先取得独立进程锁、检查物理存储哈希，再生成可信 metadata 并打开 Qdrant。

实际 rag 依赖为 transformers 4.57.6、torch 2.14.1、qdrant-client 1.15.1、既有 onnxruntime 1.31.0；uv.lock 固定全部传递依赖和包哈希。新增 Qdrant 安装引入 grpcio/h2/hpack/hyperframe/portalocker，未增加另一套解析器或 SentenceTransformers。

显式准备命令：

```powershell
uv sync --extra rag --dev
uv run --extra rag --offline python -m bioagent.knowledge.prepare_embedding --models-dir data/embedding-models
```

`--offline` 约束 uv 解析依赖，**不禁止显式 prepare 的 HTTP 下载**。实际下载经过正常 require_escalated 审批，不绕过网络沙盒；模型推理没有调用 prepare。五个文件共 **487,725,595 bytes（465.13 MiB）**，全部实际下载并逐文件验证。

| 文件 | bytes | SHA256 |
| --- | ---: | --- |
| model.safetensors | 470641600 | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` |
| tokenizer.json | 17082730 | `0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39` |
| config.json | 655 | `69137736cab8b8903a07fe8afaafdda25aac55415a12a55d1bffa9f581abf959` |
| special_tokens_map.json | 167 | `d05497f1da52c5e09554c0cd874037a083e1dc1b9cfd48034d1c717f1afc07a7` |
| tokenizer_config.json | 443 | `a1d6bc8734a6f635dc158508bef000f8e2e5a759c7d92f984b2c86e5ff53425b` |

revision 为 `614241f622f53c4eeff9890bdc4f31cfecc418b3`。工程清单 `embedding_catalog.json` 是实际准备和 readiness 的约束；模型 ID、revision、算法与维度登记在每个索引。权重不入 Git。

## 真实 API 验收

```powershell
uv run --extra rag --offline python scripts/verify_literature_retrieval.py --output data/task39/acceptance-final3
```

通过真实 FastAPI 生命周期与 HTTP 路由重新上传三份 PDF，实际 Docling 子进程解析为 PARSED，再调用 index API，经 E5 和 Qdrant 发布独立 READY revision。正文、表格、图片图注/OCR 均来自真实解析，没有用假向量或 Mock 解析代替。原文/parse JSON/settings/models/assets 在构建及发布时再次校验。每文献 collection 独立，服务进程持有一个 Qdrant 实例。

最终输出在 ignored `data/task39/acceptance-final3/acceptance.json`，保留完整实际 hit、元数据、索引 revision、分数和资源链接。三份文献共 41 个 chunks；解析及首次索引总用时 **45.593 s**，数字图表/扫描/跨页表格索引轮询分别 **5.766/0.250/0.343 s**，第一份包含 E5 导入和加载。应用进程验收末尾 RSS **942,936,064 bytes（约 899 MiB）**，这是采样点，**不是峰值**，不包含同时运行的解析子进程峰值，也不能外推大文献吞吐量。

| 中文问题 | 实际目标命中及页码 | 排名 | dense 分数 | 请求用时 |
| --- | --- | ---: | ---: | ---: |
| 扫描样本的质量是12.5毫克，测量时间是30秒 | SCAN-ALPHA 正文，scan_ocr.pdf，第 1 页 | 1 | 0.84327144 | 0.110 s |
| 表格中Beta的质量和时间，质量单位mg和时间单位s | Table 1，数字图表样本，第 1 页 | 1 | 0.85327935 | 0.109 s |
| 图1的柱高是否表示实验结果还是仅用于展示排版 | picture 的图注/OCR 与 PNG，第 1 页 | 4 | 0.80629481 | 0.109 s |

扫描正文保留 `12.5 mg`/`30 s`。表格命中包含 Sample、Mass (mg)、Time (s)、Alpha/Beta* 数据、标题和 synthetic control 脚注。图像相关原文为图注和 `SYNTHETICSIGNAL/CONTROL/TREATED` OCR，`visual_semantics=not_performed`；系统没有读取柱高或推断精确值。该问题的独立 caption 排第 1，带 PNG 的 picture 排第 4，因此验收核对设计实际返回的 top_k=6，不宣称所有元素都进入前三。

随后关闭应用及持久化客户端，创建新应用并重新打开 Qdrant。相同 query 的所有返回字段（含分数/引用）与关闭前完全一致。跨库空范围返回 NO_EVIDENCE。索引重建后旧引用返回 409；已完成 Mock 答案失效且 SSE 重放不再包含 answer.delta。删除知识库后旧引用再次返回 409。篡改 hash 返回 422。Mock 模型只调用一次，状态/检索/已验证答案 SSE 事件齐全，未读取系统凭据。单元测试另覆盖 source/asset/manifest 篡改、伪造 UUID/fileURL、取消/失败/模型配置冻结/模型维度切换、加载前向量存储校验及重启残留目录清理。

## 初始失败与质量限制

1. 第一次 E5 实验发现 tokenizer 单条 tensor 没有 batch 维度；修为固定二维 input_ids/attention_mask，随后真实中英向量为 384 维。后续直接按 token ID 组成 480 token 窗口，避免 decode→encode 重新截断；不依赖模型下载或远程代码。
2. 初版对 Cosine 模式内存向量做精确摘要，真实 API 检索触发 INDEX_INTEGRITY_FAILED。对比 chunk/source 哈希正常，而 Qdrant load_vectors 恢复的是未经过内存 float32 归一化的原始值。新增非平凡向量持久化红灯复现，改为 E5 已归一化 float32 的 DOT 存储后重启通过；同时对物理 SQLite 哈希和向量摘要分别验证。
3. 初始纯中文问题「图片里的合成信号柱状图，对照组与处理组」未在前六找到 picture。调查同样本的不同措辞，贴近图注明确声明的问题可以命中；一般化「图注说柱形高度用于说明什么」的 picture 也可能排第 10。保留这一局限，不通过伪向量/伪文献或删除失败记录冒充稳定质量。完整表头加入后 picture 从第 3 变为第 4，独立 caption 仍第 1；这反映混合排名受语料统计影响。
4. 仅三份英文合成短 PDF，不是生物学语料质量基准。章节标题可能稀释 dense 信息，caption/OCR 与 picture 重复出现；相邻上下文包含明确元素 ID，但仍可能来自 Docling 错误的双栏阅读顺序。跨页表格仍是独立页内片段，图片 OCR 仍有空格丢失。检索不修复解析器未识别的表头/脚注关联，也不保证问答正确解释文章。
5. 没有经真实外部供应商验证问答质量。问答用普通文本调用，不假设所选模型支持 embedding/vision；服务端验证的仅是来源归属和存活完整性。状态实时流，答案在全部引用验证后分段发送，未做原始 token 透传。无通用语义阈值，邻近命中不能当作问题一定有答案。
6. 完整性校验读取原文、资产和索引数据，当前优先小规模本机可审计性，未做大规模延迟/召回率或最低硬件基准。未扩大到多进程 Qdrant server、多用户或公网部署。

最后的测试、静态检查与提交状态以 `docs/progress/current-state.md` 和 Git 为准。真实数据、模型权重、索引及 PDF 均未提交。
