# 安全说明

Bio-Agent MVP 面向本地单用户科研演示。当前没有身份认证、用户间权限隔离、生产级网络防护或容器沙盒。建议将 API 与 Streamlit 绑定 `127.0.0.1`，只处理有权使用的数据。

本地 React 工作台由同一 FastAPI 服务提供。API 路由先于静态资源注册，未知 `/api/` 路径保持 JSON 404；前端路由才允许回退到构建后的 `index.html`。HTML 不缓存，带内容哈希的静态资源才使用长期缓存。开发双终端只允许精确的本地 Vite origin，不开启任意来源 CORS。浏览器只保留选中的非秘密 ID，不保存 API Key、完整消息或科研 artifact。

## 执行边界

- API、模型及上传文件不能指定可执行程序、R 脚本、任意公式或输出路径。
- Controller 在执行前重验获批计划的版本与哈希、输入 SHA-256 和确定性数据规则。
- Registry 只登记固定 DESeq2 工具。Runner 使用 `shell=False`、参数数组和固定 `r/deseq2/run.R`，JSON 参数文件只承载数据。
- Dataset/run ID 映射到受控目录；路径检查拒绝越界、路径穿越和 Windows 特殊路径别名。下载仅通过系统生成的不透明 artifact ID，并重新核对文件哈希。
- 上传自由文本视为数据。Planner 获得自然语言目标和受约束摘要，模型输出须通过 schema 与真实数据语义校验，不能用提示词绕过审批。

GEO 来源也经过同一受控路径和哈希边界。关键词 catalog 只使用官方 NCBI allow-list；搜索标题、摘要和筛选文本一律当作不可信数据，不能构成下载 URL、Dataset、统计证据或审批。搜索结果必须由用户选择，之后才允许精确 GSE 发现；选择前不创建 import/download 请求。直接 GSE 路径仍受相同的候选确认约束。候选 URL 由固定 NCBI 主机 allow-list 和逐跳网络校验决定；模型不能提供下载地址。`UNKNOWN` 文件必须由用户确认 raw counts，且仍需用户确认 feature/sample 列、GSM 映射、分组和比较方向。分析创建前会校验 source 与 dataset 的绑定，并复制 raw、source.json 和 normalized 输入；manifest 登记每份来源副本的 SHA-256，恢复或复用前重新验证。来源或 run 副本损坏会拒绝执行。

每次 catalog 选择的 search ID、query hash、accession、revision、检索时间和 evidence hash 只在已验证 source 与 manifest 中保存；source 创建和发布都从权威搜索仓库重读 `SELECTING`/`SELECTED` 快照并逐字段比较。读取含 provenance 的 source，以及 Controller 执行、复用和恢复时，也会再次验证持久化 `SELECTED` 快照；因此攻击者即使重算 source/run 副本的 provenance hash，也不能让替换后的字段成为权威值。模型、API 或前端提交的同名字段不被接受。NCBI token、未来 RAG 凭据和其他 credential 不写入 catalog evidence、source、manifest、日志、事件或 checkpoint；`KnowledgeEvidence.source_uri` 只接受无 userinfo、无敏感 query 字段的 HTTPS URI。未来知识库仅能替换独立的 `KnowledgeRetriever`；当前 `NullKnowledgeRetriever` 明确返回 `RAG_NOT_CONFIGURED`，不会把文本接入 Dataset、下载或 DESeq2 审批流程。

## Skills 与 MCP

Skills 只从用户配置的本地绝对根目录读取一级 `SKILL.md` 和受限文本引用；不跟随逃逸 symlink、不执行同目录脚本、不展开凭据模板。内容 hash 与引用快照绑定，文件改变后必须重新启用。MCP 仅支持用户明确保存的 stdio `executable`/`argv`/`cwd` 或 Streamable HTTP endpoint；应用不从聊天、Skill 或数据库文件生成命令，也不自动下载程序。

MCP 凭据使用独立的 `mcp:` 引用命名空间，值只进入连接过程，不进入模型 Key、日志、事件、checkpoint、manifest 或统计产物。工具目录初始 `CONFIRM`；MCP 自报的 read-only 不能授予执行权限，`ALLOW_READ` 仍需用户审阅名称、目标、schema 和数据去向。批准绑定参数 hash、schema/capability revision、turn 和 10 分钟期限，只能消费一次；旧 revision、过期、拒绝、重复或重启后的批准均拒绝。

