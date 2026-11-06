import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def test_local_interval_scoring_cannot_count_unsent_neighbor_or_fuzzy_letters():
    path = Path("scripts/compare_literature_retrieval.py")
    spec = importlib.util.spec_from_file_location("local_comparison", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = "x" * 110 + "13.5 h per cell type"
    element = {"id": "neighbor", "text": text, "locations": [{"page": 2}]}
    sources = [{"source_document_id": "original", "sha256": "locked"}]
    docs = [{"id": "doc", "source_sha256": "locked"}]
    note = {
        "references": [
            {
                "source_document_id": "original",
                "element_id": "neighbor",
                "page": 2,
                "quote": "13.5 h per cell type",
            }
        ]
    }
    chunk = SimpleNamespace(
        sources=(),
        element_id="anchor",
        context_element_ids=("neighbor",),
        text="unrelated",
        context=text,
    )
    hit = SimpleNamespace(chunk=chunk, reference=SimpleNamespace(document_id="doc"))
    result = SimpleNamespace(page=SimpleNamespace(items=(hit,)))
    details = module.coverage(note, result, docs, {"doc": {"elements": [element]}}, sources)
    assert details[0]["mapped"] and not details[0]["covered"]
    original = {
        "text": "a measured fact.",
        "captions": [],
        "ocr_text": "",
        "footnotes": [],
        "kind": "text",
    }
    altered = SimpleNamespace(text="a measured inserted fact.", part=0)
    assert module.legacy_intervals(altered, original) == []


def example():
    return json.loads(Path("evals/literature/example.json").read_text(encoding="utf-8"))


def test_contract_rejects_duplicate_split_and_stale_evidence():
    from bioagent.knowledge.evaluation import EvaluationDataset

    data = example()
    valid = EvaluationDataset.model_validate(data)
    assert "reference_claims" not in json.dumps(valid.generation_questions())
    duplicate = copy.deepcopy(data)
    duplicate["questions"].append({**duplicate["questions"][0], "split": "heldout"})
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(duplicate)
    stale = copy.deepcopy(data)
    stale["questions"][0]["reference_evidence"][0]["parse_revision"] = (
        "00000000-0000-0000-0000-000000000099"
    )
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(stale)


def test_live_requires_positive_budgets_and_hybrid_requires_frozen_wiki():
    from bioagent.knowledge.evaluation import LiveBudget, run_evaluation

    with pytest.raises(ValidationError):
        LiveBudget(max_calls=0, max_input_tokens=100, max_output_tokens=100)
    with pytest.raises(ValueError, match="LIVE_BUDGET_REQUIRED"):
        run_evaluation(example(), live=True)
    with pytest.raises(ValueError, match="EVALUATION_WIKI_SNAPSHOT_REQUIRED"):
        run_evaluation(example(), mode="hybrid", live=True)


def test_missing_wiki_dry_run_keeps_full_denominator_without_api():
    from bioagent.knowledge.evaluation import run_evaluation

    report = run_evaluation(example(), mode="wiki", split="all")
    assert report["counts"] == {"NOT_RUN": 2}
    assert report["wiki_snapshot_status"] == "MISSING"
    assert report["quality_status"] == "REAL_COMPARISON_PENDING"


def test_dry_run_never_touches_api_and_wiki_input_has_no_questions():
    import httpx

    from bioagent.knowledge.evaluation import EvaluationDataset, run_evaluation

    def forbidden(_):
        pytest.fail("dry-run accessed API")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        report = run_evaluation(example(), client=client, split="all")
    assert report["counts"] == {"NOT_RUN": 2}
    assert report["quality_status"] == "REAL_BASELINE_PENDING"
    assert report["implementation_sha256"]
    assert "question" not in json.dumps(
        EvaluationDataset.model_validate(example()).wiki_build_input()
    )


@pytest.mark.parametrize("failure", ["terminal", "transport", "api_rejected", "interrupted"])
def test_mock_api_success_failure_budget_stop_and_no_reference_leak(failure, tmp_path):
    from uuid import uuid4

    import httpx

    from bioagent.knowledge.evaluation import LiveBudget, run_evaluation
    from bioagent.models.profiles import ModelSnapshot

    data = example()
    # Two real attempts and one unrun, sharing the same locked protocol.
    second = {**copy.deepcopy(data["questions"][0]), "id": "second", "question": "第二个合成问题"}
    data["questions"].insert(1, second)
    profile_id = uuid4()
    snapshot = ModelSnapshot(
        provider="openai_compatible",
        model="gpt-4o-2024-08-06",
        base_url="https://api.openai.com/v1",
        revision=1,
        thinking="default",
        structured_method="function_calling",
    ).model_dump(mode="json")
    posts = []

    def api(request):
        if request.url.path.endswith("bootstrap"):
            return httpx.Response(200, json={"csrf_token": "synthetic-token"})
        if request.url.path.endswith("model-profiles"):
            return httpx.Response(
                200, json={"items": [{"id": str(profile_id), **snapshot}], "next_cursor": None}
            )
        assert request.url.path == "/api/v1/knowledge/ask"
        assert request.headers["X-CSRF-Token"] == "synthetic-token"
        body = json.loads(request.content)
        assert "reference_claims" not in str(body) and "reference_evidence" not in str(body)
        assert "12.5" not in str(body)
        posts.append(body)
        if len(posts) == 2 and failure == "transport":
            raise httpx.ReadTimeout("synthetic-private-body C:/secret")
        if len(posts) == 2 and failure == "interrupted":
            raise KeyboardInterrupt()
        if len(posts) == 2 and failure == "api_rejected":
            return httpx.Response(
                422,
                json={
                    "detail": {
                        "code": "EVALUATION_LIMITS_UNSUPPORTED",
                        "private": "synthetic-private-body",
                    }
                },
            )
        task = dict(
            id=str(uuid4()),
            status="COMPLETED" if len(posts) == 1 else "FAILED",
            model_profile_id=str(profile_id),
            snapshot=snapshot,
            created_at="fixture",
            updated_at="fixture",
            status_url="/ignored",
            events_url="/ignored",
            evaluation=body["evaluation"],
            answer="Synthetic answer" if len(posts) == 1 else None,
            error_code=None if len(posts) == 1 else "MODEL_TIMEOUT",
            usage=None,
        )
        return httpx.Response(202, json=task)

    with httpx.Client(
        base_url="http://localhost:8000", transport=httpx.MockTransport(api)
    ) as client:

        def run():
            return run_evaluation(
                data,
                live=True,
                client=client,
                model_profile_id=profile_id,
                split="all",
                budget=LiveBudget(max_calls=2, max_input_tokens=64000, max_output_tokens=4000),
                checkpoint=tmp_path / "results.json",
            )

        if failure == "interrupted":
            with pytest.raises(KeyboardInterrupt):
                run()
            report = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
        else:
            report = run()
    assert len(posts) == 2
    assert report["counts"] == {"COMPLETED": 1, "FAILED": 1, "NOT_RUN": 1}
    assert report["reserved"] == {"calls": 2, "input_tokens": 64000, "output_tokens": 4000}
    assert report.get("actual_usage_complete", False) is False
    assert "private-body" not in json.dumps(report)
    if failure == "api_rejected":
        assert report["results"][1]["reason"] == "EVALUATION_LIMITS_UNSUPPORTED"
    # A stop must still write all rows, including the unrun denominator.
    assert len(json.loads((tmp_path / "results.json").read_text())["results"]) == 3


def test_blind_blank_scores_and_pairs_cannot_be_reported_as_zero(tmp_path):
    from bioagent.knowledge.evaluation import (
        EvaluationDataset,
        export_blind,
        paired_summary,
        read_scores,
        run_evaluation,
        summarize,
    )

    data = EvaluationDataset.model_validate(example())
    report = run_evaluation(example(), split="all")
    with pytest.raises(ValueError, match="LIVE"):
        export_blind(data, [report], tmp_path)
    # Synthetic wrapper tests export/scoring mechanics, never a real quality result.
    report["execution"] = "live"
    report["results"][0].update(status="COMPLETED", answer="Synthetic")
    export_blind(data, [report], tmp_path)
    packet = (tmp_path / "blind-packet.json").read_text(encoding="utf-8")
    assert "rag" not in packet and "reference_claims" not in packet
    scores = read_scores(
        tmp_path / "scores.csv",
        json.loads((tmp_path / "manager-key.json").read_text(encoding="utf-8")),
        report["run_id"],
    )
    result = summarize(report, scores)
    assert result["total"] == 2 and result["quality_status"] == "HUMAN_REVIEW_PENDING"
    assert result["categories"]["table_numeric"]["correct"]["mean_scored"] is None
    pair = paired_summary(report, report, scores, scores)
    assert pair["scored_pairs"] == 0 and pair["mean_difference_scored"] is None
    changed = {**report, "generation": {"context_max_bytes": 1}}
    with pytest.raises(ValueError, match="PROTOCOL"):
        paired_summary(report, changed, scores, scores)
    filled = {row["question_id"]: {"correct": 1.0} for row in report["results"]}
    with pytest.raises(ValueError, match="UNRUN"):
        summarize(report, filled)
    assert (tmp_path / "reference-sheet.json").exists()
    truncated = {**report, "results": report["results"][:1]}
    with pytest.raises(ValueError, match="QUESTION_SET"):
        export_blind(data, [truncated], tmp_path / "partial")


@pytest.mark.parametrize("mode", ["rag", "wiki", "hybrid"])
def test_three_modes_lock_wiki_and_keep_full_dry_run_denominator(mode):
    from bioagent.knowledge.evaluation import run_evaluation

    data = example()
    data["wiki_snapshots"] = [
        {
            "base_id": data["corpus"][0]["base_id"],
            "generation": "00000000-0000-0000-0000-000000000077",
            "page_ids": [],
        }
    ]
    report = run_evaluation(data, mode=mode, split="all")
    assert report["counts"] == {"NOT_RUN": 2}
    assert report["mode"] == mode
    assert report["wiki_snapshots"] == data["wiki_snapshots"]
    assert report["wiki_build"] is None


def test_pilot_is_ten_development_questions_and_never_formal():
    from bioagent.knowledge.evaluation import EvaluationDataset

    data = example()
    data["kind"] = "pilot"
    data["questions"] = [
        {
            **copy.deepcopy(data["questions"][0]),
            "id": f"pilot_{i}",
            "question": f"Pilot question {i}",
            "split": "development",
        }
        for i in range(10)
    ]
    assert EvaluationDataset.model_validate(data).kind == "pilot"
    data["questions"][0]["split"] = "heldout"
    with pytest.raises(ValidationError, match="PILOT"):
        EvaluationDataset.model_validate(data)


def test_deepseek_bound_wire_payload_uses_official_output_parameter():
    from uuid import uuid4

    import httpx
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from bioagent.knowledge.retrieval_models import EvaluationControls
    from bioagent.models.evaluation_limits import bind_evaluation, validate_snapshot
    from bioagent.models.profiles import ModelSnapshot

    snapshot = ModelSnapshot(
        provider="deepseek",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        revision=1,
        thinking="disabled",
        structured_method="function_calling",
    )
    controls = EvaluationControls(
        sources=example()["corpus"],
        model_snapshot=snapshot,
        max_input_tokens=None,
        max_input_bytes=32000,
        max_output_tokens=2000,
        context_max_bytes=24000,
    )
    captured = []

    def transport(request):
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": str(uuid4()),
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ],
                "model": snapshot.model,
                "created": 0,
                "object": "chat.completion",
            },
        )

    model = ChatOpenAI(
        model=snapshot.model,
        api_key="synthetic-test-key",
        base_url=snapshot.base_url,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    )
    validate_snapshot(snapshot, controls)
    bound, size, upper = bind_evaluation(
        model, snapshot, controls, [SystemMessage("system"), HumanMessage("question")]
    )
    assert size == len(b"systemquestion") and upper is None
    bound.invoke([SystemMessage("system"), HumanMessage("question")])
    assert captured[0]["max_tokens"] == 2000
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert "max_completion_tokens" not in captured[0]
    assert "seed" not in captured[0]
    from bioagent.models.evaluation_limits import bind_output_limit

    bind_output_limit(model, snapshot, 2000, json_mode=True).invoke([HumanMessage("Return JSON")])
    assert captured[-1]["response_format"] == {"type": "json_object"}
    assert captured[-1]["max_tokens"] == 2000
    with pytest.raises(ValueError, match="INPUT_LIMIT"):
        bind_evaluation(model, snapshot, controls, [HumanMessage("a" * 32001)])
    with pytest.raises(ValueError, match="LIMITS_UNSUPPORTED"):
        validate_snapshot(snapshot.model_copy(update={"model": "unknown"}), controls)


