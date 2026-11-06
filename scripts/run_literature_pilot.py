"""Explicit live ten-question pilot in an isolated local store, with a durable global ledger.

The operator must have authorized the corpus, profile and limits before --live.
No raw provider errors or credentials are printed. No automatic retries or model changes.
"""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from uuid import UUID

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, SystemMessage
from verify_literature_retrieval import wait

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.knowledge.evaluation import (
    EvaluationDataset,
    LiveBudget,
    export_blind,
    run_evaluation,
    write_report,
)
from bioagent.knowledge.retrieval_models import Chunk, EvaluationControls, LocalEvidence
from bioagent.knowledge.store import KnowledgeError
from bioagent.models.adapters import ModelAdapter, error_code
from bioagent.models.evaluation_limits import bind_output_limit, validate_snapshot
from bioagent.models.profiles import ModelProfile


class Ledger:
    def __init__(self, path: Path):
        self.path, self.lock = path, RLock()
        self.data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {
                "limits": {
                    "calls": 50,
                    "message_input_bytes": 1600000,
                    "message_input_bytes_per_call": 32000,
                    "output_tokens_per_call": 2000,
                },
                "calls": [],
                "stopped": False,
                "token_and_money_upper_bound": None,
            }
        )

    def save(self):
        write_report(self.data, self.path)

    def resume_after_fix(self):
        """Only a human-authorized CLI continuation; never reset counters or unknown usage."""
        with self.lock:
            if any(c["status"] == "RESERVED_UNKNOWN" for c in self.data["calls"]):
                raise KnowledgeError("PILOT_UNKNOWN_INFLIGHT")
            if not self.data["calls"] or not self.data["stopped"]:
                raise KnowledgeError("PILOT_NOT_STOPPED")
            self.data.setdefault("resume_events", []).append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "calls_before": len(self.data["calls"]),
                    "input_bytes_before": sum(c["input_bytes"] for c in self.data["calls"]),
                    "previous_stopped": True,
                    "reason": "explicit continuation after validated repair",
                }
            )
            self.data["stopped"] = False
            self.save()

    def stop(self, reason):
        with self.lock:
            self.data["stopped"] = True
            self.data["last_stop_reason"] = reason
            self.save()

    def reserve(self, messages, limit):
        content = "\n".join(str(m.content) for m in messages)
        size = sum(len(str(m.content).encode()) for m in messages)
        with self.lock:
            if (
                self.data["stopped"]
                or len(self.data["calls"]) >= 50
                or size > 32000
                or sum(c["input_bytes"] for c in self.data["calls"]) + size > 1600000
                or not 1 <= limit <= 2000
            ):
                raise KnowledgeError("PILOT_GLOBAL_BUDGET_STOP")
            number = len(self.data["calls"]) + 1
            self.data["calls"].append(
                {
                    "number": number,
                    "input_bytes": size,
                    "input_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "output_token_limit": limit,
                    "status": "RESERVED_UNKNOWN",
                    "usage": None,
                }
            )
            self.save()  # Reserve before invocation; failures and crashes never refund.
            return number

    def finish(self, number, status, usage=None, finish_reason=None):
        with self.lock:
            row = self.data["calls"][number - 1]
            row.update(status=status, usage=usage, finish_reason=finish_reason)
            if status != "RESPONSE_RECEIVED":
                self.data["stopped"] = True
            self.save()


class BudgetedModel:
    def __init__(self, model, ledger, limit=0):
        self.model, self.ledger, self.limit = model, ledger, limit

    def bind(self, **options):
        limit = options.get("extra_body", {}).get("max_tokens", options.get("max_tokens", 0))
        return BudgetedModel(self.model.bind(**options), self.ledger, limit or self.limit)

    async def ainvoke(self, messages):
        number = self.ledger.reserve(messages, self.limit)
        try:
            response = await self.model.ainvoke(messages)
        except Exception as error:
            self.ledger.finish(number, error_code(error))
            raise
        metadata = getattr(response, "response_metadata", {})
        reason = metadata.get("finish_reason") if isinstance(metadata, dict) else None
        reason = reason if reason in {"stop", "length", "tool_calls", "content_filter"} else None
        self.ledger.finish(
            number, "RESPONSE_RECEIVED", getattr(response, "usage_metadata", None), reason
        )
        content = getattr(response, "content", None)
        if isinstance(content, str) and len(content.encode()) <= 64000:
            write_report(
                {"content": content, "finish_reason": reason},
                self.ledger.path.parent / "model-responses" / f"call-{number}.json",
            )
        return response