工具输出是不可信数据：界面按文本显示并折叠原始结果，模型上下文只接收带来源标签且有大小上限的摘要。调用超时、取消、连接断开或“已发出但结果未保存”统一记录稳定错误；`TOOL_OUTCOME_UNKNOWN` 不自动重试。取消不能承诺回滚远端副作用，统计 run 仍只能由原有 DESeq2 计划/人工审批/确定性 QC 改变。退出时只清理本应用创建的 stdio 子进程，不终止用户预先启动的服务。

这些措施约束应用入口，不意味着宿主机是隔离沙盒。R 包和仓库代码仍以当前操作系统用户权限运行。SHA-256 用于一致性检查，不是防篡改签名；有宿主机写权限的人仍可能同时改写文件与证据。

## 上传限制

默认 FastAPI 工厂实施下列限制（见 `api/app.py`、`api/dependencies.py` 与 `api/routes.py`）：

| 项目 | 当前默认限制 |
| --- | --- |
| 扩展名 | `.csv`、`.tsv` |
| MIME | `text/csv`、`text/tab-separated-values`、`text/plain`、`application/vnd.ms-excel`、`application/octet-stream` |
| 编码与内容 | UTF-8（允许 BOM）；仍需通过 CSV/TSV 和科学数据校验 |
| 单个文件 | 10 MiB（10 × 1,024 × 1,024 字节），拒绝空文件 |
| 整个上传请求 | `Content-Length` 必填，默认上限 20 MiB + 64 KiB |
| 表格规模 | 每个文件最多 100,000 条数据行、10,000 列 |
| 解析时间 | 预扫描检查 10 秒限制；完整解析和验证在可终止的独立进程中设置 10 秒等待上限 |

MIME 是允许列表，不是文件真实性证明；例如 `application/octet-stream` 仍必须能解析为有效文本表格。请求总长度门禁依据声明的 `Content-Length`，不是通用网络代理或全请求流量防护。限制可由受信任应用工厂代码覆盖，不开放给普通请求参数。

R 工具当前超时为 1,800 秒。取消为协作式，执行中的 R 不保证立即终止。ToolSpec 的 4,096 MiB 内存值只是声明，尚未实施操作系统级内存限额。

GEO 下载有独立的压缩/解压、矩阵规模、解析时长、停顿和磁盘预检上限；未知 Content-Length 的响应仍受流式总字节限制。失败下载清理本次临时文件并从头重试，不对外宣称 Range 续传。缓存命中时重新计算原始和标准化文件哈希，同一 URL 内容变化不会覆盖旧 source。

## 密钥与数据

DeepSeek Key 从环境变量或本地 `.env` 读取，使用 `SecretStr` 保存；它不属于 checkpoint、manifest 或 R 参数。R 子进程只继承运行所需的环境变量，不传入应用模型 Key。自动测试使用 Mock，不依赖真实 Key。

不要在目标文本、metadata、日志附件、截图、issue、测试 fixture 或 Git 中放置 Key。`.env`、运行数据、产物与 checkpoint 应保持忽略；不要打开可能记录完整请求/认证头的调试或第三方追踪。发生泄露时先在 provider 平台撤销或轮换 Key，再私密报告泄露范围。

使用外部模型时，目标、dataset ID、样本/feature 数量和受约束分组列/水平会发送给 provider。完整 counts 不在默认 Planner 请求内，但组名或目标仍可能暴露敏感信息；这些字段也可能保留在本地 checkpoint、计划、日志与报告中。只发送已允许用于外部服务的数据，分享产物前自行检查研究信息。

## 私密报告漏洞

请勿在公开 issue 或 PR 中贴出真实密钥、敏感样本、完整漏洞利用细节或未脱敏日志。

如果仓库已启用 GitHub 私密漏洞报告，使用 [Report a vulnerability](https://github.com/zzj1174949411/bio-agent/security/advisories/new)。若该入口不可用，请通过 [维护者主页](https://github.com/zzj1174949411) 提供的联系方式询问私密接收渠道；没有可用联系方式时，可发起仅请求私密联系渠道的 issue，不包含漏洞细节。项目没有声明已启用该功能或固定响应时限。

私密报告提供受影响 commit、操作系统、复现步骤、实际与预期行为、潜在影响，以及使用合成数据的最小示例。密钥只说明所属 provider 和是否已撤销，不发送密钥本身。

## 科学用途

软件用于科研探索与工程演示，不用于临床诊断、治疗选择或自动化医疗决策。QC 通过只表示定义的规则被满足，不证明实验设计合理、消除混杂或成立因果关系；研究者仍需检查比较方向、生物学重复、结果与警告。
