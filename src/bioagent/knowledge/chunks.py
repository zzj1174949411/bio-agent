"""Element-preserving chunks: quoted text and context have separate provenance."""

import json
from hashlib import sha256
from uuid import uuid4

from bioagent.knowledge.models import ParsedDocument
from bioagent.knowledge.retrieval_models import Chunk
from bioagent.knowledge.store import KnowledgeError


def digest_chunk(chunk: Chunk) -> str:
    # Hash all source-bearing fields, including section/context/asset/location.
    data = chunk.model_dump(mode="json", exclude={"id", "content_sha256"})
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def chunks(parsed: ParsedDocument) -> tuple[Chunk, ...]:
    output = []
    for index, element in enumerate(parsed.elements):
        if not element.locations:
            # Never invent a page for a parser element with no provenance.
            continue
        text = "\n".join(
            filter(None, [*element.captions, element.text, element.ocr_text, *element.footnotes])
        )
        if not text.strip():
            continue
        if sum(len(section) for section in element.section) > 2000:
            raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
        neighbors = [
            other
            for other in parsed.elements[max(0, index - 1) : index + 2]
            if other.id != element.id
            and other.kind not in {"table", "picture"}
            and other.section == element.section
            and other.locations
            and other.locations[0].page == element.locations[0].page
            and other.text
        ]
        context = "\n".join(other.text[:100] for other in neighbors)
        # Character windows keep original Unicode unchanged. The embedding adapter
        # further partitions >512-token inputs and pools their vectors; no text is dropped.
        if element.kind == "table":
            cells = (element.table or {}).get("table_cells", [])
            header = " | ".join(
                str(cell.get("text", "")) for cell in cells if cell.get("column_header")
            )
            if not header:
                header = "\n".join(element.text.splitlines()[:3])
            metadata = "\n".join([*element.captions, header, *element.footnotes])
            if len(metadata) > 2800:
                raise KnowledgeError("INDEX_CONTEXT_TOO_LARGE")
            parts = [
                metadata + "\n" + text[start : start + 1200] for start in range(0, len(text), 1200)
            ]
        else:
            parts = [text[start : start + 1200] for start in range(0, len(text), 1100)]
        for part, body in enumerate(parts):
            chunk = Chunk(
                id=uuid4(),
                element_id=element.id,
                parent_element_id=element.id if part else None,
                kind=element.kind,
                section=element.section,
                text=body,
                context=context,
                context_element_ids=tuple(other.id for other in neighbors),
                locations=element.locations,
                asset_id=element.asset_id,
                part=part,
                content_sha256="0" * 64,
            )
            output.append(chunk.model_copy(update={"content_sha256": digest_chunk(chunk)}))
            if len(output) > 5000:
                raise KnowledgeError("INDEX_TOO_LARGE")
    return tuple(output)