@pytest.mark.parametrize("mode", ["wiki", "hybrid"])
def test_live_mode_is_transmitted_and_fallback_rejected(mode):
    from uuid import uuid4

    import httpx

    from bioagent.knowledge.evaluation import LiveBudget, run_evaluation

    data = example()
    data["wiki_snapshots"] = [
        {"base_id": data["corpus"][0]["base_id"], "generation": str(uuid4()), "page_ids": []}
    ]
    profile_id = uuid4()
    snapshot = dict(
        provider="openai_compatible",
        model="gpt-4o-2024-08-06",
        base_url="https://api.openai.com/v1",
        revision=1,
        thinking="default",
        structured_method="function_calling",
    )
    calls = []

    def api(request):
        if request.url.path.endswith("bootstrap"):
            return httpx.Response(200, json={"csrf_token": "synthetic"})
        if request.url.path.endswith("model-profiles"):
            return httpx.Response(200, json={"items": [{"id": str(profile_id), **snapshot}]})
        body = json.loads(request.content)
        assert body["mode"] == mode
        assert body["evaluation"]["wiki_snapshots"] == data["wiki_snapshots"]
        assert "reference_claims" not in json.dumps(body)
        calls.append(body)
        return httpx.Response(
            202,
            json=dict(
                id=str(uuid4()),
                status="COMPLETED",
                model_profile_id=str(profile_id),
                snapshot=snapshot,
                created_at="fixture",
                updated_at="fixture",
                status_url="ignored",
                events_url="ignored",
                requested_mode=mode,
                actual_mode="rag",
                fallback_reason="WIKI_UNAVAILABLE",
                answer="Fallback answer",
            ),
        )

    with httpx.Client(
        base_url="http://localhost:8000", transport=httpx.MockTransport(api)
    ) as client:
        report = run_evaluation(
            data,
            mode=mode,
            live=True,
            client=client,
            model_profile_id=profile_id,
            split="all",
            budget=LiveBudget(max_calls=2, max_input_tokens=64000, max_output_tokens=4000),
        )
    assert len(calls) == 1
    assert report["counts"] == {"FAILED": 1, "NOT_RUN": 1}
    assert report["results"][0]["reason"] == "EVALUATION_MODE_MISMATCH"
    assert report["results"][0]["answer"] is None


def test_blind_discards_retrieval_route_scores_and_pair_locks_generation(tmp_path):
    from bioagent.knowledge.evaluation import (
        EvaluationDataset,
        export_blind,
        paired_summary,
        run_evaluation,
    )

    data = example()
    report = run_evaluation(data, split="all")
    report["execution"] = "live"
    report["results"][0]["evidence"] = [
        {"reference": {}, "chunk": {}, "score": 99, "keyword_score": 2, "actual_mode": "hybrid"}
    ]
    export_blind(EvaluationDataset.model_validate(data), [report], tmp_path)
    packet = json.loads((tmp_path / "blind-packet.json").read_text(encoding="utf-8"))
    evidence = next(row["evidence"] for row in packet["items"] if row["evidence"])
    assert evidence == [{"reference": {}, "chunk": {}}]
    changed = {**report, "wiki_snapshots": [{"generation": "different"}]}
    with pytest.raises(ValueError, match="PROTOCOL"):
        paired_summary(report, changed, {}, {})
