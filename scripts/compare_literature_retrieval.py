"""Local-only Task45 retrieval ablations; never constructs an LLM or reads credentials.

Run baseline before implementation; run merge/rechunk after. Reports contain licensed
paper excerpts and must stay under ignored data/. Reference notes are used ONLY after
retrieval, for exact source-interval coverage, never as retrieval input.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from bioagent.knowledge.answers import SYSTEM
from bioagent.knowledge.hybrid import HybridRetriever, context_payload
from bioagent.knowledge.retrieval import RetrievalEngine
from bioagent.knowledge.retrieval_models import SearchHit
from bioagent.knowledge.store import KnowledgeStore, file_hash
from bioagent.knowledge.wiki import WikiService


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def message_bytes(question, payload):
    system = SYSTEM + (
        "\nWiki navigation is AI-derived, unreviewed and not an "
        "independent study. Use it only as navigation; facts and "
        "numbers require the supplied original "
        "evidence and its chunk citations. Preserve differing study conditions."
        if payload.get("wiki_navigation") else ""
    )
    return len(system.encode()) + len(json.dumps(
        {"question": question, **payload}, ensure_ascii=False
    ).encode())


def inputs(root):
    paths = {
        "sources": Path("data/task44/pilot-preparation/sources.json"),
        "notes": Path("data/task44/pilot-preparation/pilot-notes.json"),
        "dataset": Path("data/task44/real-pilot/dataset.json"),
    }
    hashes = {key: file_hash(path) for key, path in paths.items()}
    lock = root / "inputs.json"
    if lock.exists():
        assert json.loads(lock.read_text(encoding="utf-8"))["sha256"] == hashes
    else:
        write(
            lock,
            {
                "sha256": hashes,
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "context_max_bytes": 24000,
                "top_k": 6,
            },
        )
        for key, path in paths.items():
            shutil.copyfile(path, root / f"{key}.json")
    return {key: json.loads((root / f"{key}.json").read_text(encoding="utf-8")) for key in paths}


def coverage(note, result, docs, parsed, sources):
    details = []
    for ref in note.get("references", []):
        source = next(s for s in sources if s["source_document_id"] == ref["source_document_id"])
        doc = next(d for d in docs if d["source_sha256"] == source["sha256"])
        element = next(e for e in parsed[doc["id"]]["elements"] if e["id"] == ref["element_id"])
        text, quote = element["text"], ref["quote"]
        offset = text.find(quote)
        mapped = (
            offset >= 0
            and text.count(quote) == 1
            and ref["page"] in [loc["page"] for loc in element["locations"]]
        )
        covered = set()
        if mapped:
            for hit in result.page.items:
                if str(hit.reference.document_id) != doc["id"]:
                    continue
                # New chunks expose all precise sources. Legacy chunks are mapped to
                # their actual element, including separately declared neighbor context.
                spans = getattr(hit.chunk, "sources", ())
                if spans:
                    intervals = [
                        (s.start, s.end)
                        for s in spans
                        if s.element_id == ref["element_id"]
                        and s.field == "text"
                        and s.text == text[s.start : s.end]
                        and s.text == hit.chunk.text[s.chunk_start : s.chunk_end]
                        and any(loc.page == ref["page"] for loc in s.locations)
                    ]
                else:
                    intervals = []
                    if hit.chunk.element_id == ref["element_id"]:
                        intervals.extend(legacy_intervals(hit.chunk, element))
                    if ref["element_id"] in hit.chunk.context_element_ids:
                        by_id = {e["id"]: e for e in parsed[doc["id"]]["elements"]}
                        actual_context = "\n".join(
                            by_id[key]["text"][:100] for key in hit.chunk.context_element_ids
                        )
                        if actual_context == hit.chunk.context:
                            intervals.append((0, min(100, len(text))))
                for a, end in intervals:
                    covered.update(range(max(a, offset), min(end, offset + len(quote))))
        details.append(
            {
                "element_id": ref["element_id"],
                "page": ref["page"],
                "source_sha256": source["sha256"],
                "quote": quote,
                "mapped": mapped,
                "covered": mapped and len(covered) == len(quote),
                "covered_chars": len(covered),
                "required_chars": len(quote),
            }
        )
    return details


def legacy_intervals(chunk, element):
    """Recreate old fixed windows exactly; no fuzzy matching or scattered letters."""
    values = [*element["captions"], element["text"], element["ocr_text"], *element["footnotes"]]
    joined = "\n".join(v for v in values if v)
    # The text field's offset follows the nonempty captions, even when repeated elsewhere.
    text_offset = sum(len(v) + 1 for v in element["captions"] if v)
    prefix = ""
    step = 1100
    if element["kind"] == "table":
        cells = (element.get("table") or {}).get("table_cells", [])
        header = " | ".join(str(c.get("text", "")) for c in cells if c.get("column_header"))
        header = header or "\n".join(element["text"].splitlines()[:3])
        prefix = "\n".join([*element["captions"], header, *element["footnotes"]]) + "\n"
        step = 1200
    start = chunk.part * step
    if prefix + joined[start : start + 1200] != chunk.text:
        return []  # Ambiguous/unrecognized legacy data stays uncovered.
    return [(max(0, start - text_offset), min(len(element["text"]), start + 1200 - text_offset))]


def run(args):
    root = args.output.resolve()
    assert root.is_relative_to(Path("data/task45").resolve()), "ignored Task45 output only"
    root.mkdir(parents=True, exist_ok=True)
    data = inputs(root)
    questions = {q["id"]: q for q in data["dataset"]["questions"]}
    assert len(questions) == len(data["notes"]["questions"]) == 10
    assert all(
        q["question"] == questions[q["id"]]["question"]
        and q["reference_claims"] == questions[q["id"]]["reference_claims"]
        for q in data["notes"]["questions"]
    )
    phase = args.phase
    if phase == "baseline":
        # This experiment's old implementation is fixed. Refuse to silently label
        # the new working tree as the old algorithm on a later rerun.
        for filename in ("chunks.py", "hybrid.py", "retrieval.py", "retrieval_models.py"):
            relative = "src/bioagent/knowledge/" + filename
            old = subprocess.check_output(["git", "show", "e5da324:" + relative]).decode()
            current = Path(relative).read_text(encoding="utf-8")
            assert (
                hashlib.sha256(old.replace("\r\n", "\n").encode()).digest()
                == hashlib.sha256(current.replace("\r\n", "\n").encode()).digest()
            ), "baseline requires e5da324 code"
    if phase in {"merge", "rechunk"}:
        assert not (root / f"{phase}.json").exists(), "locked run must not be overwritten"
    target = root / ("new" if phase == "rechunk" else "old") / "knowledge"
    if phase == "baseline":
        assert not target.exists(), "baseline must be locked once, never overwritten"
        shutil.copytree(Path("data/task44/real-pilot/knowledge"), target)
    elif phase == "rechunk":
        assert not target.exists(), "rechunk once; do not tune on outcomes"
        shutil.copytree(root / "old/knowledge", target)
    assert target.exists()
    store = KnowledgeStore(target)
    engine = RetrievalEngine(store, Path("data/embedding-models"))
    # pages()/source validation do not access these dependencies. Build is never called.
    wiki = WikiService(engine, None, None)
    router = HybridRetriever(engine, wiki)
    bases = [b["id"] for b in store.bases()]
    docs = [d for b in bases for d in store.documents(b)]
    assert len(docs) == 3
    assert (
        {d["source_sha256"] for d in docs}
        == {s["sha256"] for s in data["sources"]}
        == {s["source_sha256"] for s in data["dataset"]["corpus"]}
    )
    parsed = {d["id"]: store.parsed(d["id"], d["published_revision"]) for d in docs}
    source_snapshot = [
        {
            "source_sha256": p["source_sha256"],
            "parser_version": p["parser_version"],
            "parsed_sha256": p["parsed_sha256"],
            "settings_sha256": p["settings_sha256"],
        }
        for p in parsed.values()
    ]
    if phase != "baseline":
        locked = json.loads((root / "baseline.json").read_text(encoding="utf-8"))
        assert sorted(source_snapshot, key=lambda s: s["source_sha256"]) == sorted(
            locked["source_snapshot"], key=lambda s: s["source_sha256"]
        )
    for doc in docs:
        store.original(doc["id"])
    try:
        if phase == "score":
            from types import SimpleNamespace

            raw = json.loads((root / "baseline.json").read_text(encoding="utf-8"))
            for item in raw["questions"]:
                if item["status"] != "OK":
                    continue
                result = SimpleNamespace(
                    page=SimpleNamespace(
                        items=tuple(SearchHit.model_validate(h) for h in item["hits"])
                    )
                )
                note = next(q for q in data["notes"]["questions"] if q["id"] == item["id"])
                item["references"] = coverage(note, result, docs, parsed, data["sources"])
                item["covered"] = sum(r["covered"] for r in item["references"])
            raw["scoring"] = "exact-source-interval-v2; raw baseline preserved"
            write(root / "baseline-scored.json", raw)
            return
        if phase == "rechunk":
            for doc in docs:
                started = time.perf_counter()
                job = engine.build(doc["id"])
                print(
                    json.dumps(
                        {
                            "stage": "build",
                            "status": job.status,
                            "seconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
                if job.status != "READY":
                    write(
                        root / "rechunk.json",
                        {
                            "phase": phase,
                            "source_snapshot": source_snapshot,
                            "build_error": job.error_code,
                            "questions": [
                                {
                                    "id": q["id"],
                                    "mode": "rag",
                                    "status": "FAILED",
                                    "covered": 0,
                                    "required": len(q.get("references", [])),
                                    "error": "INDEX_BUILD_FAILED",
                                }
                                for q in data["notes"]["questions"]
                            ],
                            "new_answers": "NOT_RUN_NO_NEW_LLM_BUDGET",
                        },
                    )
                    return
            assert not any(p.status == "CURRENT" for base in bases for p in wiki.pages(base).items)
        # Warm model outside timings, but hash/source checks remain on every real query.
        engine._runtime()
        fixed = engine.snapshot(bases)
        frozen = router.snapshot(bases) if phase != "rechunk" else ()
        output = {
            "phase": phase,
            "source_snapshot": source_snapshot,
            "context_max_bytes": 24000,
            "top_k": 6,
            "questions": [],
            "new_answers": "NOT_RUN_NO_NEW_LLM_BUDGET",
        }
        for note in data["notes"]["questions"]:
            for mode in (
                ("rag", "hybrid")
                if phase == "baseline"
                else ("hybrid",)
                if phase == "merge"
                else ("rag",)
            ):
                started = time.perf_counter()
                try:
                    result = router.retrieve(
                        note["question"], bases, mode, fixed, frozen, 24000, strict=True
                    )
                    elapsed = time.perf_counter() - started
                    details = coverage(note, result, docs, parsed, data["sources"])
                    chunks = [h.chunk for h in result.page.items]
                    item = {
                        "id": note["id"],
                        "mode": mode,
                        "status": "OK",
                        "answerable": note["answerable"],
                        "seconds": elapsed,
                        "references": details,
                        "covered": sum(r["covered"] for r in details),
                        "required": len(details),
                        "audit": result.audit.model_dump(mode="json"),
                        "isolated_short_non_table": sum(
                            c.kind != "table" and len(c.text.strip()) < 80 for c in chunks
                        ),
                        "duplicate_text": len(chunks) - len({c.text for c in chunks}),
                        "payload": context_payload(result.page.items, result.navigation),
                        "prepared_message_input_bytes": message_bytes(
                            note["question"], context_payload(result.page.items, result.navigation)
                        ),
                        "hits": [h.model_dump(mode="json") for h in result.page.items],
                    }
                except Exception as error:
                    item = {
                        "id": note["id"],
                        "mode": mode,
                        "status": "FAILED",
                        "error": type(error).__name__ + ":" + str(error),
                        "covered": 0,
                        "required": len(note.get("references", [])),
                        "seconds": time.perf_counter() - started,
                    }
                output["questions"].append(item)
                write(root / f"{phase}.json", output)
                print(
                    json.dumps(
                        {
                            k: item[k]
                            for k in ("id", "mode", "status", "covered", "required", "seconds")
                        }
                    ),
                    flush=True,
                )
        manifests = [
            engine._manifest(row, verify_vectors=False) for row in engine.catalog.active(bases)
        ]
        output["index_stats"] = [
            {
                "chunks": len(m["chunks"]),
                "algorithm": m.get("chunking_algorithm", "element-char1200-v1"),
                "short_non_table": sum(
                    c["kind"] != "table" and len(c["text"].strip()) < 80 for c in m["chunks"]
                ),
            }
            for m in manifests
        ]
        write(root / f"{phase}.json", output)
    finally:
        engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("baseline", "merge", "rechunk", "score"), required=True)
    parser.add_argument("--output", type=Path, default=Path("data/task45/comparison"))
    run(parser.parse_args())
