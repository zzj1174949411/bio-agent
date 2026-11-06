import subprocess
import sys
import time
from threading import Event

import pytest

from bioagent.knowledge.service import KnowledgeService
from bioagent.knowledge.store import KnowledgeStore


@pytest.mark.parametrize("reason", ["timeout", "cancel", "memory"])
def test_supervisor_terminates_process_and_never_publishes(tmp_path, monkeypatch, reason):
    store = KnowledgeStore(tmp_path / "knowledge")
    base = store.create_base("base")
    doc = store.import_pdf(base["id"], "fixture.pdf", b"%PDF-1.7 fixture")["document"]
    real_popen, processes = subprocess.Popen, []
    started = Event()

    def capture_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr("bioagent.knowledge.service.subprocess.Popen", capture_process)
    # Only process supervision is replaced. Real parser validation is a separate experiment.
    service = KnowledgeService(
        store,
        tmp_path / "models",
        timeout_seconds=0.3 if reason == "timeout" else 30,
        readiness=lambda: {"ready": True, "code": "OK"},
        memory_bytes=1024 if reason == "memory" else 4 * 1024**3,
        command=lambda job: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    service.start(recover=False)
    try:
        deadline = time.monotonic() + 10
        while store.document(doc["id"])["status"] == "QUEUED" and time.monotonic() < deadline:
            time.sleep(0.02)
        job = store.document(doc["id"])["job"]
        assert started.wait(timeout=5)
        if reason == "cancel":
            store.cancel(job["id"])
        while service.active and time.monotonic() < deadline:
            time.sleep(0.02)
        state = store.document(doc["id"])
        assert state["status"] == ("CANCELLED" if reason == "cancel" else "FAILED")
        assert state["published_revision"] is None
        if reason == "timeout":
            assert state["job"]["error_code"] == "PARSE_TIMEOUT"
        if reason == "memory":
            assert state["job"]["error_code"] == "PARSE_MEMORY_LIMIT"
    finally:
        service.close()
    assert not service.active
    assert processes and all(process.poll() is not None for process in processes)
