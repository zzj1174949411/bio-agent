"""Manual, explicitly enabled DeepSeek + public PD counts + real R acceptance.

No provider response or statistical result is mocked. Downloaded data, credentials,
and generated outputs are never committed. The old literature evaluation ledger
is neither read nor modified. Run with --help before enabling --live.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import numpy as np
import pandas as pd
from langchain_core.callbacks import BaseCallbackHandler

ROOT = Path(__file__).resolve().parents[1]
ACCESSION = "GSE205450"
COUNTS_FILE = "ncbi-counts-https.tsv.gz"
COUNTS_SHA = "660da48fe5d30f6d0440c7b4884fa5924f16b67fd7510d58f3d30b7609bdf55b"
SOFT_SHA = "450c7efd31970cd387c81df2a82bc01fc7dfec6e49cb7eabf63dc72aa9aeacab"
COUNTS_URL = (
    "https://www.ncbi.nlm.nih.gov/geo/download/?type=rnaseq_counts&acc=GSE205450"
    "&format=file&file=GSE205450_raw_counts_GRCh38.p13_NCBI.tsv.gz"
)
SOFT_URL = (
    "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE205nnn/GSE205450/soft/GSE205450_family.soft.gz"
)
LIMITATIONS = (
    "Exploratory, unadjusted PD versus Control in caudate only; age, sex, RIN, "
    "post-mortem interval, treatment and cell composition are not adjusted. "
    "NCBI-generated counts cover 119/150 deposited samples; availability can introduce "
    "selection bias. No causal, diagnostic, biomarker validation or enrichment claims. "
    "NCBI HISAT2/featureCounts quantification differs from the author's Salmon/limma analysis."
)


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def require_live(enabled: bool) -> None:
    if not enabled:
        raise ValueError("EXPLICIT_LIVE_REQUIRED")


def resolve_saved_profile(path: Path, identity: str, secrets=None):
    """Read the explicitly selected saved profile; never fall back to an env key."""
    from bioagent.models.profiles import ModelProfile
    from bioagent.models.secrets import SystemSecretStore

    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT record FROM model_profiles WHERE deleted=0").fetchall()
    profiles = [ModelProfile.model_validate_json(row[0]) for row in rows]
    found = [p for p in profiles if str(p.id) == identity and p.provider == "deepseek"]
    if len(found) != 1 or not found[0].credential_ref:
        raise ValueError("SAVED_DEEPSEEK_PROFILE_REQUIRED")
    credential = (secrets or SystemSecretStore()).get(found[0].credential_ref)
    if credential is None:
        raise ValueError("SAVED_PROFILE_CREDENTIAL_UNAVAILABLE")
    return found[0], credential


def traits(sample: dict) -> dict[str, str]:
    result = {}
    for field in sample["characteristics"]:
        text = field["value"]
        if "): " in text:
            name, value = text.split("): ", 1)
            name += ")"
        else:
            name, value = text.split(": ", 1)
        if name in result and result[name] != value:
            raise ValueError("CONFLICTING_SAMPLE_TRAITS")
        result[name] = value
    return result


def select_samples(source: dict, columns: list[str]) -> tuple[list[dict], list[str]]:
    chosen, excluded, donors = [], [], set()
    for sample in source["samples"]:
        values = traits(sample)
        gsm = sample["accession"]
        if values["region"] != "CAU":
            excluded.append(gsm)
            continue
        if sample["organism"] != "Homo sapiens" or sample["platform"] != "GPL24676":
            raise ValueError("SAMPLE_DESIGN_MISMATCH")
        if gsm not in columns:
            raise ValueError("SAMPLE_COLUMN_MISSING: " + gsm)
        donor = values["patient"]
        if donor in donors:
            raise ValueError("DUPLICATE_DONOR")
        donors.add(donor)
        if values["disease"] not in {"PD", "Control"}:
            raise ValueError("UNSUPPORTED_DISEASE_GROUP")
        chosen.append({"gsm": gsm, "donor": donor, "group": values["disease"], **values})
    counts = Counter(row["group"] for row in chosen)
    if set(counts) != {"PD", "Control"} or min(counts.values()) < 3:
        raise ValueError("INSUFFICIENT_INDEPENDENT_DONORS")
    return chosen, sorted(excluded)


def validate_counts(frame: pd.DataFrame, data_type: str) -> None:
    if data_type != "RAW_COUNTS":
        raise ValueError("RAW_SOURCE_REQUIRED")
    values = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
        raise ValueError("INVALID_RAW_COUNTS")


class CallBudget:
    """Local request audit; records counts/bytes, never headers or message content."""

    def __init__(self, path: Path, maximum_calls=12):
        self.path, self.maximum_calls = path, maximum_calls
        self.calls: list[dict] = []
        self.phase = "initialization"
        self.lock = Lock()
        self.shared_path: Path | None = None

    def reserve(self, payload: dict) -> None:
        size = len(json.dumps(payload.get("messages", []), ensure_ascii=False).encode())
        with self.lock:
            if len(self.calls) >= self.maximum_calls:
                raise ValueError("LIVE_CALL_LIMIT")
            if sum(call["input_bytes"] for call in self.calls) + size > 300_000:
                raise ValueError("LIVE_INPUT_BYTE_LIMIT")
            self.calls.append(
                {
                    "sequence": len(self.calls) + 1,
                    "phase": self.phase,
                    "input_bytes": size,
                    "requested_model": payload.get("model"),
                    "max_tokens": payload.get("max_tokens"),
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            save(self.path, {"calls": self.calls, "maximum_calls": self.maximum_calls})
            if self.shared_path is not None:
                save(self.shared_path, {"calls": self.calls, "maximum_calls": self.maximum_calls})

    def request(self, request: httpx.Request) -> None:
        if request.url.host != "api.deepseek.com" or not request.url.path.endswith(
            "/chat/completions"
        ):
            raise ValueError("UNEXPECTED_PROVIDER_ENDPOINT")
        payload = json.loads(request.content)
        if payload.get("max_tokens") != 1800:
            raise ValueError("OUTPUT_LIMIT_MISSING")
        self.reserve(payload)

    async def async_request(self, request: httpx.Request) -> None:
        self.request(request)

    def response(self, response: httpx.Response) -> None:
        with self.lock:
            self.calls[-1]["http_status"] = response.status_code
            save(self.path, {"calls": self.calls, "maximum_calls": self.maximum_calls})
            if self.shared_path is not None:
                save(self.shared_path, {"calls": self.calls, "maximum_calls": self.maximum_calls})

    async def async_response(self, response: httpx.Response) -> None:
        self.response(response)


class UsageAudit(BaseCallbackHandler):
    def __init__(self, path: Path):
        self.path, self.usage = path, []

    def on_llm_end(self, response, **kwargs):
        usage = (response.llm_output or {}).get("token_usage", {})
        # Only public accounting metadata, never model reasoning or prompts.
        self.usage.append({"usage": usage, "at": datetime.now(UTC).isoformat()})
        save(self.path, self.usage)


def checked(response, status=200):
    if response.status_code != status:
        # The local API returns stable errors; no provider headers are included.
        raise ValueError(f"LOCAL_API_FAILED: {response.status_code} {response.text[:1000]}")
    return response.json()


def wait_turn(client, identity, seconds=150):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        value = checked(client.get(f"/api/v1/workbench/turns/{identity}"))
        if value["status"] not in {"QUEUED", "RUNNING"}:
            return value
        sleep(0.25)
    raise TimeoutError("LIVE_TURN_TIMEOUT")


def load_public(cache: Path, output: Path):
    from bioagent.geo.client import _build_source

    counts_path, soft_path = cache / COUNTS_FILE, cache / "GSE205450_family.soft.gz"
    for path, digest in [(counts_path, COUNTS_SHA), (soft_path, SOFT_SHA)]:
        if sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("SOURCE_HASH_MISMATCH")
    soft = gzip.decompress(soft_path.read_bytes()).decode("utf-8")
    # FTP family SOFT has a DATABASE preamble; preserve raw bytes and record adapter.
    source = _build_source(ACCESSION, soft[soft.index("^SERIES") :], ()).model_dump(mode="json")
    frame = pd.read_csv(counts_path, sep="\t", dtype=str)
    if (
        frame.columns[0] != "GeneID"
        or frame["GeneID"].isna().any()
        or frame["GeneID"].duplicated().any()
    ):
        raise ValueError("GENE_ID_CONTRACT_FAILED")
    validate_counts(frame.iloc[:, 1:], "RAW_COUNTS")
    all_gsms = {sample["accession"] for sample in source["samples"]}
    if set(frame.columns[1:]) - all_gsms:
        raise ValueError("UNKNOWN_MATRIX_SAMPLES")
    unavailable = sorted(all_gsms - set(frame.columns[1:]))
    # Explicitly audit unavailable samples before selection; never silently drop them.
    covered_source = {
        **source,
        "samples": [s for s in source["samples"] if s["accession"] not in unavailable],
    }
    chosen, other_region = select_samples(covered_source, list(frame.columns))
    raw = frame[["GeneID", *[row["gsm"] for row in chosen]]].to_csv(sep="\t", index=False).encode()
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("DEFAULT_UPLOAD_LIMIT_EXCEEDED")
    audit = {
        "accession": ACCESSION,
        "counts_url": COUNTS_URL,
        "counts_sha256": COUNTS_SHA,
        "soft_url": SOFT_URL,
        "soft_sha256": SOFT_SHA,
        "quantification": "NCBI HISAT2/featureCounts",
        "soft_adapter": "Skip DATABASE preamble before SERIES; no biological values changed",
        "deposited_samples": len(all_gsms),
        "matrix_samples": len(frame.columns) - 1,
        "unavailable_samples": unavailable,
        "excluded_other_region": other_region,
        "selected_samples": chosen,
        "group_counts": dict(Counter(x["group"] for x in chosen)),
        "input_genes": len(frame),
        "selected_matrix_sha256": sha256(raw).hexdigest(),
        "all_zero_selected_genes": int(
            (frame[[x["gsm"] for x in chosen]].astype("int64").sum(axis=1) == 0).sum()
        ),
        "limitations": LIMITATIONS,
    }
    save(output / "source-audit.json", audit)
    (output / "matrix-upload.tsv").write_bytes(raw)
    pd.DataFrame(chosen).to_csv(output / "samples.csv", index=False)
    return raw, chosen, audit


def main():
    # Windows spawn re-imports __main__. Keep the application/model stack out of
    # parser children so the existing 512 MiB worker budget measures parsing.
    from fastapi.testclient import TestClient
    from langchain_openai import ChatOpenAI

    from bioagent.api.app import create_app
    from bioagent.config import Settings
    from bioagent.execution.r_runner import RRunner

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="enable the user-authorized real DeepSeek calls"
    )
    parser.add_argument("--cache", type=Path, default=ROOT / "data/task50/research")
    parser.add_argument("--profile-id", required=True, help="existing saved DeepSeek profile UUID")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_live(args.live)
    output = args.output.resolve()
    if output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    raw, chosen, audit = load_public(args.cache, output)
    settings = Settings()
    saved_profile, credential = resolve_saved_profile(settings.workbench_db, args.profile_id)
    endpoint = urlsplit(saved_profile.base_url)
    if endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com":
        raise ValueError("EXPECTED_CONFIGURED_DEEPSEEK_ENDPOINT")
    settings = settings.model_copy(
        update={
            "data_dir": output / "data",
            "runs_dir": output / "runs",
            "workbench_db": output / "workbench.sqlite",
            "checkpoint_db": output / "checkpoints.sqlite",
            "knowledge_dir": output / "knowledge",
            "deepseek_api_key": credential,
            "deepseek_model": saved_profile.model,
            "deepseek_base_url": saved_profile.base_url,
        }
    )
    libraries = sorted((ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if libraries:
        os.environ["R_LIBS"] = str(libraries[0].parent)
        os.environ["RENV_CONFIG_AUTOLOADER_ENABLED"] = "FALSE"
    budget, usage = CallBudget(output / "model-calls.json"), UsageAudit(output / "usage.json")
    budget.shared_path = ROOT / "data/task50/live-request-ledger.json"
    if budget.shared_path.exists():
        budget.calls = json.loads(budget.shared_path.read_text(encoding="utf-8"))["calls"]
    previous_call_count = len(budget.calls)
    sync = httpx.Client(
        event_hooks={"request": [budget.request], "response": [budget.response]}, timeout=60
    )
    asynchronous = httpx.AsyncClient(
        event_hooks={"request": [budget.async_request], "response": [budget.async_response]},
        timeout=60,
    )
    import bioagent.llm.factory as factory
    import bioagent.models.adapters as adapters

    original_factory, original_adapter = factory.ChatOpenAI, adapters.ChatOpenAI

    def bounded_model(**kwargs):
        # Genuine configured provider; only transport audit and bounded generation change.
        kwargs.update(
            http_client=sync,
            http_async_client=asynchronous,
            max_retries=0,
            temperature=0,
            callbacks=[usage],
            extra_body={**kwargs.get("extra_body", {}), "max_tokens": 1800},
        )
        return ChatOpenAI(**kwargs)

    factory.ChatOpenAI = bounded_model
    adapters.ChatOpenAI = bounded_model
    real_r, r_calls = RRunner.run, []

    def tracked_r(self, *a, **kw):
        r_calls.append({"at": datetime.now(UTC).isoformat()})
        save(output / "r-calls.json", r_calls)
        return real_r(self, *a, **kw)

    RRunner.run = tracked_r
    try:
        app = create_app(settings)
        with TestClient(app, base_url="http://localhost") as client:
            # Clone only non-secret configuration/reference into the isolated database.
            # The credential remains in the existing OS keyring under the original ref.
            with sqlite3.connect(output / "workbench.sqlite") as profile_db:
                profile_db.execute(
                    "INSERT INTO model_profiles(id,record,deleted) VALUES (?,?,0)",
                    (str(saved_profile.id), saved_profile.model_dump_json()),
                )
            save(
                output / "selected-model.json",
                saved_profile.public_dict(credential_configured=True),
            )
            client.headers["X-CSRF-Token"] = checked(client.get("/api/v1/workbench/bootstrap"))[
                "csrf_token"
            ]
            project = checked(
                client.post("/api/v1/workbench/projects", json={"title": "帕金森真实DeepSeek验收"}),
                201,
            )
            chat = checked(
                client.post(
                    "/api/v1/workbench/conversations",
                    json={"project_id": project["id"], "title": "GSE205450 尾状核 PD vs Control"},
                ),
                201,
            )["id"]
            profile = str(saved_profile.id)
            base = f"/api/v1/workbench/conversations/{chat}"
            budget.phase = "real_chat_study_design"
            first = checked(
                client.post(
                    base + "/turns",
                    json={
                        "client_request_id": str(uuid4()),
                        "profile_id": profile,
                        "text": (
                            "我们准备分析GSE205450。当前已有经官方来源核验的"
                            "NCBI raw counts与样本信息，"
                            "只纳入尾状核，31例PD、32例Control，每人一份。"
                            "先用中文简要说明这项探索性双组研究需要核对什么，"
                            "以及未调整年龄、性别、RIN的局限。此轮仅讨论研究设计，"
                            "不要发起搜索或规划，不声称已经有结果。"
                        ),
                    },
                ),
                202,
            )
            first = wait_turn(client, first["id"])
            save(output / "initial-turn.json", first)
            if first["status"] != "COMPLETED":
                raise ValueError("REAL_CHAT_NOT_COMPLETED: " + first["status"])
            print("Real DeepSeek study-design chat completed", flush=True)
            draft = checked(
                client.post(base + "/matrices", files={"file": ("GSE205450_CAU.tsv", raw)}), 201
            )
            assert r_calls == []
            goal = (
                "Analyze PD relative to Control in caudate only using two-group DESeq2, "
                "alpha=0.05, lfc_shrink=false, random_seed=42. Exploratory unadjusted comparison; "
                "report age/sex/RIN and NCBI sample-coverage limitations."
            )
            body = {
                "revision": draft["revision"],
                "direction": "genes_rows",
                "id_column": 0,
                "sample_columns": list(range(1, len(chosen) + 1)),
                "groups": {str(i): row["group"] for i, row in enumerate(chosen, 1)},
                "numerator": "PD",
                "denominator": "Control",
                "data_type": "RAW_COUNTS",
                "source": (
                    f"{ACCESSION}; NCBI-generated HISAT2/featureCounts raw counts; {COUNTS_URL}; "
                    f"SHA256 {COUNTS_SHA}; CAU only; availability exclusions recorded; "
                    f"{LIMITATIONS}"
                ),
                "goal": goal,
                "profile_id": profile,
            }
            budget.phase = "real_planner"
            record = checked(client.post(base + f"/matrices/{draft['id']}/confirm", json=body))
            save(output / "matrix-record.json", record)
            run = record["run_id"]
            run_base = f"/api/v1/runs/{run}"
            assert checked(client.get(run_base))["status"] == "AWAITING_APPROVAL"
            plan = checked(client.get(run_base + "/plan"))
            save(output / "reviewed-plan.json", plan)
            assert plan["plan"]["comparison"] == {
                "factor": "condition",
                "numerator": "PD",
                "denominator": "Control",
            }
            assert not r_calls
            print("Real DeepSeek plan awaiting approval; R calls: 0", flush=True)
            approved = checked(
                client.post(
                    run_base + "/approval",
                    json={"action": "approve", "plan_revision": plan["plan_revision"]},
                ),
                202,
            )
            app.state.dependencies.job_runner.wait(approved["job_id"], timeout=300)
            state = checked(client.get(run_base))
            if state["status"] != "COMPLETED":
                save(output / "failed-run.json", state)
                raise ValueError("REAL_R_NOT_COMPLETED: " + state["status"])
            assert len(r_calls) == 1
            artifacts = checked(client.get(run_base + "/artifacts"))["artifacts"]
            files = {}
            for item in artifacts:
                response = client.get(run_base + "/artifacts/" + item["artifact_id"])
                assert response.status_code == 200
                assert sha256(response.content).hexdigest() == item["sha256"]
                files[item["name"]] = response.content
            assert {
                "all_results.csv",
                "pca.png",
                "sample_correlation_heatmap.png",
                "ma_plot.png",
                "volcano_plot.png",
                "report.html",
                "manifest.json",
            } <= files.keys()
            manifest = json.loads(files["manifest.json"])
            for item in manifest["artifacts"]:
                assert (
                    sha256((output / "runs" / run / item["relative_path"]).read_bytes()).hexdigest()
                    == item["sha256"]
                )
            results = pd.read_csv(
                __import__("io").BytesIO(files["all_results.csv"]), dtype={"feature_id": str}
            )
            summary = checked(client.get(base + f"/matrices/{draft['id']}/results"))
            significant = results["padj"].le(manifest["alpha"])
            assert summary["genes"] == len(results)
            assert summary["significant_up"] == int(
                (significant & results["log2FoldChange"].gt(0)).sum()
            )
            assert summary["significant_down"] == int(
                (significant & results["log2FoldChange"].lt(0)).sum()
            )
            assert summary["adjusted_p_available"] == int(results["padj"].notna().sum())
            assert manifest["alpha"] == 0.05 and manifest["lfc_shrink"] is False
            assert manifest["input_hashes"]["counts"] == record["counts_sha256"]
            assert manifest["input_hashes"]["metadata"] == record["metadata_sha256"]
            top = (
                results.sort_values("padj")
                .head(20)
                .replace({np.nan: None})
                .to_dict(orient="records")
            )
            save(output / "top-genes.json", top)
            budget.phase = "real_result_interpretation"
            final = checked(
                client.post(
                    base + "/turns",
                    json={
                        "client_request_id": str(uuid4()),
                        "profile_id": profile,
                        "text": (
                            "统计已通过人工审批并由Rscript真实完成。请仅依据以下核验摘要、排名和限制，"
                            "用中文解释比较方向、主要观察与局限。不要调用工具或重新规划；"
                            "不要假称做过通路富集、诊断验证或原论文复现。基因为Entrez ID，"
                            "没有本次验证的符号映射时只保留ID。\n"
                        )
                        + json.dumps(
                            {"summary": summary, "top20": top, "limitations": LIMITATIONS},
                            ensure_ascii=False,
                        ),
                    },
                ),
                202,
            )
            final = wait_turn(client, final["id"])
            save(output / "interpretation-turn.json", final)
            if final["status"] != "COMPLETED":
                raise ValueError("REAL_INTERPRETATION_NOT_COMPLETED")
            messages = checked(client.get(base + "/messages"))["items"]
            save(output / "chat-messages.json", messages)
            explanation = "\n\n".join(
                m["content"]
                for m in messages
                if m["turn_id"] == final["id"] and m["role"] == "assistant"
            )
            (output / "deepseek-interpretation.md").write_text(explanation, encoding="utf-8")
            acceptance = {
                "accession": ACCESSION,
                "run_id": run,
                "model": settings.deepseek_model,
                "provider": "deepseek",
                "real_model": True,
                "r_calls": len(r_calls),
                "model_requests": len(budget.calls),
                "model_requests_current_attempt": len(budget.calls) - previous_call_count,
                "summary": summary,
                "source": audit,
                "completed_at": datetime.now(UTC).isoformat(),
            }
            save(output / "acceptance.json", acceptance)
            print(
                json.dumps(
                    {k: v for k, v in acceptance.items() if k != "source"}, ensure_ascii=True
                ),
                flush=True,
            )
    finally:
        factory.ChatOpenAI, adapters.ChatOpenAI = original_factory, original_adapter
        RRunner.run = real_r
        sync.close()
        # Async httpx is owned by the local application event loop and process.


if __name__ == "__main__":
    try:
        main()
    except Exception as failure:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_type": type(failure).__name__,
                    "code": str(failure)[:1200]
                    if isinstance(failure, (ValueError, AssertionError))
                    else getattr(failure, "code", None),
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None
