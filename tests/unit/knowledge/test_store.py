import json
import shutil
from hashlib import sha256
from uuid import uuid4

import pytest

from bioagent.knowledge.store import KnowledgeError, KnowledgeStore


def parsed_output(store, job):
    """Simulate only the publication boundary, not PDF parsing."""
    folder = store.job_dir(job["id"])
    folder.mkdir(parents=True, exist_ok=True)
    raw = b'{"schema_name":"DoclingDocument"}'
    (folder / "docling.json").write_bytes(raw)
    (folder / "settings.json").write_bytes(b"{}")
    (folder / "models.json").write_bytes(b"{}")
    png = b"png fixture"
    asset_id = str(uuid4())
    (folder / f"{asset_id}.png").write_bytes(png)
    result = {
        "schema_version": "parsed.v1",
        "source_sha256": job["source_sha256"],
        "parser_version": "fixture",
        "settings_sha256": sha256(b"{}").hexdigest(),
        "models_sha256": sha256(b"{}").hexdigest(),
        "page_count": 1,
        "elements": [
            {
                "id": "#/texts/0",
                "kind": "text",
                "text": "untrusted text",
                "order": 0,
                "section": [],
                "locations": [{"page": 1, "bbox": [0, 10, 10, 0], "origin": "BOTTOMLEFT"}],
            }
        ],
        "assets": [{"id": asset_id, "sha256": sha256(png).hexdigest(), "media_type": "image/png"}],
        "raw_sha256": sha256(raw).hexdigest(),
        "warnings": ["FIGURE_SEMANTICS_NOT_PERFORMED"],
    }
    (folder / "parsed.json").write_text(json.dumps(result), encoding="utf-8")
    return asset_id


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path / "knowledge")


def test_store_accepts_exactly_50_mib_and_rejects_one_byte_more(store):
    base = store.create_base("limits")
    pdf = b"%PDF-" + b" " * (50 * 1024**2 - 5)
    doc = store.import_pdf(base["id"], "large.pdf", pdf)["document"]
    assert store.original(doc["id"]).stat().st_size == 50 * 1024**2
    with pytest.raises(KnowledgeError, match="PDF_TOO_LARGE"):
        store.import_pdf(base["id"], "oversize.pdf", pdf + b" ")


def test_dedup_is_scoped_to_base_and_restart_preserves_revision(store):
    a, b = store.create_base("a"), store.create_base("b")
    one = store.import_pdf(a["id"], "paper.pdf", b"%PDF-1.7 fixture")
    two = store.import_pdf(a["id"], "different.pdf", b"%PDF-1.7 fixture")
    other = store.import_pdf(b["id"], "paper.pdf", b"%PDF-1.7 fixture")
    assert two["duplicate"] and two["document"]["id"] == one["document"]["id"]
    assert other["document"]["id"] != one["document"]["id"]
    job = store.claim()
    parsed_output(store, job)
    assert store.publish(job["id"])
    reopened = KnowledgeStore(store.root)
    doc = reopened.document(one["document"]["id"])
    assert doc["status"] == "PARSED" and doc["index_revision"] is None
    assert doc["published_revision"] == job["revision_id"]


@pytest.mark.parametrize("action", ["cancel", "delete"])
def test_cancel_or_delete_wins_over_late_publication(store, action):
    base = store.create_base("base")
    doc = store.import_pdf(base["id"], "paper.pdf", b"%PDF-1.7 fixture")["document"]
    job = store.claim()
    if action == "cancel":
        store.cancel(job["id"])
    else:
        store.delete_document(doc["id"])
    parsed_output(store, job)
    assert not store.publish(job["id"])
    if action == "cancel":
        new = store.retry(doc["id"])
        assert new["revision_id"] != job["revision_id"]
        assert store.document(doc["id"])["published_revision"] is None
    else:
        with pytest.raises(KnowledgeError, match="DOCUMENT_NOT_FOUND"):
            store.document(doc["id"])


def test_restart_marks_inflight_failed_and_does_not_publish(store):
    base = store.create_base("base")
    doc = store.import_pdf(base["id"], "paper.pdf", b"%PDF-1.7 fixture")["document"]
    job = store.claim()
    parsed_output(store, job)
    store.recover()
    assert not store.job_dir(job["id"]).exists()
    assert store.job(job["id"])["error_code"] == "INGESTION_INTERRUPTED"
    assert store.document(doc["id"])["status"] == "FAILED"
    assert not store.publish(job["id"])


def test_assets_require_current_revision_ownership_and_integrity(store):
    base = store.create_base("base")
    doc = store.import_pdf(base["id"], "paper.pdf", b"%PDF-1.7 fixture")["document"]
    job = store.claim()
    asset_id = parsed_output(store, job)
    assert store.publish(job["id"])
    path = store.asset(doc["id"], job["revision_id"], asset_id)
    path.write_bytes(b"tampered")
    with pytest.raises(KnowledgeError, match="RESOURCE_INTEGRITY_FAILED"):
        store.asset(doc["id"], job["revision_id"], asset_id)
    with pytest.raises(KnowledgeError):
        store.asset(doc["id"], str(uuid4()), asset_id)
    with pytest.raises(KnowledgeError):
        store.original("../../outside")


def test_restart_retries_cleanup_of_deleted_source_locked_on_windows(store, monkeypatch):
    base = store.create_base("base")
    doc = store.import_pdf(base["id"], "paper.pdf", b"%PDF-1.7 fixture")["document"]
    folder = store.original(doc["id"]).parent
    real_remove = shutil.rmtree

    def locked(path):
        raise PermissionError("simulated original.pdf sharing violation")

    monkeypatch.setattr("bioagent.knowledge.store.shutil.rmtree", locked)
    store.delete_document(doc["id"])
    assert folder.exists()
    with pytest.raises(KnowledgeError, match="DOCUMENT_NOT_FOUND"):
        store.original(doc["id"])
    monkeypatch.setattr("bioagent.knowledge.store.shutil.rmtree", real_remove)
    store.recover()
    assert not folder.exists()
