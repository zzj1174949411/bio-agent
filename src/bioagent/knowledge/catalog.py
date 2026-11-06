"""Audited model identities; no weights or dynamic model discovery in Git."""

import json
from pathlib import Path
from typing import Any, cast

SOURCES = [
    {
        "repo_id": "ds4sd/docling-layout-heron",
        "revision": "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8",
        "license": "Apache-2.0",
    },
    {
        "repo_id": "ds4sd/docling-models",
        "revision": "fc0f2d45e2218ea24bce5045f58a389aed16dc23",
        "license": "CDLA-Permissive-2.0 weights / Apache-2.0 code",
    },
    {
        "repo_id": "RapidAI/RapidOCR",
        "revision": "ModelScope v3.4.0 ONNX / v2.0.7 keys",
        "license": "Apache-2.0",
    },
]
OCR_FILES = {
    "det_model_path": "RapidOcr/onnx/PP-OCRv4/det/ch_PP-OCRv4_det_infer.onnx",
    "cls_model_path": "RapidOcr/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_infer.onnx",
    "rec_model_path": "RapidOcr/onnx/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer.onnx",
    "rec_keys_path": "RapidOcr/paddle/PP-OCRv4/rec/ch_PP-OCRv4_rec_infer/ppocr_keys_v1.txt",
}


def model_catalog() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads(Path(__file__).with_name("model_catalog.json").read_bytes()),
    )
