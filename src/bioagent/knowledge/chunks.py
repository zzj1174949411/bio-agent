"""Token-aware excerpts with exact, independently verified source slices."""

import json
import re
from collections.abc import Callable
from hashlib import sha256
from typing import Any
from uuid import uuid4

from bioagent.knowledge.models import Element, ParsedDocument
from bioagent.knowledge.retrieval_models import Chunk, SourceSpan
from bioagent.knowledge.store import KnowledgeError

LEGACY = "element-char1200-v1"
ALGORITHM = "section-sentence-e5-400-450-table-rows-v2"
TARGET, MAX_TOKENS = 400, 450
_NEW_FIELDS = {"sources", "chunking_algorithm", "token_count", "token_overflow"}


def digest_chunk(chunk: Chunk) -> str:
    excluded = {"id", "content_sha256"}
    if chunk.chunking_algorithm == LEGACY:
        excluded |= _NEW_FIELDS
    data = chunk.model_dump(mode="json", exclude=excluded)
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def digest_element(element: Element) -> str:
    return sha256(
        json.dumps(element.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def source_map(chunk: Chunk) -> list[dict[str, Any]]:
    """Compact model input: slices point into text already present in the payload."""
    return [
        {
            **s.model_dump(mode="json", exclude={"text", "locations"}),
            "pages": list(dict.fromkeys(loc.page for loc in s.locations)),
        }
        for s in chunk.sources
    ]


def _field(element: Element, field: str, index: int) -> str:
    if field == "table_cells":
        return str((element.table or {})["table_cells"][index].get("text", ""))
    value = getattr(element, field)
    return str(value[index] if field in {"captions", "footnotes"} else value)


def _span(element: Element, field: Any, start: int, end: int, index: int = 0) -> SourceSpan:
    return SourceSpan(
        element_id=element.id,
        field=field,
        field_index=index,
        start=start,
        end=end,
        text=_field(element, field, index)[start:end],
        chunk_start=0,
        chunk_end=end - start,
        locations=element.locations,
        source_sha256=digest_element(element),
    )


def validate_sources(chunk: Chunk, parsed: ParsedDocument) -> None:
    if chunk.chunking_algorithm == LEGACY:
        if chunk.sources:
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
        return
    if chunk.chunking_algorithm != ALGORITHM or not chunk.sources:
        raise KnowledgeError("INDEX_INTEGRITY_FAILED")
    elements = {e.id: e for e in parsed.elements}
    try:
        attributed: set[int] = set()
        for source in chunk.sources:
            element = elements[source.element_id]
            value = _field(element, source.field, source.field_index)
            if (
                source.source_sha256 != digest_element(element)
                or source.locations != element.locations
                or (source.field in {"text", "ocr_text"} and source.field_index != 0)
                or source.end <= source.start
                or source.end > len(value)
                or value[source.start : source.end] != source.text
                or source.chunk_end > len(chunk.text)
                or chunk.text[source.chunk_start : source.chunk_end] != source.text
            ):
                raise KnowledgeError("INDEX_INTEGRITY_FAILED")
            attributed.update(range(source.chunk_start, source.chunk_end))
        if any(not ch.isspace() and i not in attributed for i, ch in enumerate(chunk.text)):
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
        if (
            chunk.element_id != chunk.sources[0].element_id
            or chunk.locations != chunk.sources[0].locations
            or chunk.context
            or chunk.context_element_ids
        ):
            raise KnowledgeError("INDEX_INTEGRITY_FAILED")
    except (KeyError, IndexError, TypeError) as error:
        raise KnowledgeError("INDEX_INTEGRITY_FAILED") from error


def chunks(
    parsed: ParsedDocument, *, count_tokens: Callable[[str], int] | None = None
) -> tuple[Chunk, ...]:
    # Production supplies pinned E5. Byte counting bounds explicit test embeddings
    # conservatively and introduces no second production model/tokenizer.
    count = count_tokens or (lambda text: len(text.encode("utf-8")))
    output: list[Chunk] = []
    pending: list[SourceSpan] = []
    section: tuple[str, ...] = ()
    part = 0

    def size(body: str, headings: tuple[str, ...]) -> int:
        return count("\n".join([*headings, body, ""]))

    def emit(
        spans: list[SourceSpan], text: str, element: Element, headings: tuple[str, ...]
    ) -> None:
        nonlocal part
        if not text.strip() or not spans:
            return
        compact: list[SourceSpan] = []
        for span in spans:
            previous = compact[-1] if compact else None
            if (
                previous
                and (span.element_id, span.field, span.field_index, span.start)
                == (previous.element_id, previous.field, previous.field_index, previous.end)
                and previous.text + span.text in text
            ):
                compact[-1] = previous.model_copy(
                    update={"end": span.end, "text": previous.text + span.text}
                )
            else:
                compact.append(span)
        spans = []
        cursor = 0
        for span in compact:
            start = text.find(span.text, cursor)
            if start < 0:
                raise KnowledgeError("INDEX_INTEGRITY_FAILED")
            cursor = start + len(span.text)
            spans.append(span.model_copy(update={"chunk_start": start, "chunk_end": cursor}))
        tokens = size(text, headings)
        if tokens > MAX_TOKENS and element.kind in {"text", "paragraph", "list_item", "formula"}:
            raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
        chunk = Chunk(
            id=uuid4(),
            element_id=spans[0].element_id,
            parent_element_id=spans[0].element_id if part else None,
            kind=element.kind,
            section=headings,
            text=text,
            locations=spans[0].locations,
            asset_id=element.asset_id,
            part=part,
            sources=tuple(spans),
            chunking_algorithm=ALGORITHM,
            token_count=tokens,
            token_overflow=tokens > MAX_TOKENS,
            content_sha256="0" * 64,
        )
        output.append(chunk.model_copy(update={"content_sha256": digest_chunk(chunk)}))
        part += 1
        if len(output) > 5000:
            raise KnowledgeError("INDEX_TOO_LARGE")

    elements = {e.id: e for e in parsed.elements}

    def body(spans: list[SourceSpan]) -> str:
        result = ""
        previous = None
        for span in spans:
            if previous and (span.element_id, span.field, span.field_index) != (
                previous.element_id,
                previous.field,
                previous.field_index,
            ):
                result += "\n\n"
            result += span.text
            previous = span
        return result

    def flush() -> None:
        nonlocal pending
        if pending:
            emit(pending, body(pending), elements[pending[0].element_id], section)
            pending = []

    for element in parsed.elements:
        if not element.locations:
            flush()
            continue
        if sum(len(h) for h in element.section) > 2000:
            raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
        if size("", element.section) >= MAX_TOKENS:
            raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
        if element.kind == "table":
            flush()
            metadata = []
            for field in ("captions", "footnotes"):
                for i, value in enumerate(getattr(element, field)):
                    if value:
                        metadata.append(_span(element, field, 0, len(value), i))
            lines = [m for m in re.finditer(r"[^\n]*(?:\n|$)", element.text) if m.end() > m.start()]
            separator = next(
                (
                    i
                    for i, line in enumerate(lines)
                    if re.fullmatch(r"[\s|:\-]+", line.group()) and "-" in line.group()
                ),
                None,
            )
            header_end = (
                lines[separator].end()
                if separator is not None
                else (lines[0].end() if lines else 0)
            )
            if header_end:
                metadata.append(_span(element, "text", 0, header_end))
            for i, cell in enumerate((element.table or {}).get("table_cells", [])):
                value = str(cell.get("text", ""))
                if cell.get("column_header") and value and value not in element.text[:header_end]:
                    metadata.append(_span(element, "table_cells", 0, len(value), i))
            prefix = "\n".join(s.text for s in metadata)
            if len(prefix) > 2800:
                raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
            rows: list[SourceSpan] = []
            for line in lines:
                if line.start() < header_end:
                    continue
                row = _span(element, "text", line.start(), line.end())
                candidate = prefix + "\n" + "".join(s.text for s in [*rows, row])
                if rows and size(candidate, element.section) > MAX_TOKENS:
                    emit(
                        [*metadata, *rows],
                        prefix + "\n" + "".join(s.text for s in rows),
                        element,
                        element.section,
                    )
                    rows = []
                rows.append(row)
            emit(
                [*metadata, *rows],
                prefix + "\n" + "".join(s.text for s in rows),
                element,
                element.section,
            )
            continue
        if element.kind not in {"text", "paragraph", "list_item", "formula"}:
            flush()
            if element.kind in {"picture", "chart", "caption"}:
                spans = []
                for field in ("captions", "text", "ocr_text", "footnotes"):
                    values = getattr(element, field)
                    for i, value in enumerate(values if isinstance(values, tuple) else (values,)):
                        if value:
                            spans.append(_span(element, field, 0, len(value), i))
                text = "\n".join(s.text for s in spans)
                if len(text.strip()) >= 40 or element.captions:
                    emit(spans, text, element, element.section)
            continue
        if element.section != section:
            flush()
            section = element.section
        if pending and pending[0].locations[0].page != element.locations[0].page:
            flush()  # Existing preview links show one page; never mislabel a merged page.
        if len(element.text.strip()) < 3 or (
            element.kind in {"text", "paragraph"}
            and len(element.text.strip()) < 40
            and not re.search(r"[.!?。！？]", element.text)
        ):
            continue
        for sentence in re.finditer(
            r".+?(?:[.!?](?=\s|$)\s*|\n\s*\n|$)", element.text, flags=re.DOTALL
        ):
            start, end = sentence.span()
            while start < end:
                span = _span(element, "text", start, end)
                if pending and size(body([*pending, span]), section) > MAX_TOKENS:
                    flush()
                if size(span.text, section) > MAX_TOKENS:
                    lo, hi = start + 1, end
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        if size(element.text[start:mid], section) <= TARGET:
                            lo = mid
                        else:
                            hi = mid - 1
                    stop = lo
                    boundary = element.text.rfind(" ", start + 1, stop)
                    if boundary > start:
                        stop = boundary + 1
                    span = _span(element, "text", start, stop)
                pending.append(span)
                start = span.end
                if size(body(pending), section) >= TARGET:
                    flush()
    flush()
    return tuple(output)
