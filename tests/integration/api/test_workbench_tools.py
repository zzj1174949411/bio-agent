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