class BudgetedAdapter:
    def __init__(self, adapter, ledger):
        self.adapter, self.ledger = adapter, ledger

    def prepare(self, identity, fixed):
        model, snapshot = self.adapter.prepare(identity, fixed)
        return BudgetedModel(model, self.ledger), snapshot


def run_probe(client, model):
    """Keep SDK cached async connections on the same loop as backend Wiki/Ask calls."""
    if client.portal is None:
        raise KnowledgeError("PILOT_BACKEND_NOT_RUNNING")
    return client.portal.call(
        model.ainvoke,
        [SystemMessage("Return only JSON."), HumanMessage('{"ok":true}')],
    )


def build_limits(ledger, documents):
    capacity = min(19, 50 - len(ledger.data["calls"]) - 30)
    if capacity < documents + 1:
        raise KnowledgeError("PILOT_QUERY_BUDGET_RESERVED")
    return {"max_calls": capacity, "max_segments_per_document": min(4, (capacity - 1) // documents)}


def reference_chunks(chunks, reference):
    """Map an exact verified quote, including a span split into source windows."""
    quote = reference["quote"]
    exact = [c for c in chunks if quote in c.text]
    if exact:
        return exact[:1]
    pool = [
        c
        for c in chunks
        if c.element_id == reference["element_id"] and c.locations[0].page == reference["page"]
    ]
    remaining, selected = quote, []
    while remaining:
        match, length = None, 0
        for chunk in pool:
            for count in range(len(remaining), min(16, len(remaining)) - 1, -1):
                if remaining[:count] in chunk.text:
                    if count > length:
                        match, length = chunk, count
                    break
        if match is None:
            raise KnowledgeError("PILOT_REFERENCE_NOT_IN_CHUNK")
        if match not in selected:
            selected.append(match)
        remaining = remaining[length:]
    return selected


def run(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "global-ledger.json")
    if args.resume_after_fix and not args.live:
        raise KnowledgeError("PILOT_LIVE_RESUME_REQUIRED")
    if ledger.data["calls"] and not args.resume_after_fix:
        raise KnowledgeError("PILOT_ALREADY_STARTED")  # No automatic resume/retry.
    ledger.save()
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    notes = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
    if not 3 <= len(sources) <= 5 or len(notes) != 10:
        raise KnowledgeError("PILOT_INPUT_INVALID")
    # Copy public configuration plus its opaque credential reference, never the secret.
    with sqlite3.connect(args.profile_db.resolve().as_uri() + "?mode=ro", uri=True) as db:
        record = db.execute(
            "SELECT record FROM model_profiles WHERE id=? AND deleted=0", (str(args.profile_id),)
        ).fetchone()
    if record is None:
        raise KnowledgeError("MODEL_NOT_CONFIGURED")
    profile = ModelProfile.model_validate_json(record[0])
    if profile.provider != "deepseek" or profile.thinking != "disabled":
        raise KnowledgeError("EVALUATION_LIMITS_UNSUPPORTED")
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=root / "data",
        runs_dir=root / "runs",
        checkpoint_db=root / "cp.sqlite",
        workbench_db=root / "wb.sqlite",
        knowledge_dir=root / "knowledge",
        knowledge_models_dir=Path("data/task38/models").resolve(),
        knowledge_embedding_models_dir=Path("data/embedding-models").resolve(),
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost") as client:
        deps = app.state.dependencies
        with deps.model_profiles._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO model_profiles VALUES(?,?,0)",
                (str(profile.id), profile.model_dump_json()),
            )
        adapter = BudgetedAdapter(ModelAdapter(deps.model_profiles), ledger)
        deps.answer_service.adapter = adapter
        deps.wiki_service.adapter = adapter
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        prefix = "/api/v1/knowledge"
        existing_bases = deps.knowledge_service.store.bases()
        base = (
            existing_bases[0]["id"]
            if existing_bases
            else client.post(
                prefix + "/bases", json={"name": "Task44 authorized real pilot"}
            ).json()["id"]
        )
        mapping = {}
        for source in sources:
            existing = next(
                (
                    d
                    for d in deps.knowledge_service.store.documents(base)
                    if d["source_sha256"] == source["sha256"] and d["status"] == "READY"
                ),
                None,
            )
            if existing is not None:
                mapping[source["source_document_id"]] = existing["id"]
                continue
            path = Path(source["source_path"])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise KnowledgeError("SOURCE_HASH_MISMATCH")
            response = client.post(
                prefix + f"/bases/{base}/documents",
                files={"files": (path.name, raw, "application/pdf")},
            )
            response.raise_for_status()
            doc_id = response.json()["items"][0]["document"]["id"]
            doc = wait(client, prefix + f"/documents/{doc_id}", {"QUEUED", "PARSING"}, seconds=900)
            if doc["status"] != "PARSED":
                raise KnowledgeError("PILOT_PARSE_FAILED")
            job = client.post(prefix + f"/documents/{doc_id}/index").json()
            indexed = wait(
                client, prefix + f"/index-jobs/{job['id']}", {"QUEUED", "INDEXING"}, seconds=900
            )
            if indexed["status"] != "READY":
                raise KnowledgeError("PILOT_INDEX_FAILED")
            mapping[source["source_document_id"]] = doc_id
            print(json.dumps({"stage": "indexed", "documents": len(mapping)}), flush=True)
        corpus = deps.wiki_service._sources(base)
        questions = []
        for note in notes:
            refs = []
            for reference in note.get("references", []):
                doc_id = mapping[reference["source_document_id"]]
                source = next(s for s in corpus if str(s.document_id) == doc_id)
                row = next(
                    r
                    for r in deps.retrieval_engine.catalog.active([base])
                    if r["document_id"] == doc_id
                )
                chunks = [
                    Chunk.model_validate(c) for c in deps.retrieval_engine._manifest(row)["chunks"]
                ]
                try:
                    candidates = reference_chunks(chunks, reference)
                except KnowledgeError:
                    write_report(
                        {
                            "question_id": note["id"],
                            "reference": reference,
                            "candidate_chunks": [
                                c.model_dump(mode="json")
                                for c in chunks
                                if c.locations[0].page == reference["page"]
                            ],
                        },
                        root / "reference-remap-error.json",
                    )
                    raise KnowledgeError("PILOT_REFERENCE_NOT_IN_CHUNK") from None
                for chunk in candidates:
                    ref = LocalEvidence(
                        base_id=source.base_id,
                        document_id=source.document_id,
                        parse_revision=source.parse_revision,
                        index_revision=source.index_revision,
                        chunk_id=chunk.id,
                        element_id=chunk.element_id,
                        page=chunk.locations[0].page,
                        content_sha256=chunk.content_sha256,
                    ).model_dump(mode="json")
                    if ref not in refs:
                        refs.append(ref)
            questions.append(
                {
                    **{
                        key: note[key]
                        for key in (
                            "id",
                            "category",
                            "question",
                            "answerable",
                            "reference_claims",
                            "rubric",
                        )
                    },
                    "split": "development",
                    "reference_evidence": refs,
                }
            )
        dataset = {
            "dataset_id": "task44-real-pilot",
            "kind": "pilot",
            "corpus": [s.model_dump(mode="json") for s in corpus],
            "questions": questions,
            "generation": {
                "input_tokens_per_question": None,
                "input_bytes_per_question": 32000,
                "output_tokens_per_question": 2000,
                "context_max_bytes": 24000,
            },
        }
        EvaluationDataset.model_validate(dataset)
        write_report(dataset, root / "dataset-before-wiki.json")
        summary = {
            "status": "PREPARED",
            "profile_id": str(profile.id),
            "model": profile.model,
            "corpus_documents": len(corpus),
            "questions": 10,
        }
        stop_reason = None
        if args.live:
            try:
                validate_snapshot(
                    profile.snapshot(),
                    EvaluationControls(
                        sources=corpus,
                        model_snapshot=profile.snapshot(),
                        max_input_tokens=None,
                        max_input_bytes=32000,
                        max_output_tokens=2000,
                        context_max_bytes=24000,
                    ),
                )
                if args.resume_after_fix:
                    ledger.resume_after_fix()
                model, snapshot = adapter.prepare(profile.id, profile.snapshot())
                model = bind_output_limit(model, snapshot, 128)
                run_probe(client, model)
            except Exception as error:
                stop_reason = error_code(error)
                ledger.stop(stop_reason)
                summary.update(status="PROBE_FAILED", error_code=stop_reason)
            if stop_reason is None:
                wiki = prefix + f"/bases/{base}/wiki"
                request = {
                    "model_profile_id": str(profile.id),
                    "input_max_bytes": 24000,
                    "output_token_limit": 2000,
                    "min_context_chars": 80,
                    **build_limits(ledger, len(corpus)),
                }
                pre = client.post(wiki + "/preflight", json=request)
                pre.raise_for_status()
                write_report(pre.json(), root / "wiki-preflight.json")
                built = client.post(
                    wiki + "/build",
                    json={**request, "preflight_sha256": pre.json()["preflight_sha256"]},
                )
                built.raise_for_status()
                job = wait(
                    client,
                    wiki + f"/jobs/{built.json()['id']}",
                    {"QUEUED", "BUILDING"},
                    seconds=1800,
                )
                write_report(job, root / "wiki-build.json")
                if job["status"] != "COMPLETED":
                    stop_reason = job["error_code"] or "WIKI_BUILD_FAILED"
                    ledger.stop(stop_reason)
                    summary.update(status="WIKI_BUILD_FAILED", error_code=stop_reason)
                else:
                    dataset.update(
                        wiki_build=[job],
                        wiki_snapshots=[
                            s.model_dump(mode="json")
                            for s in deps.answer_service.hybrid.snapshot([base])
                        ],
                    )
        write_report(dataset, root / "dataset.json")
        reports = []
        for mode in ("rag", "wiki", "hybrid"):
            live = args.live and stop_reason is None
            report = run_evaluation(
                dataset,
                live=live,
                mode=mode,
                model_profile_id=profile.id,
                budget=LiveBudget(max_calls=10, max_input_bytes=320000, max_output_tokens=20000)
                if live
                else None,
                api_url="http://localhost",
                client=client,
                checkpoint=root / mode / "results.json",
            )
            if stop_reason:
                for row in report["results"]:
                    row["reason"] = stop_reason
                report["quality_status"] = "REAL_COMPARISON_PENDING"
            write_report(report, root / mode / "results.json")
            reports.append(report)
            if ledger.data["stopped"]:
                stop_reason = "PREVIOUS_PROVIDER_FAILURE"
        if all(report["execution"] == "live" for report in reports):
            export_blind(EvaluationDataset.model_validate(dataset), reports, root / "blind")
            summary["status"] = "HUMAN_BLIND_REVIEW_PENDING"
        summary.update(
            calls=len(ledger.data["calls"]),
            input_bytes=sum(c["input_bytes"] for c in ledger.data["calls"]),
            counts={r["mode"]: r["counts"] for r in reports},
            token_and_money_upper_bound=None,
        )
        write_report(summary, root / "summary.json")
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--resume-after-fix",
        action="store_true",
        help="Requires new explicit human authorization; preserves original ledger/budget.",
    )
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--profile-db", type=Path, required=True)
    parser.add_argument("--profile-id", type=UUID, required=True)
    parser.add_argument("--output", type=Path, required=True)
    try:
        run(parser.parse_args())
    except Exception as error:
        # Never print raw traceback, source text, provider error bodies or secrets.
        print(
            json.dumps(
                {
                    "status": "STOPPED",
                    "exception_type": type(error).__name__,
                    "code": error.code if isinstance(error, KnowledgeError) else error_code(error),
                }
            )
        )
        raise SystemExit(2) from None
