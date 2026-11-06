"""Explicit public GSE60450 acceptance; offline cache by default, real R, Mock Planner."""

from __future__ import annotations

import argparse
import gzip
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.domain.plans import AnalysisPlan
from bioagent.execution.r_runner import RRunner
from bioagent.geo.client import _build_source
from bioagent.geo.download import GeoDownloader
from bioagent.geo.transport import GeoTransport
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat

ROOT = Path(__file__).resolve().parents[1]
ACCESSION = "GSE60450"
FILE = "GSE60450_Lactation-GenewiseCounts.txt.gz"
URL = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE60nnn/GSE60450/suppl/" + FILE
COUNTS_SHA = "906b6ec4c33e95ca0ba454a3e0d07ad74e9cb7528ee38b89a9b122f5674a5f0d"
SOFT_SHA = "35a1950322dccaa555d13108492ab5b981cef51b7cd2d8de59658d2051cd4549"
SOFT_URL = (
    "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE60450&targ=all&form=text&view=brief"
)
GOAL = "Compare basal mammary cells at 2 day lactation relative to virgin, independent mice."
EXPECTED = {
    "GSM1480297": ("virgin", "Virgin"),
    "GSM1480298": ("virgin", "Virgin"),
    "GSM1480301": ("2 day lactation", "Lactating"),
    "GSM1480302": ("2 day lactation", "Lactating"),
}


def locked_cache(path: Path, expected: str) -> bytes:
    if not path.is_file():
        raise ValueError("CACHE_MISSING: use --download explicitly")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("CACHE_TOO_LARGE")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError("CACHE_HASH_MISMATCH")
    return raw


def sample_design(source: dict, headers: list[str]) -> tuple[dict, dict, list]:
    by_id = {sample["accession"]: sample for sample in source["samples"]}
    mapping, groups = {}, {}
    for identity, (stage, group) in EXPECTED.items():
        sample = by_id.get(identity, {})
        traits = {item["value"] for item in sample.get("characteristics", [])}
        names = [
            item["value"]
            for item in sample.get("fields", [])
            if item["name"] == "Sample_description" and item["value"] in headers
        ]
        if (
            sample.get("platform") != "GPL13112"
            or "immunophenotype: basal cell population" not in traits
            or "developmental stage: " + stage not in traits
            or len(names) != 1
            or names[0] in mapping
        ):
            raise ValueError("SAMPLE_EVIDENCE_MISMATCH: " + identity)
        mapping[names[0]] = identity
        groups[identity] = group
    return mapping, groups, sorted(set(by_id) - set(groups))


