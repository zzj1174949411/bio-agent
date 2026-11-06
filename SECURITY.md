# 安全说明

Bio-Agent MVP 面向本地单用户科研演示。当前没有身份认证、用户间权限隔离、生产级网络防护或容器沙盒。建议将 API 与 Streamlit 绑定 `127.0.0.1`，只处理有权使用的数据。

本地 React 工作台由同一 FastAPI 服务提供。API 路由先于静态资源注册，未知 `/api/` 路径保持 JSON 404；前端路由才允许回退到构建后的 `index.html`。HTML 不缓存，带内容哈希的静态资源才使用长期缓存。开发双终端只允许精确的本地 Vite origin，不开启任意来源 CORS。浏览器只保留选中的非秘密 ID，不保存 API Key、完整消息或科研 artifact。

## 执行边界

- API、模型及上传文件不能指定可执行程序、R 脚本、任意公式或输出路径。
- Controller 在执行前重验获批计划的版本与哈希、输入 SHA-256 和确定性数据规则。
- Registry 只登记固定 DESeq2 工具。Runner 使用 `shell=False`、参数数组和固定 `r/deseq2/run.R`，JSON 参数文件只承载数据。
- Dataset/run ID 映射到受控目录；路径检查拒绝越界、路径穿越和 Windows 特殊路径别名。下载仅通过系统生成的不透明 artifact ID，并重新核对文件哈希。
- 上传自由文本视为数据。Planner 获得自然语言目标和受约束摘要，模型输出须通过 schema 与真实数据语义校验，不能用提示词绕过审批。

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
