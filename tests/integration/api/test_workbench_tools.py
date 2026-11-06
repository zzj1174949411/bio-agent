import time
from uuid import uuid4

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.workbench.models import TurnModelSnapshot
from bioagent.workbench.turns import PreparedChat

SNAPSHOT = TurnModelSnapshot(
    provider="ollama",
    model="fixture",
    base_url="http://localhost:11434",
    revision=1,
    structured_method="function_calling",
    thinking="default",
)


class _SearchService:
    def __init__(self) -> None:
        self.search_id = str(uuid4())
        self.calls: list[tuple[object, str, str]] = []
        self._event_sink = None

    def bind_event_sink(self, sink) -> None:
        self._event_sink = sink

    def close(self) -> None:
        return None

    def create(self, query, conversation_id: str, turn_id: str) -> dict[str, object]:
        self.calls.append((query, conversation_id, turn_id))
        if self._event_sink is not None:
            self._event_sink(
                {
                    "conversation_id": conversation_id,
                    "turn_id": turn_id,
                    "kind": "geo.updated",
                    "id": self.search_id,
                    "status": "QUEUED",
                    "revision": 1,
                    "result_count": 0,
                }
            )
        return {
            "id": self.search_id,
            "status": "QUEUED",
            "revision": 1,
            "query_hash": "a" * 64,
            "items": [],
            "result_count": 0,
            "total": 0,
            "next_page_token": None,
            "source_id": None,
            "error_code": None,
        }

    def owns(self, _search_id: str, _owner_token_sha256: str) -> bool:
        return False

    def is_conversation_search(self, search_id: str, *_context: str) -> bool:
        return str(search_id) == self.search_id

    def get(self, search_id: str) -> dict[str, object]:
        assert str(search_id) == self.search_id
        return {
            "id": self.search_id,
            "status": "AWAITING_SELECTION",
            "revision": 2,
            "query_hash": "a" * 64,
            "query": {"text": "AD brain RNA-seq", "provider": "geo", "page_size": 10},
            "items": [],
            "result_count": 0,
            "total": 0,
            "next_page_token": None,
            "source_id": None,
            "error_code": None,
        }


def test_workbench_turn_uses_controlled_action_loop(tmp_path):
    def prepare(_identity, fixed=None):
        async def stream(_messages):
            yield {"kind": "answer", "text": "controlled"}

        return PreparedChat(fixed or SNAPSHOT, stream)

    app = create_app(
        Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "checkpoint.sqlite",
            workbench_db=tmp_path / "wb.sqlite",
            local_allowed_hosts=("127.0.0.1", "localhost"),
        ),
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "readiness": lambda: True,
            "chat_model_factory": prepare,
        },
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.headers["X-CSRF-Token"] = client.get(
            "/api/v1/workbench/bootstrap"
        ).json()["csrf_token"]
        project = client.post("/api/v1/workbench/projects", json={"title": "fixture"}).json()
        conversation = client.post(
            "/api/v1/workbench/conversations",
            json={"project_id": project["id"], "title": "chat"},
        ).json()["id"]
        turn = client.post(
            f"/api/v1/workbench/conversations/{conversation}/turns",
            json={"client_request_id": str(uuid4()), "text": "hello", "profile_id": str(uuid4())},
        )
        assert turn.status_code == 202, turn.text
        identity = turn.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f"/api/v1/workbench/turns/{identity}").json()
            if current["status"] == "COMPLETED":
                break
            time.sleep(0.01)
        assert current["status"] == "COMPLETED"
        messages = client.get(f"/api/v1/workbench/conversations/{conversation}/messages").json()
        assert any(message["content"] == "controlled" for message in messages["items"])


def test_workbench_dataset_search_waits_for_user_selection_and_recovers_search_state(tmp_path):
    def prepare(_identity, fixed=None):
        async def stream(_messages):
            yield {
                "kind": "dataset_search",
                "text": "AD brain RNA-seq",
                "organism": "Homo sapiens",
            }

        return PreparedChat(fixed or SNAPSHOT, stream)

    search = _SearchService()
    app = create_app(
        Settings(
            _env_file=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "checkpoint.sqlite",
            workbench_db=tmp_path / "wb.sqlite",
            local_allowed_hosts=("127.0.0.1", "localhost"),
        ),
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "readiness": lambda: True,
            "chat_model_factory": prepare,
            "geo_search_service": search,
        },
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        client.headers["X-CSRF-Token"] = client.get(
            "/api/v1/workbench/bootstrap"
        ).json()["csrf_token"]
        project = client.post("/api/v1/workbench/projects", json={"title": "fixture"}).json()
        conversation = client.post(
            "/api/v1/workbench/conversations",
            json={"project_id": project["id"], "title": "chat"},
        ).json()
        submitted = client.post(
            f"/api/v1/workbench/conversations/{conversation['id']}/turns",
            json={
                "client_request_id": str(uuid4()),
                "text": "Find Alzheimer brain RNA-seq datasets",
                "profile_id": str(uuid4()),
            },
        )
        assert submitted.status_code == 202, submitted.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            turn = client.get(f"/api/v1/workbench/turns/{submitted.json()['id']}").json()
            if turn["status"] in {"WAITING_USER", "FAILED"}:
                break
            time.sleep(0.01)

        restored = client.get(
            "/api/v1/workbench/conversations",
            params={"project_id": project["id"]},
        ).json()["items"]
        search_state = client.get(
            f"/api/v1/geo/searches/{search.search_id}",
            params={"conversation_id": conversation["id"]},
        )
        attacker = TestClient(app, base_url="http://127.0.0.1:8000")
        try:
            attacker.get("/api/v1/workbench/bootstrap")
            foreign_search = attacker.get(
                f"/api/v1/geo/searches/{search.search_id}",
                params={"conversation_id": conversation["id"]},
            )
            foreign_selection = attacker.post(
                f"/api/v1/geo/searches/{search.search_id}/selection",
                params={"conversation_id": conversation["id"]},
                json={"accession": "GSE111", "revision": 2},
                headers={"X-CSRF-Token": attacker.app.state.csrf_token},
            )
        finally:
            attacker.close()
        events = client.app.state.dependencies.workbench.list_events(conversation["id"])

    assert turn["status"] == "WAITING_USER"
    assert turn["pending_input"]["question"] == "请从 GEO 搜索结果中选择一个数据集继续。"
    assert len(search.calls) == 1
    assert search.calls[0][0].text == "AD brain RNA-seq"
    assert restored[0]["geo_search_id"] == search.search_id
    assert search_state.status_code == 200
    assert foreign_search.status_code == 404
    assert foreign_selection.status_code == 404
    assert any(event.kind == "geo.search.updated" for event in events)
