import asyncio
import time
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat


@pytest.fixture
def client(tmp_path):
    calls = []

    def prepare(profile_id, fixed=None):
        async def answer(messages):
            calls.append(messages[-1].content)
            yield "hello\n\nid: 99"

        return PreparedChat(
            fixed
            or TurnModelSnapshot(
                provider="ollama",
                model="mock",
                base_url="http://localhost:11434",
                revision=1,
                structured_method="function_calling",
                thinking="default",
            ),
            answer,
        )

    app = create_app(
        Settings(
            _env_file=None,
            deepseek_api_key=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            workbench_db=tmp_path / "wb.sqlite",
            local_allowed_hosts=("127.0.0.1", "localhost"),
        ),
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "secret_store": Mock(),
            "chat_model_factory": prepare,
        },
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as api:
        token = api.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
        api.headers["X-CSRF-Token"] = token
        api.calls = calls
        yield api


def conversation(client):
    p = client.post("/api/v1/workbench/projects", json={"title": "RNA"})
    assert p.status_code == 201
    c = client.post(
        "/api/v1/workbench/conversations", json={"project_id": p.json()["id"], "title": "chat"}
    )
    assert c.status_code == 201
    return c.json()


def test_project_conversation_api_and_turn_retry(client):
    c = conversation(client)
    updated = client.patch(f"/api/v1/workbench/conversations/{c['id']}", json={"title": "renamed"})
    assert updated.status_code == 200 and updated.json()["title"] == "renamed"
    body = {
        "client_request_id": str(uuid4()),
        "text": "hello",
        "profile_id": str(uuid4()),
        "dataset_ids": [],
    }
    response = client.post(f"/api/v1/workbench/conversations/{c['id']}/turns", json=body)
    assert response.status_code == 202
    duplicate = client.post(f"/api/v1/workbench/conversations/{c['id']}/turns", json=body)
    assert duplicate.status_code == 202 and duplicate.json()["id"] == response.json()["id"]
    assert client.get(f"/api/v1/workbench/conversations/{c['id']}/messages").status_code == 200
    assert client.get("/api/v1/workbench/projects?limit=101").status_code == 422
    assert (
        client.get(
            "/api/v1/workbench/conversations", params={"project_id": c["project_id"]}
        ).status_code
        == 200
    )
    archived = client.patch(
        f"/api/v1/workbench/projects/{c['project_id']}", json={"archived": True}
    )
    assert archived.status_code == 200 and archived.json()["archived"]


@pytest.mark.parametrize("after,last", [("-1", None), ("bad", None), ("1", "bad"), ("2", "-1")])
def test_sse_invalid_cursor_fails_before_streaming(client, after, last):
    c = conversation(client)
    response = client.get(
        f"/api/v1/workbench/conversations/{c['id']}/events",
        params={"after": after},
        headers={"Last-Event-ID": last} if last is not None else {},
    )
    assert response.status_code == 422


def test_new_routes_preserve_csrf_and_origin_protection(client):
    response = client.post(
        "/api/v1/workbench/projects", json={"title": "bad"}, headers={"X-CSRF-Token": "wrong"}
    )
    assert response.status_code == 403
    response = client.get("/api/v1/workbench/projects", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert client.get(f"/api/v1/workbench/conversations/{uuid4()}/messages").status_code == 404


def test_actual_sse_response_has_persisted_cursor_and_bounded_disconnect(client):
    c = conversation(client)
    store = client.app.state.dependencies.workbench
    turn = store.begin_turn(c["id"], uuid4(), "hello", None)
    store.append_event(c["id"], turn.id, "message.delta", {"text": "x\n\nid: 99"})

    async def request():
        disconnected = asyncio.Event()
        messages = []

        async def receive():
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                disconnected.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "method": "GET",
            "path": f"/api/v1/workbench/conversations/{c['id']}/events",
            "query_string": b"after=0",
            "headers": [(b"host", b"127.0.0.1:8000"), (b"last-event-id", b"1")],
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 1234),
            "http_version": "1.1",
            "root_path": "",
        }
        async with asyncio.timeout(5):
            await client.app(scope, receive, send)
        return messages

    response = asyncio.run(request())
    assert response[0]["status"] == 200
    assert b"text/event-stream" in dict(response[0]["headers"])[b"content-type"]
    body = b"".join(m.get("body", b"") for m in response)
    assert body.startswith(b"id: 2\n") and body.count(b"\ndata: ") == 1
    assert store.get_turn(turn.id).status == "QUEUED"


