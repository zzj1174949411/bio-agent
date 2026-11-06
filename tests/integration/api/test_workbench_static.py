from pathlib import Path

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


class MemorySecrets:
    def get(self, ref: str):
        return None

    def set(self, ref: str, value: str) -> None:
        pass

    def delete(self, ref: str) -> None:
        pass


def _app(tmp_path: Path, static_dir: Path):
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "checkpoint.sqlite",
        workbench_db=tmp_path / "workbench.sqlite",
        local_allowed_hosts=("127.0.0.1", "localhost", "::1"),
    )
    return create_app(
        settings,
        {
            "static_dir": static_dir,
            "graph": object(),
            "planner": object(),
            "executor": object(),
            "readiness": lambda: True,
            "secret_store": MemorySecrets(),
        },
    )


def test_static_root_spa_fallback_and_api_404_are_separate(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html><body>workbench</body></html>", encoding="utf-8")
    (static / "assets" / "app-a1b2c3.js").write_text("console.log('ok')", encoding="utf-8")
    with TestClient(_app(tmp_path, static)) as client:
        root = client.get("/")
        route = client.get("/chat/demo")
        asset = client.get("/assets/app-a1b2c3.js")
        unknown = client.get("/api/v1/no-such-route")
    assert (
        root.status_code == 200
        and "workbench" in root.text
        and root.headers["cache-control"] == "no-store"
    )
    assert route.status_code == 200 and "workbench" in route.text
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "NOT_FOUND"


def test_missing_dist_returns_a_build_message(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path, tmp_path / "missing")) as client:
        response = client.get("/")
    assert response.status_code == 503
    assert "npm run build" in response.text
