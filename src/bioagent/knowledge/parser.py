"""Replaceable local parser. Heavy optional packages load only inside the worker."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from bioagent.knowledge.models import Asset, Element, Location, ParsedDocument
from bioagent.knowledge.runtime import PARSER_VERSION, bundle_path, load_bundle
from bioagent.knowledge.store import MAX_PDF_BYTES, KnowledgeError, file_hash


class LiteratureParser(Protocol):
    def parse(self, source: Path, output: Path, models: Path) -> ParsedDocument: ...


class DoclingParser:
    def parse(self, source: Path, output: Path, models: Path) -> ParsedDocument:
        bundle, models_hash = load_bundle(models, verify=True)
        options_module = importlib.import_module("docling.datamodel.pipeline_options")
        base = importlib.import_module("docling.datamodel.base_models")
        converter_module = importlib.import_module("docling.document_converter")
        accelerator = importlib.import_module("docling.datamodel.accelerator_options")
        core = importlib.import_module("docling_core.types.doc")
        ocr_paths = {key: str(bundle_path(models, value)) for key, value in bundle["ocr"].items()}
        options = options_module.PdfPipelineOptions(
            artifacts_path=models,
            enable_remote_services=False,
            allow_external_plugins=False,
            do_ocr=True,
            do_table_structure=True,
            do_picture_classification=False,
            do_picture_description=False,
            do_code_enrichment=False,
            do_formula_enrichment=False,
            generate_page_images=True,
            generate_picture_images=True,
            generate_parsed_pages=True,
            images_scale=2,
            document_timeout=570,
            accelerator_options=accelerator.AcceleratorOptions(
                device=accelerator.AcceleratorDevice.CPU,
                num_threads=2,
            ),
            ocr_options=options_module.RapidOcrOptions(backend="onnxruntime", **ocr_paths),
        )
        # Normalize machine-specific paths out of the configuration provenance hash.
        configuration = options.model_dump(mode="json")
        configuration["artifacts_path"] = "<verified-model-bundle>"
        configuration["ocr_options"].update(bundle["ocr"])
        settings_bytes = json.dumps(configuration, sort_keys=True).encode()
        settings_hash = sha256(settings_bytes).hexdigest()
        converter = converter_module.DocumentConverter(
            allowed_formats=[base.InputFormat.PDF],
            format_options={
                base.InputFormat.PDF: converter_module.PdfFormatOption(pipeline_options=options)
            },
        )
        result = converter.convert(source, max_num_pages=200, max_file_size=MAX_PDF_BYTES)
        if result.status != base.ConversionStatus.SUCCESS:
            raise KnowledgeError("PARSE_INCOMPLETE")
        doc = result.document
        output.mkdir(parents=True, exist_ok=True)
        (output / "settings.json").write_bytes(settings_bytes)
        (output / "models.json").write_bytes((models / "bundle.json").read_bytes())
        # Preserve all Docling relationships/data; image bytes are separate controlled assets.
        doc.save_as_json(output / "docling.json", image_mode=core.ImageRefMode.PLACEHOLDER)
        elements: list[Element] = []
        assets: list[Asset] = []
        warnings = [
            "FIGURE_SEMANTICS_NOT_PERFORMED",
            "OCR_TEXT_MAY_CONTAIN_ERRORS",
            "READING_ORDER_REQUIRES_REVIEW",
        ]
        sections: list[tuple[int, str]] = []
        crop_ocr: Any = None
        for item, level in doc.iterate_items(traverse_pictures=True):
            kind = item.label.value
            text = getattr(item, "text", "")
            if kind in {"section_header", "title"}:
                heading_level = 0 if kind == "title" else getattr(item, "level", level)
                while sections and sections[-1][0] >= heading_level:
                    sections.pop()
                sections.append((heading_level, text))
            locations = tuple(
                Location(
                    page=prov.page_no,
                    bbox=(prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b),
                    origin=prov.bbox.coord_origin.value,
                )
                for prov in item.prov
            )
            table, asset_id, ocr_text = None, None, ""
            captions = tuple(
                getattr(ref.resolve(doc), "text", "") for ref in getattr(item, "captions", [])
            )
            footnotes = tuple(
                getattr(ref.resolve(doc), "text", "") for ref in getattr(item, "footnotes", [])
            )
            if kind == "table":
                table = item.data.model_dump(mode="json")
                text = item.export_to_markdown(doc=doc)
                warnings.append("TABLE_STRUCTURE_AND_CROSS_PAGE_CONTINUITY_REQUIRE_REVIEW")
                if not captions:
                    warnings.append("TABLE_CAPTION_NOT_ASSOCIATED")
                if not footnotes:
                    warnings.append("TABLE_FOOTNOTES_NOT_ASSOCIATED")
            if kind in {"picture", "chart", "table"}:
                image = item.get_image(doc)
                if image is None:
                    warnings.append("CROP_NOT_AVAILABLE")
                else:
                    asset_id = uuid4()
                    image_path = output / f"{asset_id}.png"
                    image.save(image_path, format="PNG")
                    assets.append(Asset(id=asset_id, sha256=file_hash(image_path)))
                    if kind in {"picture", "chart"}:
                        if crop_ocr is None:
                            crop_ocr = self._crop_ocr(ocr_paths)
                        try:
                            recognized = crop_ocr(str(image_path))
                            ocr_text = "\n".join(recognized.txts or [])
                        except Exception:
                            warnings.append("PICTURE_OCR_UNAVAILABLE")
                        if not captions:
                            warnings.append("PICTURE_CAPTION_NOT_ASSOCIATED")
            elements.append(
                Element(
                    id=item.self_ref,
                    kind=kind,
                    order=len(elements),
                    text=text,
                    section=tuple(value for _, value in sections),
                    locations=locations,
                    captions=captions,
                    footnotes=footnotes,
                    table=table,
                    asset_id=asset_id,
                    ocr_text=ocr_text,
                )
            )
        if not elements:
            raise KnowledgeError("PARSE_EMPTY")
        parsed = ParsedDocument(
            source_sha256=file_hash(source),
            parser_version=f"docling/{PARSER_VERSION}",
            settings_sha256=settings_hash,
            models_sha256=models_hash,
            page_count=len(doc.pages),
            elements=tuple(elements),
            assets=tuple(assets),
            raw_sha256=file_hash(output / "docling.json"),
            warnings=tuple(dict.fromkeys(warnings)),
            software_versions={
                package: importlib.metadata.version(package)
                for package in (
                    "docling",
                    "docling-core",
                    "docling-ibm-models",
                    "docling-parse",
                    "torch",
                    "rapidocr",
                    "onnxruntime",
                )
            },
            page_text_cells={
                str(page.page_no + 1): [cell.model_dump(mode="json") for cell in page.cells]
                for page in result.pages
            },
        )
        (output / "parsed.json").write_text(parsed.model_dump_json(), encoding="utf-8")
        return parsed

    @staticmethod
    def _crop_ocr(paths: dict[str, str]) -> Any:
        rapid = importlib.import_module("rapidocr")
        params: dict[str, Any] = {"Global.text_score": 0.5}
        for name, key in (
            ("Det", "det_model_path"),
            ("Cls", "cls_model_path"),
            ("Rec", "rec_model_path"),
        ):
            params.update(
                {
                    f"{name}.model_path": paths[key],
                    f"{name}.use_cuda": False,
                    f"{name}.use_dml": False,
                    f"{name}.intra_op_num_threads": 2,
                    f"{name}.engine_type": rapid.EngineType.ONNXRUNTIME,
                }
            )
        params["Rec.keys_path"] = paths["rec_keys_path"]
        return rapid.RapidOCR(params=params)