def test_slow_chat_does_not_block_get_or_use_r_worker(client, monkeypatch):
    started, release = Event(), Event()

    async def slow(messages):
        started.set()
        yield "partial"
        while not release.is_set():
            await asyncio.sleep(0.01)
        yield "done"

    deps = client.app.state.dependencies
    original = deps.turn_service._prepare

    def prepare(identity, fixed=None):
        prepared = original(identity, fixed)
        return PreparedChat(prepared.snapshot, slow)

    monkeypatch.setattr(deps.turn_service, "_prepare", prepare)
    r_submit = Mock(side_effect=AssertionError("chat must not use R worker"))
    monkeypatch.setattr(deps.job_runner, "submit", r_submit)
    c = conversation(client)
    try:
        response = client.post(
            f"/api/v1/workbench/conversations/{c['id']}/turns",
            json={"client_request_id": str(uuid4()), "text": "hello", "profile_id": str(uuid4())},
        )
        assert response.status_code == 202 and started.wait(5)
        assert client.get("/api/v1/workbench/projects").status_code == 200
        turn_id = response.json()["id"]
        assert client.get(f"/api/v1/workbench/turns/{turn_id}").json()["status"] == "RUNNING"
        cancelled = client.post(f"/api/v1/workbench/turns/{turn_id}/cancel")
        assert cancelled.status_code == 202 and cancelled.json()["cancel_requested"]
        assert cancelled.json()["status"] == "CANCELLED"
        r_submit.assert_not_called()
    finally:
        release.set()


def test_waiting_user_api_requires_current_response(client, monkeypatch):
    from bioagent.workbench.turns import Clarification

    original = client.app.state.dependencies.turn_service._prepare

    def prepare(identity, fixed=None):
        prepared = original(identity, fixed)

        async def answer(messages):
            if messages[-1].content == "help":
                yield Clarification("Which group?")
            else:
                yield "done"

        return PreparedChat(prepared.snapshot, answer)

    monkeypatch.setattr(client.app.state.dependencies.turn_service, "_prepare", prepare)
    c = conversation(client)
    body = {"client_request_id": str(uuid4()), "text": "help", "profile_id": str(uuid4())}
    turn = client.post(f"/api/v1/workbench/conversations/{c['id']}/turns", json=body).json()
    deadline = time.monotonic() + 5
    while turn["status"] != "WAITING_USER" and time.monotonic() < deadline:
        turn = client.get(f"/api/v1/workbench/turns/{turn['id']}").json()
    assert turn["status"] == "WAITING_USER"
    busy = client.post(
        f"/api/v1/workbench/conversations/{c['id']}/turns",
        json={**body, "client_request_id": str(uuid4())},
    )
    assert busy.status_code == 409
    pending = turn["pending_input"]
    response = {
        "request_id": pending["request_id"],
        "revision": pending["revision"],
        "action": "clarify",
        "value": "AD",
    }
    path = f"/api/v1/workbench/turns/{turn['id']}/responses"
    assert (
        client.post(path, json={**response, "revision": pending["revision"] + 1}).status_code == 409
    )
    assert client.post(path, json=response).status_code == 202
    assert client.post(path, json=response).status_code == 409


def test_missing_model_is_actionable_and_does_not_create_turn(client):
    c = conversation(client)
    response = client.post(
        f"/api/v1/workbench/conversations/{c['id']}/turns",
        json={"client_request_id": str(uuid4()), "text": "hello"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MODEL_NOT_CONFIGURED"
    assert client.get(f"/api/v1/workbench/conversations/{c['id']}/messages").json()["items"] == []
