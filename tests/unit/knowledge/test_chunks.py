"""Task45 focused structural/token/provenance regressions."""

import json
from hashlib import sha256

import pytest

from bioagent.knowledge.chunks import chunks, digest_chunk, validate_sources
from bioagent.knowledge.models import Element, Location, ParsedDocument
from bioagent.knowledge.retrieval_models import Chunk
from bioagent.knowledge.store import KnowledgeError


def parsed(elements):
    return ParsedDocument(
        source_sha256="0" * 64,
        parser_version="fixture",
        settings_sha256="0" * 64,
        models_sha256="0" * 64,
        raw_sha256="0" * 64,
        page_count=2,
        elements=tuple(elements),
    )


def element(index, text, **kwargs):
    return Element(
        id=f"#/texts/{index}",
        order=index,
        kind="text",
        text=text,
        section=("Methods",),
        locations=(Location(page=1, bbox=(0, 0, 10, 10), origin="TOPLEFT"),),
        **kwargs,
    )


def test_same_section_paragraphs_merge_without_inventing_first_element_origin():
    doc = parsed(
        [
            element(0, "First sentence ends here."),
            element(1, "Second paragraph has the units 13.5 h."),
        ]
    )
    result = chunks(doc)
    assert len(result) == 1
    chunk = result[0]
    assert chunk.text == "First sentence ends here.\n\nSecond paragraph has the units 13.5 h."
    assert {s.element_id for s in chunk.sources} == {e.id for e in doc.elements}
    assert {loc.page for s in chunk.sources for loc in s.locations} == {1}
    assert all(s.text in chunk.text and len(s.source_sha256) == 64 for s in chunk.sources)
    assert chunk.content_sha256 == digest_chunk(chunk)
    validate_sources(chunk, doc)
    with pytest.raises(KnowledgeError, match="INDEX_INTEGRITY_FAILED"):
        validate_sources(chunk.model_copy(update={"text": chunk.text + " invented fact"}), doc)
    with pytest.raises(KnowledgeError, match="INDEX_INTEGRITY_FAILED"):
        source = chunk.sources[1].model_copy(update={"source_sha256": "0" * 64})
        validate_sources(chunk.model_copy(update={"sources": (chunk.sources[0], source)}), doc)
    next_page = doc.elements[1].model_copy(
        update={"locations": (Location(page=2, bbox=(0, 0, 10, 10), origin="TOPLEFT"),)}
    )
    split = chunks(parsed([doc.elements[0], next_page]))
    assert len(split) == 2 and split[1].locations[0].page == 2


def test_token_limit_preserves_sentences_and_does_not_emit_short_ocr_labels():
    text = "A complete sentence has measured quantities. " * 50
    doc = parsed([element(0, text), element(1, "A"), element(2, "B")])
    result = chunks(doc, count_tokens=lambda value: len(value.encode()))
    assert len(result) > 1
    assert all(len("\n".join([*c.section, c.text, c.context]).encode()) <= 450 for c in result)
    assert all(c.text.rstrip().endswith(".") for c in result)
    assert "".join(s.text for c in result for s in c.sources) == text
    assert not any(c.text in {"A", "B"} for c in result)


def test_table_rows_repeat_units_caption_footnote_without_cutting_cells():
    rows = [f"| Method{n} | {n}.25 ± 0.01 |" for n in range(25)]
    table = element(0, "| Method | Time (h) |\n|---|---|\n" + "\n".join(rows))
    table = table.model_copy(
        update={
            "kind": "table",
            "captions": ("Table 2 Runtime",),
            "footnotes": ("* Mean ± SD across 5 runs.",),
        }
    )
    result = chunks(parsed([table]))
    assert len(result) > 1
    assert all(
        "Table 2 Runtime" in c.text
        and "Time (h)" in c.text
        and "Mean ± SD across 5 runs." in c.text
        for c in result
    )
    for row in rows:
        assert sum(row in c.text for c in result) == 1
    assert all(s.text in c.text for c in result for s in c.sources)


def test_legacy_digest_ignores_new_default_fields():
    data = dict(
        id="00000000-0000-4000-8000-000000000000",
        element_id="#/texts/0",
        parent_element_id=None,
        kind="text",
        section=[],
        text="old",
        context="",
        context_element_ids=[],
        locations=[dict(page=1, bbox=[0.0, 0.0, 1.0, 1.0], origin="TOPLEFT")],
        asset_id=None,
        part=0,
        content_sha256="0" * 64,
        visual_semantics="not_performed",
    )
    expected = sha256(
        json.dumps(
            {k: v for k, v in data.items() if k not in {"id", "content_sha256"}},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert digest_chunk(Chunk.model_validate(data)) == expected
