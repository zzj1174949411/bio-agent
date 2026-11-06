# Task 38：Windows Docling 兼容性与真实解析实验

日期：2026-10-12。仅验证本地 PDF 解析，不包含 embedding、检索或问答。

## 环境与可复现入口

实验使用 Windows x86-64、CPython 3.12.14、uv 0.12.5，隔离环境位于
`data/task38/docling-env`，没有更改项目的基础 Python 环境或 R 环境。
机器为 Windows 11 build 26200、AMD Ryzen 9 8940HX（16 核 / 32 逻辑 CPU），
可见内存 33,521,258,496 bytes（31.219 GiB）；精确机器参数及解析测量写在 ignored
`data/task38/measurements.json`。采样 RSS 是解析 Python 进程的 resident set，
不等于机器总内存或最低硬件要求。CPU 配置会在最终实测表中区分。

安装与原始样本生成命令：

```powershell
uv venv data/task38/docling-env --python 3.12
uv pip install --python data/task38/docling-env/Scripts/python.exe 'docling==2.58.0' reportlab psutil
uv run --no-project --python data/task38/docling-env/Scripts/python.exe python scripts/literature_samples.py --output data/task38/samples
```

实际安装还曾加入 `rapidocr-onnxruntime==1.4.4`，随后确认 Docling 2.58 使用
`rapidocr` 命名空间，已卸载无用旧包；最终推理不依赖该旧包。
完整实际解析依赖清单保存在 `data/task38/requirements-frozen.txt`。

| 包 | 实验安装版本 |
| --- | --- |
| docling | 2.58.0 |
| docling-core | 2.101.1 |
| docling-ibm-models | 3.15.0 |
| docling-parse | 4.7.3 |
| torch / torchvision | 2.14.1 / 0.29.1 |
| transformers | 4.57.6 |
| rapidocr / onnxruntime | 3.10.0 / 1.31.0 |
| numpy / Pillow | 2.5.4 / 11.3.0 |
| reportlab / psutil | 5.0.1 / 7.2.2 |

