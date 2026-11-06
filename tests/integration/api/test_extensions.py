from __future__ import annotations

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings
from bioagent.extensions.models import McpCallResult, McpConnection, McpTool


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, ref):
        return self.values.get(ref)

    def set(self, ref, value):
        self.values[ref] = value

    def delete(self, ref):
        self.values.pop(ref, None)


class FakeMcp:
    def __init__(self):
        self.connected = set()

    async def connect(self, config):
        self.connected.add(str(config.id))
        return McpConnection(
            server_id=config.id, revision=config.revision, protocol_version="fixture"
        )

    async def disconnect(self, identity):
        self.connected.discard(str(identity))

    async def close(self):
        self.connected.clear()

    async def list_tools(self, identity):
        if str(identity) not in self.connected:
            raise RuntimeError("not connected")
        return (
            McpTool(
                name="echo",
                description="fixture",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                annotations={"readOnlyHint": True},
            ),
        )

    async def call_tool(self, *_args, **_kwargs):
        return McpCallResult(structured_content={"ok": True})


def make_client(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        workbench_db=tmp_path / "workbench.sqlite",
        skill_root=tmp_path / "skills",
        local_allowed_hosts=("127.0.0.1", "localhost", "::1"),
    )
    secrets = MemorySecrets()
    app = create_app(
        settings,
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "readiness": lambda: True,
            "secret_store": secrets,
            "mcp_client": FakeMcp(),
        },
    )
    return TestClient(app, base_url="http://127.0.0.1:8000"), secrets, settings


def headers(client):
    token = client.get("/api/v1/workbench/bootstrap").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8000"}


def test_extensions_mcp_lifecycle_policy_and_secret_redaction(tmp_path):
    client, secrets, settings = make_client(tmp_path)
    with client:
        h = headers(client)
        created = client.post(
            "/api/v1/extensions/mcp/servers",
            headers=h,
            json={
                "label": "fixture",
                "transport": "http",
                "http": {"endpoint": "https://example.invalid/mcp"},
            },
        )
        assert created.status_code == 201, created.text
        identity = created.json()["id"]
        secret = "fixture-secret-not-in-response"
        credential = client.put(
            f"/api/v1/extensions/mcp/servers/{identity}/credential",
            headers=h,
            json={"ref": "token", "value": secret},
        )
        assert credential.status_code == 200 and secret not in credential.text
        assert any(secret not in str(value) for value in secrets.values.values())
        connected = client.post(f"/api/v1/extensions/mcp/servers/{identity}/connect", headers=h)
        assert connected.status_code == 200, connected.text
        tools = client.get("/api/v1/extensions/tools")
        assert tools.status_code == 200
        descriptor = tools.json()["items"][0]
        assert descriptor["qualified_name"].startswith("mcp.")
        assert descriptor["policy"] == "CONFIRM"
        denied = client.patch(
            f"/api/v1/extensions/tools/{descriptor['qualified_name']}",
            headers=h,
            json={"policy": "DENY"},
        )
        assert denied.status_code == 200
        assert client.get("/api/v1/extensions/tools").json()["items"][0]["policy"] == "DENY"
        assert (
            client.patch(
                f"/api/v1/extensions/mcp/servers/{identity}",
                headers=h,
                json={"expected_revision": 1, "label": "new"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/api/v1/extensions/mcp/servers/{identity}",
                headers=h,
                json={"expected_revision": 1, "label": "stale"},
            ).status_code
            == 409
        )
        assert (
            client.delete(
                f"/api/v1/extensions/mcp/servers/{identity}/credential?ref=token", headers=h
            ).status_code
            == 200
        )


def test_skill_root_rescan_enable_and_local_boundary(tmp_path):
    root = tmp_path / "skills" / "demo"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: fixture\n---\nHello", encoding="utf-8"
    )
    client, _, _ = make_client(tmp_path)
    with client:
        h = headers(client)
        assert (
            client.patch(
                "/api/v1/extensions/skill-roots", headers=h, json={"root": str(root.parent)}
            ).status_code
            == 200
        )
        scan = client.post("/api/v1/extensions/skills/rescan", headers=h)
        assert scan.status_code == 200 and len(scan.json()["items"]) == 1
        record = scan.json()["items"][0]
        assert (
            client.patch(
                f"/api/v1/extensions/skills/{record['id']}",
                headers=h,
                json={"enabled": True, "expected_hash": record["sha256"]},
            ).status_code
            == 200
        )
        detail = client.get(f"/api/v1/extensions/skills/{record['id']}")
        assert detail.status_code == 200 and detail.json()["snapshot"]["content"].endswith("Hello")
        assert client.post("/api/v1/extensions/skills/rescan", headers={}).status_code == 403


def test_extension_host_origin_csrf_and_analysis_approve_hidden(tmp_path):
    client, _, _ = make_client(tmp_path)
    with client:
        assert (
            client.patch("/api/v1/extensions/skill-roots", json={"root": str(tmp_path)}).status_code
            == 403
        )
        assert (
            client.get("/api/v1/extensions/tools", headers={"Host": "evil.example"}).status_code
            == 403
        )
        assert all(
            "analysis.approve" not in item.get("qualified_name", "")
            for item in client.get("/api/v1/extensions/tools").json()["items"]
        )
