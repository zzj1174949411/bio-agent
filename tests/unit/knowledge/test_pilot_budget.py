import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from bioagent.knowledge.store import KnowledgeError

scripts = Path(__file__).parents[3] / "scripts"
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location("pilot_budget", scripts / "run_literature_pilot.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_global_reservation_survives_restart_and_unknown_failure_stops(tmp_path):
    ledger = module.Ledger(tmp_path / "ledger.json")
    number = ledger.reserve([HumanMessage("bounded input")], 2000)
    reopened = module.Ledger(ledger.path)
    assert reopened.data["calls"][0]["status"] == "RESERVED_UNKNOWN"
    assert reopened.data["calls"][0]["usage"] is None
    ledger.finish(number, "MODEL_TIMEOUT")
    reopened = module.Ledger(ledger.path)
    with pytest.raises(KnowledgeError, match="PILOT_GLOBAL_BUDGET_STOP"):
        reopened.reserve([HumanMessage("no retry")], 2000)


def test_global_call_and_input_output_limits_are_checked_before_send(tmp_path):
    ledger = module.Ledger(tmp_path / "ledger.json")
    for _ in range(50):
        ledger.reserve([HumanMessage("a" * 32000)], 2000)
    assert sum(c["input_bytes"] for c in ledger.data["calls"]) == 1600000
    with pytest.raises(KnowledgeError):
        ledger.reserve([HumanMessage("one more")], 2000)
    for text, limit in [("a" * 32001, 2000), ("small", 2001)]:
        fresh = module.Ledger(tmp_path / (str(limit) + ".json"))
        with pytest.raises(KnowledgeError):
            fresh.reserve([HumanMessage(text)], limit)
        assert not fresh.data["calls"]


def test_explicit_resume_preserves_failed_calls_and_refuses_unknown_inflight(tmp_path):
    ledger = module.Ledger(tmp_path / "ledger.json")
    number = ledger.reserve([HumanMessage("existing possibly charged request")], 2000)
    with pytest.raises(KnowledgeError, match="PILOT_UNKNOWN_INFLIGHT"):
        ledger.resume_after_fix()
    ledger.finish(number, "MODEL_CONNECTION_FAILED")
    original = dict(ledger.data["calls"][0])
    ledger.resume_after_fix()
    assert ledger.data["calls"][0] == original
    assert ledger.data["resume_events"][0]["calls_before"] == 1
    assert not ledger.data["stopped"]
    assert ledger.reserve([HumanMessage("new explicitly authorized request")], 2000) == 2


def test_reference_crossing_chunk_boundary_requires_complete_exact_coverage():
    first = "First verified original fact. "
    second = "Second verified original condition."
    chunks = [
        SimpleNamespace(id=1, text=first, element_id="e", locations=[SimpleNamespace(page=2)]),
        SimpleNamespace(id=2, text=second, element_id="e", locations=[SimpleNamespace(page=2)]),
    ]
    reference = {"quote": first + second, "element_id": "e", "page": 2}
    assert module.reference_chunks(chunks, reference) == chunks
    with pytest.raises(KnowledgeError, match="PILOT_REFERENCE_NOT_IN_CHUNK"):
        module.reference_chunks(chunks[:1], reference)


def test_probe_and_following_call_share_backend_loop_with_sdk_keepalive(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(1)
            body = json.dumps(
                {
                    "id": "local-mock",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "local-mock",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": '{"ok":true}'},
                            "finish_reason": "stop",
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"
    first = ChatOpenAI(
        model="local-mock", api_key="mock-only", base_url=endpoint, max_retries=0, timeout=5
    )
    second = ChatOpenAI(
        model="local-mock", api_key="mock-only", base_url=endpoint, max_retries=0, timeout=5
    )
    assert first.root_async_client._client is second.root_async_client._client
    try:
        with TestClient(FastAPI()) as client:
            module.run_probe(client, first)
            response = client.portal.call(second.ainvoke, [HumanMessage("local mock")])
            assert response.content == '{"ok":true}'
            client.portal.call(first.root_async_client.close)
        assert len(calls) == 2
    finally:
        server.shutdown()
        server.server_close()
