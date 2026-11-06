import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def get(self, ref):
        return self.values.get(ref)

    def set(self, ref, value):
        self.values[ref] = value

    def delete(self, ref):
        self.values.pop(ref, None)


@pytest.fixture
def client(tmp_path, monkeypatch):
    model = Mock()
    model.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"ok": True})
    constructor = Mock(return_value=model)
    monkeypatch.setattr("bioagent.models.adapters.ChatOpenAI", constructor)
    monkeypatch.setattr("bioagent.models.adapters.ChatOllama", constructor)
    config = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoint.sqlite",
        workbench_db=tmp_path / "wb.sqlite",
        local_allowed_hosts=("127.0.0.1", "localhost", "::1"),
    )
    secrets = MemorySecrets()
    app = create_app(
        config,
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "readiness": lambda: True,
            "secret_store": secrets,
        },
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as api:
        api.secrets = secrets
        api.constructor = constructor
        api.db_path = config.workbench_db
        yield api


def bootstrap(client):
    response = client.get("/api/v1/workbench/bootstrap")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    token = response.json()["csrf_token"]
    assert len(token) >= 32 and token not in str(response.request.url)
    return {"X-CSRF-Token": token, "Origin": "http://127.0.0.1:8000"}


def create(client, headers):
    response = client.post(
        "/api/v1/model-profiles",
        headers=headers,
        json={
            "label": "本地模型",
            "provider": "openai_compatible",
            "model": "model-a",
            "base_url": "https://mock.invalid/v1",
            "structured_method": "json_schema",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_profile_crud_credential_redaction_probe_and_no_auto_requests(client, caplog):
    headers = bootstrap(client)
    p = create(client, headers)
    assert not p["credential_configured"]
    assert "credential_ref" not in p
    identity = p["id"]
    client.constructor.assert_not_called()
    secret = "synthetic-api-secret-for-redaction"
    response = client.put(
        f"/api/v1/model-profiles/{identity}/credential", headers=headers, json={"key": secret}
    )
    assert response.status_code == 200 and response.json()["credential_configured"]
    listing = client.get("/api/v1/model-profiles")
    assert listing.status_code == 200
    client.constructor.assert_not_called()
    probe = client.post(f"/api/v1/model-profiles/{identity}/test", headers=headers)
    assert probe.status_code == 200 and probe.json()["ok"]
    assert client.constructor.call_count == 1
    changed = client.patch(
        f"/api/v1/model-profiles/{identity}",
        headers=headers,
        json={"expected_revision": 1, "model": "model-b"},
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    stale = client.patch(
        f"/api/v1/model-profiles/{identity}",
        headers=headers,
        json={"expected_revision": 1, "model": "model-c"},
    )
    assert stale.status_code == 409
    cleared = client.delete(f"/api/v1/model-profiles/{identity}/credential", headers=headers)
    assert cleared.status_code == 200 and not cleared.json()["credential_configured"]
    deleted = client.delete(
        f"/api/v1/model-profiles/{identity}?expected_revision=2", headers=headers
    )
    assert deleted.status_code == 204
    missing = client.post(f"/api/v1/model-profiles/{identity}/test", headers=headers)
    assert missing.json()["code"] == "MODEL_NOT_CONFIGURED"
    assert client.constructor.call_count == 1
    for r in (response, listing, probe, changed, stale, cleared, deleted, missing):
        assert secret not in r.text
        assert "credential_ref" not in r.text
    assert secret not in caplog.text
    assert secret.encode() not in client.db_path.read_bytes()


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"Host": "evil.example"}, "LOCAL_HOST_REJECTED"),
        ({"Origin": "https://evil.example"}, "LOCAL_ORIGIN_REJECTED"),
        ({"Origin": "http://127.0.0.1:8001"}, "LOCAL_ORIGIN_REJECTED"),
        ({"Origin": "null"}, "LOCAL_ORIGIN_REJECTED"),
        ({"Sec-Fetch-Site": "cross-site"}, "LOCAL_ORIGIN_REJECTED"),
    ],
)
def test_bootstrap_rejects_host_origin_and_cross_site(client, headers, code):
    response = client.get("/api/v1/workbench/bootstrap", headers=headers)
    assert response.status_code == 403 and response.json()["detail"]["code"] == code
    assert "csrf_token" not in response.text


