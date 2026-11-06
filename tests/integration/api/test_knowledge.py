from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


def test_local_boundary_batch_import_and_optional_readiness(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            deepseek_api_key=None,
            data_dir=tmp_path / "data",
            runs_dir=tmp_path / "runs",
            checkpoint_db=tmp_path / "cp.sqlite",
            workbench_db=tmp_path / "wb.sqlite",
            knowledge_dir=tmp_path / "knowledge",
            knowledge_models_dir=tmp_path / "missing-models",
        )
    )
    with TestClient(app, base_url="http://localhost") as client:
        prefix = "/api/v1/knowledge"
        assert client.get(prefix + "/bases", headers={"host": "attacker.test"}).status_code == 403
        assert client.post(prefix + "/bases", json={"name": "papers"}).status_code == 403
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert (
            client.post(
                prefix + "/bases",
                json={"name": "papers"},
                headers={"origin": "https://attacker.test"},
            ).status_code
            == 403
        )
        base = client.post(prefix + "/bases", json={"name": "papers"})
        assert base.status_code == 201
        base_id = base.json()["id"]
        route = prefix + f"/bases/{base_id}/documents"
        assert client.post(route, json={"path": "C:/private.pdf"}).status_code == 422
        pdf = b"%PDF-1.7 fixture" + b" " * 65536
        response = client.post(
            route,
            files=[
                ("files", ("one.pdf", pdf, "application/pdf")),
                ("files", ("two.pdf", pdf, "application/pdf")),
            ],
        )
        assert response.status_code == 202, response.text
        values = response.json()["items"]
        assert values[1]["duplicate"]
        assert len(client.get(route).json()["items"]) == 1
        ready = client.get(prefix + "/readiness").json()
        assert not ready["ready"] and ready["code"].startswith("KNOWLEDGE_")
        assert client.get("/health").status_code == 200
        doc_id = values[0]["document"]["id"]
        assert client.get(prefix + f"/documents/{doc_id}/pdf").content == pdf
        assert client.delete(prefix + f"/bases/{base_id}").status_code == 204
        assert client.get(prefix + f"/documents/{doc_id}/pdf").status_code == 404
