from uuid import uuid4

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


def test_wiki_local_security_preflight_and_no_automatic_calls(tmp_path):
    class NoSecrets:
        def get(self, *_):
            raise AssertionError("preflight cannot read credentials")

    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "cp.sqlite",
        workbench_db=tmp_path / "wb.sqlite",
    )
    with TestClient(
        create_app(settings, {"secret_store": NoSecrets()}), base_url="http://localhost"
    ) as client:
        root = "/api/v1/knowledge"
        missing = root + f"/bases/{uuid4()}/wiki"
        assert client.post(missing + "/preflight", json={}).status_code == 403
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        profile = client.post(
            "/api/v1/model-profiles",
            json={
                "label": "Wiki Mock",
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": "mock",
                "structured_method": "function_calling",
            },
        ).json()["id"]
        base = client.post(root + "/bases", json={"name": "empty"}).json()["id"]
        wiki = root + f"/bases/{base}/wiki"
        request = {"model_profile_id": profile, "max_calls": 1}
        assert (
            client.post(
                wiki + "/preflight", json=request, headers={"Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                wiki + "/preflight", json=request, headers={"Host": "evil.test"}
            ).status_code
            == 403
        )
        assert (
            client.post(wiki + "/preflight", json={**request, "path": "C:/private"}).status_code
            == 422
        )
        result = client.post(wiki + "/preflight", json=request)
        assert result.status_code == 200, result.text
        check = result.json()
        assert check["ready_count"] == 0 and not check["protocol_limits_verified"]
        assert client.get(wiki + "/status").json() is None
        assert client.post(wiki + "/build", json=request).status_code == 409
        assert (
            client.post(
                wiki + "/build", json={**request, "preflight_sha256": check["preflight_sha256"]}
            ).json()["detail"]["code"]
            == "WIKI_NO_EVIDENCE"
        )
        assert client.get(wiki + f"/pages/{uuid4()}").status_code == 404
        assert client.get(wiki + "/pages").json()["items"] == []
        assert client.get("/health").status_code == 200