[PyPI 固定版 Docling](https://pypi.org/project/docling/2.58.0/) 的软件许可证是 MIT；
权重许可证必须单独核对，不能从 Python 包许可证推断。

## 模型来源、布局与许可证

模型仅在显式实验准备阶段下载。运行解析时设置 `HF_HUB_OFFLINE=1`、
`TRANSFORMERS_OFFLINE=1`，并用拒绝 `socket.connect` 的实际运行验证独立下载路径。
`enable_remote_services=False`、`allow_external_plugins=False`，关闭图片描述、分类、
公式与代码增强，没有视觉语义模型或远程模型调用。

| 模型 | 固定来源 | 许可证依据 |
| --- | --- | --- |
| Heron 布局 | `ds4sd/docling-layout-heron`，提交 `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8` | 该提交 README：Apache-2.0 |
| TableFormer accurate | `ds4sd/docling-models`，`v2.3.0` → `fc0f2d45e2218ea24bce5045f58a389aed16dc23` | 该提交 README：CDLA-Permissive-2.0 |
| PP-OCRv4 ONNX | ModelScope `RapidAI/RapidOCR`，`v3.4.0`；字典为 `v2.0.7` | RapidOCR 和上游 PaddleOCR 的 Apache-2.0；未发现每个导出 ONNX 另附许可证，保留来源与字节哈希 |

对应的固定模型卡：[Heron](https://huggingface.co/ds4sd/docling-layout-heron/blob/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8/README.md)、
[TableFormer](https://huggingface.co/ds4sd/docling-models/blob/fc0f2d45e2218ea24bce5045f58a389aed16dc23/README.md)；
OCR 官方依据：[RapidOCR v3.4.0 LICENSE](https://github.com/RapidAI/RapidOCR/blob/v3.4.0/LICENSE)、
[PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)、
[Docling 2.58 OCR 下载配置](https://github.com/docling-project/docling/blob/v2.58.0/docling/models/rapid_ocr_model.py)。

模型根目录为 `data/task38/models`。Docling 2.58 使用旧命名 `ds4sd--...`，
尽管 Hugging Face 会把网页重定向到 `docling-project`。
不要根据最新版文档改名；本次适配以固定版本的实际源码与推理为准。

```text
models/
  bundle.json
  ds4sd--docling-layout-heron/
    config.json
    preprocessor_config.json
    model.safetensors
  ds4sd--docling-models/model_artifacts/tableformer/accurate/
    tableformer_accurate.safetensors
    tm_config.json
  RapidOcr/onnx/PP-OCRv4/
    det/ch_PP-OCRv4_det_infer.onnx
    cls/ch_ppocr_mobile_v2.0_cls_infer.onnx
    rec/ch_PP-OCRv4_rec_infer.onnx
  RapidOcr/paddle/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer/
    ppocr_keys_v1.txt
```

`bundle.json` 为 `docling-bundle.v1`：`parser_version`、相对路径到 SHA-256 的
`files`、RapidOcrOptions 参数名到相对路径的 `ocr`、含 repo/revision/license 的
`sources`。OCR 的 `det_model_path`、`cls_model_path`、`rec_model_path`、
`rec_keys_path` 均转换为本地绝对路径；不能只设置 OCR 语言列表，因为固定版本源码说明
`lang` 不改变 RapidOCR 模型选择。

下载中的完整流曾停滞，改用固定提交 URL 的 HTTP Range 分段；每段校验预期长度，
合并后再校验总长度与 SHA-256。中断产生的部分 safetensors 不作为模型就绪证据。
原始模型和运行 JSON/PNG/PDF 只保存在 ignored `data/task38/`，不进入 Git。

## 样本与观测方法

`scripts/literature_samples.py` 自行创作全部文字、数字和图像，没有用户文献、
外部论文或真实生物学结果：

- `digital_twocolumn_figure_table.pdf`：一页数字 PDF，`LEFT-01` 至 `LEFT-10`
  与 `RIGHT-01` 至 `RIGHT-10` 的双栏次序标记；原始图片、Figure 1 图注；
  Table 1 包含 `Mass (mg)`、`Time (s)`、`Beta*` 和独立脚注。
- `scan_ocr.pdf`：一页纯栅格扫描 PDF，无 PDF 文字层，检查标题、`SCAN-ALPHA`、
  `12.5 mg`、`30 s` 和句子恢复。
- `cross_page_table.pdf`：两页 Table 2，各保留同样表头，第二页带 continued 图注及 `D*` 脚注。

先行扫描探针关闭 TableFormer，但真实运行布局与 OCR，socket 连接被拒绝，返回
`ConversionStatus.SUCCESS`：五个 text cell 全部 `from_ocr=True`，上述五条文本正确恢复。
该探针不替代完整布局、表格、资源和 API 验收。

## API 适配注意事项

使用 `PdfPipelineOptions(artifacts_path=models)` 配合显式 `RapidOcrOptions`；
`AcceleratorOptions(device=CPU, num_threads=...)` 固定 CPU 推理。
[固定版选项源码](https://github.com/docling-project/docling/blob/v2.58.0/docling/datamodel/pipeline_options.py)
和 [官方离线准备说明](https://docling-project.github.io/docling/usage/advanced_options/)
支持预取后指定本地 artifacts 路径。

`DoclingDocument.export_to_dict()`/`save_as_json()` 保留 body 树、元素关系、pages、
表格与图片。`iterate_items()` 给出的次序用于阅读顺序，`self_ref` 用作原始元素 ID。
最终元素 `prov.page_no` 与中间 `ConversionResult.pages[*].page_no` 分开核对；
后者实测从 0 开始。坐标保留 `coord_origin`，不能无条件翻转。

`TableItem.data.table_cells` 保存行列索引、span、header 和 bbox；单位通常就是表头文字。
表格与图片的 `captions`、`footnotes` 是 RefItem，可 `resolve(doc)`；
`caption_text(doc)` 获取相关图注。结构模型没有承诺将所有邻近脚注自动关联。
跨页表格要保存页内片段，不推断合并后统计关系。

`generate_page_images=True` 可使表格 `get_image(doc)` 返回裁剪；图片还启用
`generate_picture_images=True`。`generate_parsed_pages=True` 使 page cells 可用于
保存原始 OCR 来源、置信度和区域。最终 TextItem 不保留 `from_ocr` 字段。
无语义增强时不能把 PictureItem.annotations 当成图片描述；图片 OCR 单独识别或按坐标关联。

## 最终真实解析结果

完整模型和模型卡共 **400,650,044 bytes（382.09 MiB）**，其中推理必需文件
400,643,412 bytes，另外两个 README 共 6,632 bytes。
隔离环境实际文件大小总计 **1,212,812,229 bytes（1.130 GiB）**，不包含 uv
全局下载缓存；模型目录不包含在环境大小内。临时分段文件另占约 384 MB，可在实验结束后清理。
环境安装中下载/准备 85 个包用时 1m31s，安装 101 个包用时 11.65s，
解析器最终卸载了 1 个无用旧 OCR 包。模型下载有 TLS EOF、完整流停滞与重试，
最后一次续传完成用时 123.969s；这不是从空目录开始的总下载时长或稳定带宽指标。

模型逐文件 SHA-256 和 bytes 已写在 `data/task38/model-catalog.json`、
`models/bundle.json`，并交接给工程的固定模型 catalog。主要权重：

| 文件 | bytes | SHA-256 |
| --- | ---: | --- |
| Heron `model.safetensors` | 171658996 | `00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c` |
| `tableformer_accurate.safetensors` | 212758388 | `2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9` |
| `ch_PP-OCRv4_det_infer.onnx` | 4745517 | `d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9` |
| `ch_ppocr_mobile_v2.0_cls_infer.onnx` | 585532 | `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c` |
| `ch_PP-OCRv4_rec_infer.onnx` | 10857958 | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` |
| `ppocr_keys_v1.txt` | 26249 | `28b2362ad4ab2dc38769aa72feb535e3a9ddb3fd2a7585a05920e6393b1dc7f7` |

完整 Docling 直接转换使用 CPU `num_threads=4`、`images_scale=1`、同一 converter
顺序运行三份 PDF；计时包含该次转换与 JSON/PNG 导出，第一份包含 pipeline 模型初始化，
不含 Python 导入时间。RSS 每 20ms 采样，`network_attempts=[]`，三份均为 SUCCESS
且没有 ConversionResult.errors。

| PDF | 页数 | 时间（s） | CPU 时间（s） | peak RSS（bytes） | 表格 / 图片 |
| --- | ---: | ---: | ---: | ---: | --- |
| cross_page_table | 2 | 4.133 | 13.563 | 1165836288 | 2 / 0 |
| digital_twocolumn_figure_table | 1 | 2.764 | 22.688 | 1170448384 | 1 / 1 |
| scan_ocr | 1 | 3.575 | 45.219 | 1449664512 | 0 / 0 |

CPU 时间为 user+system 累计，可能大于墙钟时间；线程参数限制不保证所有依赖内部线程都相同。
这里不能据此推断 OCR 质量或大文献吞吐量。

进一步使用真实 `bioagent.knowledge.worker` 固定入口，新建进程逐份转换，
CPU `num_threads=2`、`images_scale=2`、保存完整 JSON、归一化结构与 PNG，
并单独对图片 crop 做 RapidOCR。计时包括 Python 导入、模型初始化和输出；
worker 拒绝 socket connect/connect_ex/create_connection，子进程使用 supervisor 的
Windows/home 环境 allowlist，没有 API Key。

| PDF | 退出码 | 时间（s） | peak 进程树 RSS（bytes） | 归一化元素 / assets |
| --- | ---: | ---: | ---: | --- |
| cross_page_table | 0 | 11.797 | 1176961024 | 7 / 2 |
| digital_twocolumn_figure_table | 0 | 12.625 | 1106014208 | 31 / 2 |
| scan_ocr | 0 | 12.296 | 1135804416 | 3 / 0 |

worker 结果保存在 `data/task38/worker-results/`，测量为
`data/task38/worker-measurements.json`。最初的实验 harness 遗漏 USERPROFILE/HOME 等
Windows 环境变量，worker 在导入阶段退出，返回 PARSE_PROCESS_FAILED；与工程 supervisor
实际 allowlist 对齐后全部成功。该失败不作为工程 parser 的解析缺陷。

逐项检查原始 JSON、归一化结构、导出的 Markdown 和裁剪图像后得到：

- **双栏顺序缺陷：** 所有 20 条标记完整，但顺序为 LEFT-01、RIGHT-01、LEFT-02、
  RIGHT-02，逐行交错，未恢复预期的完整左栏后完整右栏。本任务保留模型输出，附
  `READING_ORDER_REQUIRES_REVIEW`，不能把 SUCCESS 当成阅读顺序正确。
- **数字表格：** 3×3 cell 表格正确恢复，三个表头的 `column_header=True`，
  `Mass (mg)`、`Time (s)`、`12.5`、`8.0`、`Beta*` 均完整；caption 关联正确。
  `* Beta...` 脚注在 JSON 中作为 footnote 元素和表格 ref 保存，worker 正确解析为
  `footnotes` 字符串；默认 Markdown 导出未显示这个已关联脚注，不能仅保存 Markdown。
- **跨页表格：** 两页保留为两个独立 3×3 table；页码分别为 1、2，表头/单位均保留，
  continued caption 正确关联。第二片段关联 `* D...` 脚注，D* 正确保留；第一片段没有
  footnote，因此出现缺失关联提示。没有自动合并、推断缺失行或计算统计量。
- **图片与图注：** 识别 1 个 picture，关联 Figure 1 图注，生成可读 PNG 裁剪。
  目视确认两个彩色柱、坐标轴、CONTROL/TREATED 均包含；没有生成图像语义描述。
  worker 图片 OCR 为 `SYNTHETICSIGNAL\nCONTROL\nTREATED`，标题空格被丢失；
  这说明高 OCR 置信度不保证精确转录，也不能据柱高推断数值。
- **扫描 OCR：** 纯栅格 PDF 的五条文字完整恢复，`12.5 mg` 与 `30 s` 正确，
  五个 `page_text_cells` 都 `from_ocr=True`，置信度约 0.957–0.998；布局组合成三个
  TextItem/SectionHeaderItem，不等同于 OCR cell 个数。
- **资源定位：** 原始元素 self_ref、1-based `prov.page_no`、bbox 与 BOTTOMLEFT
  坐标原点保存；OCR page cells 保留 TOPLEFT，工程转换其内部页号 `0→1`。
  表格 crop 包含表头、单位和 D*；caption/footnote 在结构中独立关联，不假定属于 crop 像素。

这组短小、清晰、英文、合成样本只证明固定软件栈、本地权重、OCR 和结构输出在这台
Windows 机器可运行；不能外推中文、倾斜/低质扫描、多级复杂表头或真实长论文的质量。
机器为 31.219 GiB RAM、CPU 推理未使用 GPU；新进程峰值约 1.03–1.10 GiB，
同进程多文档最大约 1.35 GiB。建议首轮为单解析 worker 预留至少 4 GiB RAM 和
约 2 GiB 空闲磁盘（不含下载缓存和文献产物），这是基于小样本的运维余量建议，
不是已经验证的最低配置；大文献仍由超时、页数和进程树 RSS 限额约束。

本实验未修改 `renv/activate.R`，结束时 SHA-256 仍为
`A36F28F84219B6B9A89C4E5EB365A0F44D2F01F4FB9CFEDB0940D1CC7D09103A`。
`scripts/literature_samples.py` Ruff 检查为 All checks passed。工程 API 端到端导入及
完整代码门禁由任务 38 主实现验收；本文不以独立 parser 实验代替该项。

主实现随后运行真实 API 验收：`uv run --extra rag --offline python scripts/verify_literature_ingestion.py --output data/task38/api-acceptance-final`。
3 份样本/4 页均完成 PARSED，index_revision 为空；digital/scan/cross-page 分别耗时
13.031/12.532/11.922 秒，进程树 peak RSS 分别为
1,141,379,072/1,120,493,568/1,164,365,824 bytes。
实际检查扫描 OCR、表头单位脚注、图片 OCR/PNG 资源及删除后访问失效，结果写入 ignored
`data/task38/api-acceptance-final/acceptance.json`。最终测试和审查记录见
`docs/progress/current-state.md` 的 Task 38 节。
