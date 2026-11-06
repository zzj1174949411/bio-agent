import subprocess
import sys
import textwrap
from uuid import uuid4

from fastapi.testclient import TestClient

from bioagent.api.app import create_app
from bioagent.config import Settings


def test_retrieval_api_optional_boundary_and_openapi(tmp_path):
    settings = Settings(
        _env_file=None,
        deepseek_api_key=None,
        data_dir=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        checkpoint_db=tmp_path / "cp.sqlite",
        workbench_db=tmp_path / "wb.sqlite",
        knowledge_embedding_models_dir=tmp_path / "missing",
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        prefix = "/api/v1/knowledge"
        readiness = client.get(prefix + "/retrieval/readiness")
        assert readiness.status_code == 200
        assert not readiness.json()["ready"]
        payload = {"query": "基因表达", "knowledge_base_ids": [str(uuid4())], "top_k": 3}
        assert client.post(prefix + "/search", json=payload).status_code == 403
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert (
            client.post(
                prefix + "/search", json=payload, headers={"origin": "https://evil.test"}
            ).status_code
            == 403
        )
        base = client.post(prefix + "/bases", json={"name": "empty"}).json()
        payload["knowledge_base_ids"] = [base["id"]]
        response = client.post(prefix + "/search", json=payload)
        assert response.status_code == 200 and response.json()["code"] == "NO_EVIDENCE"
        assert (
            client.post(prefix + "/search", json={**payload, "path": "C:/secret"}).status_code
            == 422
        )
        assert client.get("/health").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
        assert all(
            prefix + route in paths
            for route in [
                "/search",
                "/ask",
                "/asks/{ask_id}/events",
                "/documents/{document_id}/index",
            ]
        )


def test_application_boots_with_optional_rag_imports_blocked(tmp_path):
    code = textwrap.dedent("""
        import importlib.abc
        import importlib.metadata
        import sys
        from pathlib import Path
        class BlockOptional(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in {'torch', 'transformers', 'qdrant_client', 'docling'}:
                    raise ImportError('optional package deliberately unavailable')
        sys.meta_path.insert(0, BlockOptional())
        original = importlib.metadata.version
        def version(name):
            if name in {'torch', 'transformers', 'qdrant-client', 'docling'}:
                raise importlib.metadata.PackageNotFoundError(name)
            return original(name)
        importlib.metadata.version = version
        from bioagent.api.app import create_app
        from bioagent.config import Settings
        from fastapi.testclient import TestClient
        root = Path(sys.argv[1])
        settings = Settings(_env_file=None, deepseek_api_key=None, data_dir=root/'data',
            runs_dir=root/'runs', checkpoint_db=root/'cp.sqlite', workbench_db=root/'wb.sqlite')
        with TestClient(create_app(settings), base_url='http://localhost') as client:
            assert client.get('/health').status_code == 200
            ready = client.get('/api/v1/knowledge/retrieval/readiness').json()
            assert ready['code'] == 'RAG_DEPENDENCY_MISSING' and not ready['ready']
        assert not {'torch', 'transformers', 'qdrant_client', 'docling'}.intersection(sys.modules)
    """)
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