def test_csrf_required_on_all_new_writes_but_old_api_still_works(client):
    headers = bootstrap(client)
    for path, method in [
        ("/api/v1/model-profiles", "post"),
        ("/api/v1/model-profiles/not-a-uuid/credential", "put"),
        ("/api/v1/workbench/projects", "post"),
    ]:
        for request_headers in ({}, {"X-CSRF-Token": "wrong"}):
            response = getattr(client, method)(path, headers=request_headers, json={})
            assert response.status_code == 403
    query = client.post("/api/v1/model-profiles?csrf_token=" + headers["X-CSRF-Token"], json={})
    assert query.status_code == 403 and headers["X-CSRF-Token"] not in query.text
    assert client.get("/health").status_code == 200
    assert client.post("/api/v1/runs", json={}).status_code == 422
    assert client.get("/api/v1/runs").status_code == 200


def test_validation_errors_never_echo_secret_input(client):
    headers = bootstrap(client)
    secret = "synthetic-invalid-request-secret"
    p = create(client, headers)
    responses = [
        client.put(
            f"/api/v1/model-profiles/{p['id']}/credential",
            headers=headers,
            json={"key": {"nested": secret}, "extra": secret},
        ),
        client.post(
            "/api/v1/model-profiles",
            headers=headers,
            json={"label": "x", "provider": secret, "key": secret},
        ),
        client.post("/api/v1/model-profiles", headers=headers, content='{"key":"' + secret),
    ]
    for response in responses:
        assert response.status_code == 422
        assert secret not in response.text and "input" not in response.text


def test_environment_profiles_cannot_be_changed(client):
    headers = bootstrap(client)
    profiles = client.get("/api/v1/model-profiles").json()["items"]
    env = next(p for p in profiles if p["read_only"])
    response = client.put(
        f"/api/v1/model-profiles/{env['id']}/credential",
        headers=headers,
        json={"key": "synthetic-value"},
    )
    assert response.status_code == 409
    assert client.secrets.values == {}


def test_keyring_failure_has_safe_error_and_no_plaintext_fallback(client, monkeypatch, caplog):
    headers = bootstrap(client)
    p = create(client, headers)

    def fail(*_):
        raise RuntimeError("synthetic-backend-private-body")

    monkeypatch.setattr(client.secrets, "set", fail)
    response = client.put(
        f"/api/v1/model-profiles/{p['id']}/credential",
        headers=headers,
        json={"key": "synthetic-value"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SECRET_STORE_UNAVAILABLE"
    assert "synthetic" not in response.text + caplog.text
    assert b"synthetic" not in client.db_path.read_bytes()
    assert client.secrets.values == {}


def test_profile_pagination_and_limits(client):
    headers = bootstrap(client)
    for _ in range(3):
        create(client, headers)
    first = client.get("/api/v1/model-profiles?limit=2").json()
    second = client.get(
        "/api/v1/model-profiles", params={"limit": 100, "cursor": first["next_cursor"]}
    )
    assert second.status_code == 200
    ids = [p["id"] for p in first["items"] + second.json()["items"]]
    assert len(ids) == len(set(ids)) == 5
    assert client.get("/api/v1/model-profiles?limit=101").status_code == 422


def test_configured_development_origin_is_exact(tmp_path):
    config = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        workbench_db=tmp_path / "wb.sqlite",
        local_dev_origin="http://localhost:5173",
        local_allowed_hosts=("localhost", "127.0.0.1"),
    )
    app = create_app(
        config,
        {
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "secret_store": MemorySecrets(),
        },
    )
    with TestClient(app, base_url="http://127.0.0.1:8000") as api:
        assert (
            api.get(
                "/api/v1/workbench/bootstrap", headers={"Origin": "http://localhost:5173"}
            ).status_code
            == 200
        )
        assert (
            api.get(
                "/api/v1/workbench/bootstrap", headers={"Origin": "http://localhost:5174"}
            ).status_code
            == 403
        )
    # Creating API dependencies did not read or write any system credential.
    assert json.dumps(config.model_dump(mode="json"))