def prepare_cache(cache: Path, download: bool) -> tuple[bytes, dict]:
    cache.mkdir(parents=True, exist_ok=True)
    for name, url, digest in [
        (FILE, URL, COUNTS_SHA),
        ("GSE60450-family.soft", SOFT_URL, SOFT_SHA),
    ]:
        path = cache / name
        if not path.exists() and download:
            result = GeoDownloader(GeoTransport(), root=cache, max_retries=0).download(
                url, path, expected_sha256=digest
            )
            path.with_suffix(".audit.json").write_text(
                json.dumps(
                    {
                        "url": url,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "bytes": result.bytes_downloaded,
                        "sha256": result.sha256,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        locked_cache(path, digest)
    source = _build_source(
        ACCESSION, (cache / "GSE60450-family.soft").read_text(encoding="utf-8"), ()
    )
    return gzip.decompress(locked_cache(cache / FILE, COUNTS_SHA)), source.model_dump(mode="json")


class MockPlanner:
    def plan(self, *, user_goal, summary):
        return AnalysisPlan(
            dataset_id=summary.dataset_id,
            comparison={"factor": "condition", "numerator": "Lactating", "denominator": "Virgin"},
            options={"lfc_shrink": False, "alpha": 0.05, "random_seed": 42},
        )


def make_app(output: Path):
    async def stream(messages):
        yield "Mock"

    def prepare(*_):
        return PreparedChat(
            TurnModelSnapshot(
                provider="ollama",
                model="mock",
                base_url="http://localhost:11434",
                revision=1,
                structured_method="function_calling",
                thinking="default",
            ),
            stream,
            planner=MockPlanner(),
        )

    return create_app(
        Settings(
            _env_file=None,
            deepseek_api_key=None,
            data_dir=output / "data",
            runs_dir=output / "runs",
            checkpoint_db=output / "cp.sqlite",
            workbench_db=output / "wb.sqlite",
        ),
        {"planner": MockPlanner(), "chat_model_factory": prepare},
    )


def checked(response, expected=200):
    assert response.status_code == expected, (response.status_code, response.text[:2000])
    return response.json()


def poll(client, path, pending):
    deadline = monotonic() + 240
    while monotonic() < deadline:
        state = checked(client.get(path))
        if state["status"] not in pending:
            return state
        sleep(0.2)
    raise TimeoutError(path)


def geo_import(client, output, audit):
    base = "/api/v1/geo"
    search = checked(client.post(base + "/searches", json={"text": ACCESSION}), 202)
    search = poll(client, base + "/searches/" + search["id"], {"QUEUED", "SEARCHING"})
    audit["search"] = search
    if search["status"] == "AWAITING_SELECTION":
        selected = checked(
            client.post(
                base + "/searches/" + search["id"] + "/selection",
                json={"accession": ACCESSION, "revision": search["revision"]},
            ),
            202,
        )
        identity = selected["source_id"]
    else:
        identity = checked(client.post(base + "/sources", json={"accession": ACCESSION}), 202)["id"]
    source = poll(client, base + "/sources/" + identity, {"DISCOVERING"})
    audit["source"] = source
    assert source["status"] == "AWAITING_SELECTION", source
    candidate = next(c for c in source["source"]["candidates"] if c["file_name"] == FILE)
    imported = checked(
        client.post(
            base + "/sources/" + identity + "/imports",
            json={"candidate_id": candidate["id"], "revision": source["revision"]},
        ),
        202,
    )
    path = base + "/imports/" + imported["id"]
    imported = poll(client, path, {"DOWNLOADING"})
    audit["download"] = imported
    assert imported["status"] == "AWAITING_MAPPING", imported
    assert imported["raw_sha256"] == COUNTS_SHA
    mapping, groups, excluded = sample_design(source["source"], imported["preview"]["headers"])
    selection = {
        "source_id": identity,
        "candidate_id": candidate["id"],
        "raw_sha256": COUNTS_SHA,
        "feature_column": "EntrezGeneID",
        "sample_columns": list(mapping),
        "sample_map": mapping,
        "groups": groups,
        "numerator": "Lactating",
        "denominator": "Virgin",
        "revision": imported["revision"],
        "excluded_samples": excluded,
        "confirmed_raw_type": "RAW_COUNTS",
        "evidence": [SOFT_URL, GOAL],
    }
    checked(client.post(path + "/selection", json=selection), 202)
    ready = poll(client, path, {"VALIDATING"})
    audit["ready"] = ready
    assert ready["status"] == "READY", ready
    (output / "geo-audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return ready


def verify_run(client, app, run, output):
    base = "/api/v1/runs/" + run
    assert checked(client.get(base))["status"] == "AWAITING_APPROVAL"
    assert not list((output / "runs" / run / "attempts").glob("*"))
    approval = checked(
        client.post(base + "/approval", json={"action": "approve", "plan_revision": 1}), 202
    )
    app.state.dependencies.job_runner.wait(approval["job_id"], timeout=300)
    state = checked(client.get(base))
    assert state["status"] == "COMPLETED", state
    files = {}
    for item in checked(client.get(base + "/artifacts"))["artifacts"]:
        response = client.get(base + "/artifacts/" + item["artifact_id"])
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
    zero_issue = next(i for i in manifest["qc"]["issues"] if i["code"] == "ZERO_FEATURE_REMOVED")
    assert str(zero_issue["evidence"]["feature_count"]).encode() in files["report.html"]
    assert b"LOW_REPLICATE_NUMBER" in files["report.html"]
    assert manifest["comparison"] == {
        "factor": "condition",
        "numerator": "Lactating",
        "denominator": "Virgin",
    }
    for artifact in manifest["artifacts"]:
        data = (output / "runs" / run / artifact["relative_path"]).read_bytes()
        assert sha256(data).hexdigest() == artifact["sha256"]
    table = pd.read_csv(BytesIO(files["all_results.csv"])).sort_values("feature_id")
    return manifest, table


def verify_result_summary(table, alpha, summary):
    """Reconcile HTTP counts with the existing R/report padj <= alpha contract."""
    significant = table["padj"].le(alpha)
    assert summary["genes"] == len(table)
    assert summary["adjusted_p_available"] == int(table["padj"].notna().sum())
    assert summary["significant_up"] == int((significant & (table["log2FoldChange"] > 0)).sum())
    assert summary["significant_down"] == int((significant & (table["log2FoldChange"] < 0)).sum())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true", help="explicitly enable official GEO network I/O"
    )
    parser.add_argument("--cache", type=Path, default=ROOT / "data/task49/research")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output, cache = args.output.resolve(), args.cache.resolve()
    if output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW: preserve previous acceptance evidence")
    output.mkdir(parents=True)
    raw, source = prepare_cache(cache, args.download)
    frame = pd.read_csv(BytesIO(raw), sep="\t", dtype=str)
    mapping, groups, excluded = sample_design(source, list(frame.columns))
    libraries = sorted((ROOT / "renv/library").glob("*/R-*/**/DESeq2"))
    if libraries:
        os.environ["R_LIBS"] = str(libraries[0].parent)
        os.environ["RENV_CONFIG_AUTOLOADER_ENABLED"] = "FALSE"
    original, calls = RRunner.run, []

    def tracked(self, *a, **kw):
        calls.append("Rscript")
        return original(self, *a, **kw)

    RRunner.run = tracked
    audit = {}
    try:
        app = make_app(output)
        with TestClient(app, base_url="http://localhost") as client:
            client.headers["X-CSRF-Token"] = checked(client.get("/api/v1/workbench/bootstrap"))[
                "csrf_token"
            ]
            geo = None
            if args.download:
                try:
                    geo = geo_import(client, output, audit)
                finally:
                    (output / "geo-audit.json").write_text(
                        json.dumps(audit, indent=2), encoding="utf-8"
                    )
                print("Official GEO search/source/download/mapping completed", flush=True)
            project = checked(
                client.post("/api/v1/workbench/projects", json={"title": ACCESSION}), 201
            )
            chat = checked(
                client.post(
                    "/api/v1/workbench/conversations",
                    json={"project_id": project["id"], "title": GOAL},
                ),
                201,
            )["id"]
            prefix = f"/api/v1/workbench/conversations/{chat}/matrices"
            draft = checked(client.post(prefix, files={"file": ("GSE60450.tsv", raw)}), 201)
            assert calls == []
            body = {
                "revision": draft["revision"],
                "direction": "genes_rows",
                "id_column": 0,
                "sample_columns": [list(frame.columns).index(c) for c in mapping],
                "groups": {
                    str(list(frame.columns).index(c)): groups[g] for c, g in mapping.items()
                },
                "numerator": "Lactating",
                "denominator": "Virgin",
                "data_type": "RAW_COUNTS",
                "source": (
                    f"{ACCESSION}; official featureCounts Entrez read counts; "
                    f"{COUNTS_SHA}; {SOFT_URL}"
                ),
                "goal": GOAL,
                "profile_id": str(uuid4()),
            }
            record = checked(client.post(prefix + "/" + draft["id"] + "/confirm", json=body))
            assert calls == []
            print("Matrix confirmed; R calls before approval: 0", flush=True)
            manifest, table = verify_run(client, app, record["run_id"], output)
            nonzero = frame[list(mapping)].astype("int64").sum(axis=1) > 0
            removed_count = int((~nonzero).sum())
            assert set(table["feature_id"].astype(str)) == set(frame.loc[nonzero, "EntrezGeneID"])
            zero_issue = next(
                i for i in manifest["qc"]["issues"] if i["code"] == "ZERO_FEATURE_REMOVED"
            )
            assert zero_issue["evidence"]["feature_count"] == removed_count
            assert manifest["qc"]["status"] == "WARN"
            assert any(i["code"] == "LOW_REPLICATE_NUMBER" for i in manifest["qc"]["issues"])
            assert manifest["input_hashes"]["counts"] == record["counts_sha256"]
            assert manifest["input_hashes"]["metadata"] == record["metadata_sha256"]
            summary = checked(client.get(prefix + "/" + draft["id"] + "/results"))
            verify_result_summary(table, manifest["alpha"], summary)
            geo_run = None
            if geo:
                # READY already created an approval-gated plan through resume_geo_ready.
                candidates = [
                    r
                    for r in checked(client.get("/api/v1/runs"))["runs"]
                    if r["dataset_id"] == geo["dataset_id"]
                ]
                assert len(candidates) == 1, candidates
                geo_run = candidates[0]["run_id"]
                geo_state = checked(client.get("/api/v1/runs/" + geo_run))
                assert geo_state["agent_context"]["source_id"] == geo["published_source_id"]
                geo_manifest, other = verify_run(client, app, geo_run, output)
                assert geo_manifest["source_id"] == geo["published_source_id"]
                assert list(table["feature_id"]) == list(other["feature_id"])
                for column in ["log2FoldChange", "pvalue", "padj"]:
                    np.testing.assert_allclose(
                        table[column], other[column], rtol=1e-8, atol=1e-10, equal_nan=True
                    )
            acceptance = {
                "accession": ACCESSION,
                "source_sha256": COUNTS_SHA,
                "metadata_sha256": SOFT_SHA,
                "official_url": URL,
                "sample_map": mapping,
                "groups": groups,
                "excluded_samples": excluded,
                "annotation_not_counts": ["Length"],
                "input_genes": len(frame),
                "all_zero_removed": removed_count,
                "matrix": record,
                "summary": summary,
                "geo_run": geo_run,
                "r_calls": len(calls),
                "real_network": args.download,
                "numeric_parity": bool(geo),
                "completed_at": datetime.now(UTC).isoformat(),
            }
            (output / "acceptance.json").write_text(
                json.dumps(acceptance, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "run": record["run_id"],
                        "geo_run": geo_run,
                        "summary": summary,
                        "r_calls": len(calls),
                    },
                    indent=2,
                ),
                flush=True,
            )
    finally:
        RRunner.run = original


if __name__ == "__main__":
    main()
