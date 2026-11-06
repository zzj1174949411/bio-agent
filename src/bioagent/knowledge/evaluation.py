"""Versioned literature evaluation protocol, local API runner and human scoring.

Reference answers never enter generation requests. Synthetic runs prove plumbing only.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import Field, model_validator

from bioagent.knowledge.models import Record
from bioagent.knowledge.retrieval_models import (
    AskTask,
    EvaluationSource,
    LocalEvidence,
    ModelAnswer,
    WikiSnapshot,
)
from bioagent.knowledge.wiki_models import WikiJob

Category = Literal[
    "single_fact",
    "table_numeric",
    "cross_paper",
    "method_synthesis",
    "conditions_conflict",
    "unanswerable",
]
METRICS = (
    "correct",
    "claim_coverage",
    "numeric_units",
    "citation_support",
    "unsupported_claims",
    "correct_abstention",
)
CATEGORIES = (
    "single_fact",
    "table_numeric",
    "cross_paper",
    "method_synthesis",
    "conditions_conflict",
    "unanswerable",
)


class EvaluationQuestion(Record):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    split: Literal["development", "heldout"]
    category: Category
    question: str = Field(min_length=1, max_length=4096)
    answerable: bool
    reference_claims: tuple[str, ...]
    reference_evidence: tuple[LocalEvidence, ...]
    rubric: str = Field(min_length=1, max_length=4096)


class GenerationConfig(Record):
    temperature: Literal[0] = 0
    seed: Literal[42] = 42
    prompt_version: Literal["rag-answer.v1"] = "rag-answer.v1"
    context_max_bytes: int = Field(default=24000, ge=1, le=100000, strict=True)
    input_tokens_per_question: int | None = Field(default=32000, ge=1, le=200000, strict=True)
    input_bytes_per_question: int | None = Field(default=None, ge=1, le=32000, strict=True)
    output_tokens_per_question: int = Field(default=2000, ge=1, le=16000, strict=True)


class EvaluationDataset(Record):
    schema_version: Literal["literature-eval.v1"] = "literature-eval.v1"
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["synthetic_example", "pilot", "formal"]
    corpus: tuple[EvaluationSource, ...] = Field(min_length=1, max_length=100)
    generation: GenerationConfig
    questions: tuple[EvaluationQuestion, ...] = Field(min_length=1, max_length=1000)
    wiki_snapshots: tuple[WikiSnapshot, ...] = ()
    wiki_build: tuple[WikiJob, ...] | None = None

    @model_validator(mode="after")
    def consistent(self) -> EvaluationDataset:
        sources = {source.document_id: source for source in self.corpus}
        if len(sources) != len(self.corpus) or len({s.index_revision for s in self.corpus}) != len(
            self.corpus
        ):
            raise ValueError("DUPLICATE_SOURCE")
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("DUPLICATE_QUESTION_OR_SPLIT_LEAKAGE")
        if len({q.question.strip().casefold() for q in self.questions}) != len(self.questions):
            raise ValueError("DUPLICATE_QUESTION_TEXT")
        for q in self.questions:
            if q.answerable != bool(q.reference_claims and q.reference_evidence):
                raise ValueError("REFERENCE_REQUIRED_FOR_ANSWERABLE")
            if not q.answerable and (q.reference_claims or q.reference_evidence):
                raise ValueError("UNANSWERABLE_REFERENCE_CONFLICT")
            for ref in q.reference_evidence:
                source = sources.get(ref.document_id)
                if source is None or (ref.base_id, ref.parse_revision, ref.index_revision) != (
                    source.base_id,
                    source.parse_revision,
                    source.index_revision,
                ):
                    raise ValueError("REFERENCE_SNAPSHOT_MISMATCH")
        if self.kind == "formal" and (
            len(self.questions) != 60
            or Counter(q.category for q in self.questions) != dict.fromkeys(CATEGORIES, 10)
            or Counter(q.split for q in self.questions) != {"development": 15, "heldout": 45}
        ):
            raise ValueError("FORMAL_REQUIRES_60_SIX_CATEGORIES_15_45")
        if self.kind == "pilot" and (
            len(self.questions) != 10 or any(q.split != "development" for q in self.questions)
        ):
            raise ValueError("PILOT_REQUIRES_TEN_DEVELOPMENT_QUESTIONS")
        bases = {source.base_id for source in self.corpus}
        if self.wiki_snapshots and (
            {s.base_id for s in self.wiki_snapshots} != bases
            or len(self.wiki_snapshots) != len(bases)
        ):
            raise ValueError("WIKI_SCOPE_MISMATCH")
        for job in self.wiki_build or ():
            if job.status != "COMPLETED" or any(
                source not in self.corpus for source in job.sources
            ):
                raise ValueError("WIKI_BUILD_SNAPSHOT_MISMATCH")
            if not any(
                s.base_id == job.base_id and s.generation == job.generation
                for s in self.wiki_snapshots
            ):
                raise ValueError("WIKI_BUILD_GENERATION_MISMATCH")
        return self

    def generation_questions(self) -> list[dict[str, str]]:
        return [{"id": q.id, "question": q.question} for q in self.questions]

    def wiki_build_input(self) -> dict[str, Any]:
        # No questions or reference answers, including development, are build input.
        return {"corpus": [source.model_dump(mode="json") for source in self.corpus]}


class LiveBudget(Record):
    max_calls: int = Field(ge=1, strict=True)
    max_input_tokens: int | None = Field(default=None, ge=1, strict=True)
    max_input_bytes: int | None = Field(default=None, ge=1, strict=True)
    max_output_tokens: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def input_bound_required(self) -> LiveBudget:
        if self.max_input_tokens is None and self.max_input_bytes is None:
            raise ValueError("LIVE_INPUT_BUDGET_REQUIRED")
        return self


def protocol_hash(dataset: EvaluationDataset) -> str:
    return hashlib.sha256(dataset.model_dump_json().encode()).hexdigest()


def _json(response: httpx.Response) -> Any:
    response.raise_for_status()
    return response.json()


def _api_error(error: Exception) -> str:
    # This is the local API, not a model-provider response. Preserve only exact
    # public contract codes; never emit arbitrary response/body text.
    if isinstance(error, httpx.HTTPStatusError):
        try:
            code = error.response.json()["detail"]["code"]
        except (ValueError, KeyError, TypeError):
            return "EVALUATION_API_REJECTED"
        allowed = {
            "EVALUATION_LIMITS_UNSUPPORTED",
            "EVALUATION_MODEL_MISMATCH",
            "EVALUATION_SNAPSHOT_MISMATCH",
            "EVIDENCE_STALE",
            "BASE_NOT_FOUND",
            "DOCUMENT_NOT_FOUND",
            "MODEL_NOT_CONFIGURED",
            "CSRF_TOKEN_REQUIRED",
            "LOCAL_HOST_REJECTED",
            "LOCAL_ORIGIN_REJECTED",
            "REQUEST_INVALID",
            "SECRET_STORE_UNAVAILABLE",
            "ASK_QUEUE_FULL",
        }
        return code if isinstance(code, str) and code in allowed else "EVALUATION_API_REJECTED"
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "EVALUATION_API_TIMEOUT"
    if isinstance(error, httpx.HTTPError):
        return "EVALUATION_API_CONNECTION_FAILED"
    return "EVALUATION_API_RESPONSE_INVALID"


def run_evaluation(
    data: dict[str, Any],
    *,
    live: bool = False,
    mode: str = "rag",
    model_profile_id: UUID | None = None,
    budget: LiveBudget | None = None,
    api_url: str = "http://127.0.0.1:8000",
    client: httpx.Client | None = None,
    split: Literal["development", "heldout", "all"] = "development",
    poll_seconds: float = 0.2,
    timeout_seconds: float = 150,
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"rag", "wiki", "hybrid"}:
        raise ValueError("MODE_NOT_IMPLEMENTED")
    dataset = EvaluationDataset.model_validate(data)
    missing_wiki = (
        not dataset.wiki_snapshots or any(s.generation is None for s in dataset.wiki_snapshots)
    )
    if live and mode != "rag" and missing_wiki:
        raise ValueError("EVALUATION_WIKI_SNAPSHOT_REQUIRED")
    if live and (budget is None or model_profile_id is None):
        raise ValueError("LIVE_BUDGET_REQUIRED")
    parsed = urlsplit(api_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("LOCAL_API_REQUIRED")
    report: dict[str, Any] = {
        "schema_version": "literature-results.v1",
        "run_id": str(uuid4()),
        "dataset_id": dataset.dataset_id,
        "dataset_kind": dataset.kind,
        "protocol_sha256": protocol_hash(dataset),
        "mode": mode,
        "split": split,
        "execution": "live" if live else "dry-run",
        "quality_status": "HUMAN_REVIEW_PENDING" if live else "REAL_BASELINE_PENDING",
        "corpus": [s.model_dump(mode="json") for s in dataset.corpus],
        "wiki_snapshots": [s.model_dump(mode="json") for s in dataset.wiki_snapshots],
        "wiki_build": (
            [job.model_dump(mode="json") for job in dataset.wiki_build]
            if dataset.wiki_build is not None
            else None
        ),
        "generation": dataset.generation.model_dump(),
        "budget": budget.model_dump() if budget else None,
        "model_profile_id": str(model_profile_id) if model_profile_id else None,
        "model_snapshot": None,
        "provider_controls": None,
        "results": [],
        "reserved": {"calls": 0, "input_tokens": 0, "output_tokens": 0},
    }
    if dataset.generation.input_bytes_per_question is not None:
        report["reserved"]["input_bytes"] = 0
    if dataset.generation.input_tokens_per_question is None:
        report["reserved"]["input_tokens"] = None
    root = Path(__file__).parents[1]
    files = [
        Path(__file__),
        root / "knowledge/answers.py",
        root / "knowledge/retrieval.py",
        root / "knowledge/retrieval_models.py",
        root / "knowledge/snapshots.py",
        root / "models/adapters.py",
        root / "models/evaluation_limits.py",
        Path(__file__).parents[3] / "scripts/evaluate_literature.py",
        *sorted((root / "knowledge").glob("wiki*.py")),
        *sorted((root / "knowledge").glob("hybrid*.py")),
    ]
    report["implementation_sha256"] = hashlib.sha256(
        b"".join(path.name.encode() + b"\0" + path.read_bytes() for path in files)
    ).hexdigest()
    report["answer_schema_sha256"] = hashlib.sha256(
        json.dumps(ModelAnswer.model_json_schema(), sort_keys=True).encode()
    ).hexdigest()
    report["software_versions"] = {
        name: importlib.metadata.version(name)
        for name in ("bio-agent", "httpx", "pydantic", "langchain-openai")
    }
    questions = [q for q in dataset.questions if split == "all" or q.split == split]
    if not questions:
        raise ValueError("EVALUATION_SPLIT_EMPTY")
    report["question_ids"] = [q.id for q in questions]
    if not live:
        report["wiki_snapshot_status"] = "MISSING" if missing_wiki else "LOCKED"
        if mode != "rag" and missing_wiki:
            report["quality_status"] = "REAL_COMPARISON_PENDING"
        report["results"] = [
            {"question_id": q.id, "category": q.category, "status": "NOT_RUN", "reason": "DRY_RUN"}
            for q in questions
        ]
        report["counts"] = dict(Counter(row["status"] for row in report["results"]))
        return report
    assert budget is not None and model_profile_id is not None
    # Every checkpoint contains the full locked denominator, even if bootstrap,
    # a request or the process is interrupted. Never score a successful prefix.
    report["results"] = [
        {
            "question_id": q.id,
            "category": q.category,
            "status": "NOT_RUN",
            "reason": "RUN_INTERRUPTED",
        }
        for q in questions
    ]
    report["runner_finished"] = False
    if checkpoint is not None:
        write_report(report, checkpoint)
    owned = client is None
    client = client or httpx.Client(base_url=api_url, timeout=15, follow_redirects=False)
    try:
        token = _json(client.get("/api/v1/workbench/bootstrap"))["csrf_token"]
        headers = {"X-CSRF-Token": token, "Origin": api_url.rstrip("/")}
        # Profiles are public metadata; credentials remain behind the server API.
        cursor = None
        profile = None
        while True:
            page = _json(
                client.get(
                    "/api/v1/model-profiles",
                    params={"limit": 100, **({"cursor": cursor} if cursor else {})},
                )
            )
            profile = next((p for p in page["items"] if p["id"] == str(model_profile_id)), None)
            cursor = page.get("next_cursor")
            if profile is not None or not cursor:
                break
        if profile is None:
            raise ValueError("MODEL_PROFILE_NOT_FOUND")
        from bioagent.models.profiles import ModelSnapshot

        snapshot = ModelSnapshot.model_validate(
            {key: profile[key] for key in ModelSnapshot.model_fields}
        )
        report["model_snapshot"] = snapshot.model_dump(mode="json")
        report["provider_controls"] = {
            "input_bound": (
                "application_message_utf8_bytes"
                if snapshot.provider == "deepseek"
                else "message_utf8_bytes_plus_1024_token_upper_bound"
            ),
            "output_parameter": (
                "max_tokens" if snapshot.provider == "deepseek" else "max_completion_tokens"
            ),
            "thinking": "disabled" if snapshot.provider == "deepseek" else "not_applicable",
            "seed_sent": None if snapshot.provider == "deepseek" else 42,
            "sdk_max_retries": 0,
            "model_id_rewritten": False,
            "monetary_upper_bound": None,
        }
        config = dataset.generation
        if (budget.max_input_bytes is not None) != (config.input_bytes_per_question is not None):
            raise ValueError("LIVE_INPUT_BUDGET_MISMATCH")
        if (budget.max_input_tokens is not None) != (config.input_tokens_per_question is not None):
            raise ValueError("LIVE_INPUT_BUDGET_MISMATCH")
        stopped = False
        stop_reason = "BUDGET_STOP"
        for q, row in zip(questions, report["results"], strict=True):
            reserved = report["reserved"]
            config = dataset.generation
            if stopped or (
                reserved["calls"] + 1 > budget.max_calls
                or (
                    budget.max_input_tokens is not None
                    and config.input_tokens_per_question is not None
                    and reserved["input_tokens"] + config.input_tokens_per_question
                    > budget.max_input_tokens
                )
                or (
                    budget.max_input_bytes is not None
                    and config.input_bytes_per_question is not None
                    and reserved["input_bytes"] + config.input_bytes_per_question
                    > budget.max_input_bytes
                )
                or reserved["output_tokens"] + config.output_tokens_per_question
                > budget.max_output_tokens
            ):
                stopped = True
                row["reason"] = stop_reason
                continue
            reserved["calls"] += 1
            if config.input_tokens_per_question is not None:
                reserved["input_tokens"] += config.input_tokens_per_question
            if config.input_bytes_per_question is not None:
                reserved["input_bytes"] += config.input_bytes_per_question
            reserved["output_tokens"] += config.output_tokens_per_question
            start = time.monotonic()
            ask_id = None
            row.update(status="FAILED", reason="EVALUATION_INTERRUPTED_UNKNOWN", usage=None)
            if checkpoint is not None:
                write_report(report, checkpoint)
            try:
                request = {
                    "question": q.question,
                    "knowledge_base_ids": sorted({str(s.base_id) for s in dataset.corpus}),
                    "model_profile_id": str(model_profile_id),
                    "mode": mode,
                    "evaluation": {
                        "sources": report["corpus"],
                        "model_snapshot": report["model_snapshot"],
                        "max_input_tokens": config.input_tokens_per_question,
                        "max_input_bytes": config.input_bytes_per_question,
                        "max_output_tokens": config.output_tokens_per_question,
                        "context_max_bytes": config.context_max_bytes,
                        "temperature": config.temperature,
                        "seed": config.seed,
                        "prompt_version": config.prompt_version,
                        "wiki_snapshots": report["wiki_snapshots"],
                    },
                }
                task = AskTask.model_validate(
                    _json(client.post("/api/v1/knowledge/ask", json=request, headers=headers))
                )
                ask_id = task.id
                row["ask_id"] = str(ask_id)
                row["first_status_seconds"] = time.monotonic() - start
                if checkpoint is not None:
                    write_report(report, checkpoint)
                while task.status not in {"COMPLETED", "FAILED", "CANCELLED", "NO_EVIDENCE"}:
                    if time.monotonic() - start > timeout_seconds:
                        raise TimeoutError()
                    time.sleep(poll_seconds)
                    task = AskTask.model_validate(
                        _json(client.get(f"/api/v1/knowledge/asks/{ask_id}"))
                    )
                row.update(
                    status=task.status,
                    reason=task.error_code,
                    answer=task.answer,
                    citations=[ref.model_dump(mode="json") for ref in task.citations],
                    evidence=[hit.model_dump(mode="json") for hit in task.evidence],
                    usage=task.usage,
                    input_token_upper_bound=task.input_token_upper_bound,
                    input_bytes=task.input_bytes,
                    context_bytes=task.context_bytes,
                    diagnostic=task.diagnostic.model_dump() if task.diagnostic else None,
                    ask_id=str(ask_id),
                    requested_mode=task.requested_mode,
                    actual_mode=task.actual_mode,
                    fallback_reason=task.fallback_reason,
                    wiki_snapshot=[s.model_dump(mode="json") for s in task.wiki_snapshot],
                    audit=task.audit.model_dump(mode="json") if task.audit else None,
                )
                if task.actual_mode != mode or task.fallback_reason is not None:
                    row.update(status="FAILED", reason="EVALUATION_MODE_MISMATCH", answer=None)
                    stopped = True
                    stop_reason = "PREVIOUS_FAILURE"
                if task.error_code and (
                    task.error_code.startswith("EVALUATION_")
                    or task.error_code
                    in {
                        "MODEL_TIMEOUT",
                        "MODEL_CONNECTION_FAILED",
                        "MODEL_AUTH_FAILED",
                        "MODEL_PAYMENT_REQUIRED",
                        "MODEL_NOT_FOUND",
                        "MODEL_RATE_LIMITED",
                        "MODEL_PROTOCOL_UNSUPPORTED",
                        "MODEL_SERVER_ERROR",
                        "MODEL_HTTP_ERROR",
                    }
                ):
                    stopped = True
                    stop_reason = "PREVIOUS_FAILURE"
            except (httpx.HTTPError, TimeoutError, ValueError) as error:
                row.update(status="FAILED", reason=_api_error(error), usage=None)
                # An ambiguous transport failure may have accepted a task: stop, never retry.
                stopped = True
                stop_reason = "PREVIOUS_FAILURE"
                if ask_id is not None:
                    try:
                        client.post(
                            f"/api/v1/knowledge/asks/{ask_id}/cancel", headers=headers
                        ).raise_for_status()
                    except httpx.HTTPError:
                        row["cancellation"] = "UNKNOWN"
            row["elapsed_seconds"] = time.monotonic() - start
            if checkpoint is not None:
                write_report(report, checkpoint)
    finally:
        if owned:
            client.close()
    report["counts"] = dict(Counter(row["status"] for row in report["results"]))
    report["runner_finished"] = True
    report["actual_usage_complete"] = all(
        row.get("usage") is not None for row in report["results"] if row["status"] != "NOT_RUN"
    )
    if checkpoint is not None:
        write_report(report, checkpoint)
    return report


def write_report(report: dict[str, Any], path: Path) -> None:
    if report.get("schema_version") == "literature-results.v1":
        report["counts"] = dict(Counter(row["status"] for row in report["results"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def export_blind(dataset: EvaluationDataset, reports: list[dict[str, Any]], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    packet, key = [], []
    questions = {q.id: q for q in dataset.questions}
    for report in reports:
        if report["protocol_sha256"] != protocol_hash(dataset) or report["execution"] != "live":
            raise ValueError("BLIND_REQUIRES_MATCHING_LIVE_PROTOCOL")
        expected = {
            q.id
            for q in dataset.questions
            if report["split"] == "all" or q.split == report["split"]
        }
        actual = [row["question_id"] for row in report["results"]]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("BLIND_QUESTION_SET_MISMATCH")
        for row in report["results"]:
            q = questions[row["question_id"]]
            identity = str(uuid4())
            packet.append(
                {
                    "blind_id": identity,
                    "question": q.question,
                    "answer": row.get("answer"),
                    "status": row["status"],
                    "citations": row.get("citations", []),
                    # Retrieval scores and route metadata can identify the arm.
                    "evidence": [
                        {field: hit[field] for field in ("reference", "chunk") if field in hit}
                        for hit in row.get("evidence", [])
                    ],
                }
            )
            key.append(
                {
                    "blind_id": identity,
                    "run_id": report["run_id"],
                    "question_id": q.id,
                    "reference_claims": q.reference_claims,
                    "reference_evidence": [
                        ref.model_dump(mode="json") for ref in q.reference_evidence
                    ],
                    "rubric": q.rubric,
                }
            )
    random.SystemRandom().shuffle(packet)
    write_report({"items": packet}, output / "blind-packet.json")
    write_report(
        {
            "items": [
                {
                    field: row[field]
                    for field in ("blind_id", "reference_claims", "reference_evidence", "rubric")
                }
                for row in key
            ]
        },
        output / "reference-sheet.json",
    )
    write_report({"items": key}, output / "manager-key.json")
    with (output / "scores.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["blind_id", *METRICS, "notes"])
        writer.writeheader()
        writer.writerows({"blind_id": row["blind_id"]} for row in packet)


def read_scores(path: Path, key: dict[str, Any], run_id: str) -> dict[str, dict[str, float | None]]:
    mapping = {row["blind_id"]: row for row in key["items"]}
    scores = {}
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            identity = row["blind_id"]
            if identity not in mapping or identity in seen:
                raise ValueError("SCORE_ID_INVALID")
            seen.add(identity)
            values = {
                metric: float(row[metric]) if row[metric].strip() else None for metric in METRICS
            }
            if any(value is not None and not 0 <= value <= 1 for value in values.values()):
                raise ValueError("SCORE_OUT_OF_RANGE")
            if mapping[identity]["run_id"] == run_id:
                scores[mapping[identity]["question_id"]] = values
    return scores


def summarize(report: dict[str, Any], scores: dict[str, dict[str, float | None]]) -> dict[str, Any]:
    results = report["results"]
    if len(results) != len(report["question_ids"]) or {
        row["question_id"] for row in results
    } != set(report["question_ids"]):
        raise ValueError("SCORE_QUESTION_SET_MISMATCH")
    if not set(scores) <= {row["question_id"] for row in results}:
        raise ValueError("SCORE_QUESTION_MISMATCH")
    for row in results:
        row_scores = scores.get(row["question_id"], {})
        if row["status"] == "NOT_RUN" and any(v is not None for v in row_scores.values()):
            raise ValueError("UNRUN_CANNOT_BE_SCORED")
        if row["status"] in {"FAILED", "CANCELLED"} and row_scores.get("correct") not in {None, 0}:
            raise ValueError("FAILED_CANNOT_BE_CORRECT")
    summary: dict[str, Any] = {
        "total": len(results),
        "counts": dict(Counter(row["status"] for row in results)),
        "categories": {},
    }
    for category in sorted({row["category"] for row in results}):
        rows = [row for row in results if row["category"] == category]
        metrics = {}
        for metric in METRICS:
            values = [scores.get(row["question_id"], {}).get(metric) for row in rows]
            judged = [v for v in values if v is not None]
            metrics[metric] = {
                "scored": len(judged),
                "total": len(rows),
                "sum": sum(judged) if judged else None,
                "mean_scored": sum(judged) / len(judged) if judged else None,
                "mean_all": sum(judged) / len(rows) if len(judged) == len(rows) else None,
            }
        summary["categories"][category] = metrics
    summary["quality_status"] = (
        "HUMAN_REVIEW_PENDING"
        if any(scores.get(row["question_id"], {}).get("correct") is None for row in results)
        else "HUMAN_SCORED"
    )
    return summary


def paired_summary(
    left: dict[str, Any],
    right: dict[str, Any],
    left_scores: dict[str, Any],
    right_scores: dict[str, Any],
) -> dict[str, Any]:
    if left["execution"] != "live" or right["execution"] != "live":
        raise ValueError("PAIRED_REQUIRES_LIVE")
    summarize(left, left_scores)
    summarize(right, right_scores)
    for key in (
        "protocol_sha256",
        "model_snapshot",
        "generation",
        "split",
        "dataset_kind",
        "implementation_sha256",
        "software_versions",
        "wiki_snapshots",
        "wiki_build",
        "answer_schema_sha256",
        "provider_controls",
    ):
        if left[key] != right[key]:
            raise ValueError("PAIRED_PROTOCOL_MISMATCH")
    ids = {row["question_id"] for row in left["results"]}
    if ids != {row["question_id"] for row in right["results"]}:
        raise ValueError("PAIRED_QUESTION_MISMATCH")
    differences = []
    for identity in sorted(ids):
        a, b = (
            left_scores.get(identity, {}).get("correct"),
            right_scores.get(identity, {}).get("correct"),
        )
        if a is not None and b is not None:
            differences.append(b - a)
    interval = None
    if len(differences) >= 2:
        rng = random.Random(42)
        samples = sorted(
            sum(rng.choices(differences, k=len(differences))) / len(differences)
            for _ in range(2000)
        )
        interval = [samples[49], samples[1949]]
    result = {
        "total_pairs": len(ids),
        "scored_pairs": len(differences),
        "unscored_pairs": len(ids) - len(differences),
        "right_win": sum(v > 0 for v in differences),
        "tie": sum(v == 0 for v in differences),
        "right_loss": sum(v < 0 for v in differences),
        "mean_difference_scored": sum(differences) / len(differences) if differences else None,
        "mean_difference_all": (
            sum(differences) / len(ids) if len(differences) == len(ids) and ids else None
        ),
        "bootstrap_95_interval_scored": interval,
        "provisional": len(differences) != len(ids),
    }
    categories = {}
    for category in sorted({row["category"] for row in left["results"]}):
        group_ids = {row["question_id"] for row in left["results"] if row["category"] == category}
        values = [
            right_scores[key]["correct"] - left_scores[key]["correct"]
            for key in sorted(group_ids)
            if left_scores.get(key, {}).get("correct") is not None
            and right_scores.get(key, {}).get("correct") is not None
        ]
        categories[category] = {
            "total_pairs": len(group_ids),
            "scored_pairs": len(values),
            "right_win": sum(v > 0 for v in values),
            "tie": sum(v == 0 for v in values),
            "right_loss": sum(v < 0 for v in values),
            "mean_difference_scored": sum(values) / len(values) if values else None,
        }
    result["categories"] = categories
    return result
