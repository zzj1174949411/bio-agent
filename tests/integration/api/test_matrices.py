import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bioagent.services.datasets import DatasetImportError
from bioagent.services.matrices import MatrixConfirmation, MatrixService

sys.path.insert(0, str(Path(__file__).parents[2] / "e2e"))
from test_matrix_workflow import Planner, confirmation, setup  # noqa: E402
from test_matrix_workflow import make_app as make_workflow_app  # noqa: E402


def make_app(tmp_path):
    """Keep API behavior tests independent of spawn startup speed on Windows.

    Production and shared e2e defaults stay unchanged. The dedicated parse
    deadline test below constructs its own 0.001-second limits.
    """
    app = make_workflow_app(tmp_path)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application) as state:
            deps = application.state.dependencies
            deps.parse_timeout_seconds = 30.0
            importer = deps.dataset_import_service
            importer.upload_limits = replace(importer.upload_limits, parse_timeout_seconds=30.0)
            yield state

    app.router.lifespan_context = lifespan
    return app


def test_matrix_preview_confirmation_and_restart(tmp_path):
    service = MatrixService(tmp_path / "matrix.sqlite")
    draft = service.upload("chat", b"gene,A,B,C,D\ng1,10,20,30,40\n", ".csv")
    assert draft["headers"] == ["gene", "A", "B", "C", "D"]
    assert (
        MatrixService(tmp_path / "matrix.sqlite").get("chat", draft["id"])["sha256"]
        == draft["sha256"]
    )


def test_matrix_upload_above_chat_json_limit_keeps_upload_boundary(tmp_path):
    raw = b"gene,A,B,C,D\n" + b"".join(f"gene{i},100,200,300,400\n".encode() for i in range(3000))
    assert len(raw) > 32 * 1024
    with TestClient(make_app(tmp_path), base_url="http://localhost") as client:
        prefix = setup(client)
        response = client.post(prefix, files={"file": ("real-sized.csv", raw)})
        assert response.status_code == 201, response.text
        assert response.json()["row_count"] == 3000
        assert (
            client.post(
                prefix, content=b"x" * (33 * 1024), headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        assert (
            client.post(
                prefix + "/" + response.json()["id"] + "/confirm", content=b"x" * (33 * 1024)
            ).status_code
            == 413
        )
        assert (
            client.post(
                prefix, files={"file": ("m.csv", raw)}, headers={"X-CSRF-Token": "bad"}
            ).status_code
            == 403
        )


@pytest.mark.parametrize("bad", ["NA", "-1", "1.5", "Inf", "__import__('os')"])
def test_invalid_counts_are_not_coerced(tmp_path, bad):
    store = MatrixService(tmp_path / "db")
    payload = confirmation()
    payload.update(
        sample_columns=[1, 2, 3, 4], groups={"1": "AD", "2": "AD", "3": "Control", "4": "Control"}
    )
    with pytest.raises(DatasetImportError):
        store.normalize(
            f"gene,A,B,C,D\ng1,{bad},1,2,3\n".encode(), ".csv", MatrixConfirmation(**payload)
        )


def test_http_owner_revision_raw_idempotency_and_restore(tmp_path):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        prefix = setup(client)
        raw = (Path(__file__).parents[2] / "fixtures/counts_deseq2.csv").read_bytes()
        assert (
            client.post(
                prefix, files={"file": ("m.csv", raw)}, headers={"X-CSRF-Token": "bad"}
            ).status_code
            == 403
        )
        draft = client.post(prefix, files={"file": ("m.csv", raw)}).json()
        target = prefix + "/" + draft["id"] + "/confirm"
        body = confirmation()
        assert client.post(target, json={**body, "data_type": "TPM"}).status_code == 422
        assert client.post(target, json={**body, "revision": 9}).status_code == 409
        result = client.post(target, json=body)
        assert result.status_code == 200, result.text
        assert client.post(target, json=body).json()["run_id"] == result.json()["run_id"]
        reordered = {**body, "groups": dict(reversed(list(body["groups"].items())))}
        assert client.post(target, json=reordered).json()["run_id"] == result.json()["run_id"]
        assert client.post(target, json={**body, "numerator": "Control"}).status_code == 409
        assert client.get(prefix).json()["status"] == "CONFIRMED"
        cookies = dict(client.cookies)
        other = setup(client)
        assert client.get(other + "/" + draft["id"]).status_code == 422
        client.cookies.clear()
        assert client.get(prefix).status_code == 403
    with TestClient(make_app(tmp_path), base_url="http://localhost") as client:
        # Missing owner never gains access after process recovery.
        assert client.get(prefix).status_code == 403
        client.cookies.update(cookies)
        restored = client.get(prefix)
        assert restored.json()["dataset_id"] == result.json()["dataset_id"]


def test_failed_planning_has_durable_terminal_state(tmp_path, monkeypatch):
    def broken(self, **kwargs):
        raise RuntimeError("synthetic planner failure")

    monkeypatch.setattr(Planner, "plan", broken)
    with TestClient(
        make_app(tmp_path), base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        prefix = setup(client)
        raw = (Path(__file__).parents[2] / "fixtures/counts_deseq2.csv").read_bytes()
        draft = client.post(prefix, files={"file": ("m.csv", raw)}).json()
        target = prefix + "/" + draft["id"] + "/confirm"
        body = confirmation()
        response = client.post(target, json=body)
        assert response.status_code >= 400
        restored = client.get(prefix).json()
        assert restored["status"] == "FAILED", restored
        assert restored["error_code"] == "MATRIX_PLANNING_FAILED"
        assert (
            client.get("/api/v1/workbench/turns/" + restored["turn_id"]).json()["status"]
            == "FAILED"
        )
        cookies = dict(client.cookies)
        run_count = len(list((tmp_path / "runs").iterdir()))
    with TestClient(make_app(tmp_path), base_url="http://localhost") as client:
        client.cookies.update(cookies)
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert client.get(prefix).json()["status"] == "FAILED"
        assert client.post(target, json=body).status_code == 409
        assert len(list((tmp_path / "runs").iterdir())) == run_count


def test_restart_marks_abandoned_planning_failed_without_retry(tmp_path):
    import json
    from uuid import UUID, uuid4

    from bioagent.workbench.models import TurnStatus

    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client:
        prefix = setup(client)
        chat = UUID(prefix.split("/")[-2])
        store = MatrixService(tmp_path / "data/matrices.sqlite")
        draft = store.upload(str(chat), b"gene,A,B,C,D\ng1,1,2,3,4\n", ".csv")
        turn = app.state.dependencies.workbench.begin_turn(chat, uuid4(), "goal", None)
        app.state.dependencies.workbench.update_turn(turn.id, TurnStatus.RUNNING)
        with store.db() as db:
            _, record = store.read(db, str(chat), draft["id"])
            body = confirmation()
            record.update(
                status="PLANNING",
                turn_id=str(turn.id),
                confirmation_hash="fixed",
                confirmation=body,
            )
            db.execute("UPDATE matrices SET record=? WHERE id=?", (json.dumps(record), draft["id"]))
        cookies = dict(client.cookies)
        run_count = len(list((tmp_path / "runs").iterdir()))
    with TestClient(make_app(tmp_path), base_url="http://localhost") as client:
        client.cookies.update(cookies)
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        record = client.get(prefix).json()
        assert record["status"] == "FAILED"
        assert record["error_code"] == "MATRIX_PLANNING_INTERRUPTED"
        assert client.get("/api/v1/workbench/turns/" + str(turn.id)).json()["status"] == "FAILED"
        assert client.get(prefix).json()["status"] == "FAILED"
        assert client.post(prefix + "/" + draft["id"] + "/confirm", json=body).status_code == 409
        assert len(list((tmp_path / "runs").iterdir())) == run_count


@pytest.mark.parametrize("change", ["duplicate_gene", "duplicate_sample", "too_few", "transpose"])
def test_columns_groups_and_transpose(tmp_path, change):
    store = MatrixService(tmp_path / "db")
    body = confirmation()
    body.update(
        sample_columns=[1, 2, 3, 4], groups={"1": "AD", "2": "AD", "3": "Control", "4": "Control"}
    )
    raw = b"gene,A,B,C,D\ng1,1,2,3,4\ng2,5,6,7,8\n"
    if change == "transpose":
        body["direction"] = "samples_rows"
        counts, metadata = store.normalize(
            b"sample,g1,g2\nA,1,5\nB,2,6\nC,3,7\nD,4,8\n", ".csv", MatrixConfirmation(**body)
        )
        assert counts.startswith(b"feature_id,A,B,C,D") and b"A,AD" in metadata
        return
    if change == "duplicate_gene":
        raw = raw.replace(b"g2,", b"g1,")
    if change == "duplicate_sample":
        raw = raw.replace(b"gene,A,B", b"gene,A,A")
    if change == "too_few":
        body["groups"] = {"1": "AD", "2": "Control", "3": "Control", "4": "Control"}
    with pytest.raises(DatasetImportError):
        store.normalize(raw, ".csv", MatrixConfirmation(**body))


def test_parse_worker_has_real_timeout(tmp_path):
    from types import SimpleNamespace

    from bioagent.services.datasets import ImportLimits

    service = MatrixService(
        tmp_path / "db", SimpleNamespace(upload_limits=ImportLimits(10000, 100, 100, 0.001))
    )
    with pytest.raises(DatasetImportError, match="MATRIX_PARSE_TIMEOUT"):
        service.upload("chat", b"gene,A\ng1,1\n", ".csv")


def test_upload_parsing_keeps_health_and_cancel_responsive(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from uuid import UUID, uuid4

    from bioagent.workbench.models import TurnStatus

    entered, release = Event(), Event()

    def slow_rows(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return [["gene", "A", "B", "C", "D"], ["g1", "1", "2", "3", "4"]]

    monkeypatch.setattr(MatrixService, "rows", slow_rows)
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client, ThreadPoolExecutor(3) as pool:
        prefix = setup(client)
        chat = UUID(prefix.split("/")[-2])
        turn = app.state.dependencies.workbench.begin_turn(chat, uuid4(), "slow upload", None)
        app.state.dependencies.workbench.update_turn(turn.id, TurnStatus.RUNNING)
        uploading = pool.submit(client.post, prefix, files={"file": ("m.csv", b"ignored")})
        try:
            assert entered.wait(5)
            health = pool.submit(client.get, "/health")
            cancel = pool.submit(client.post, f"/api/v1/workbench/turns/{turn.id}/cancel")
            assert health.result(timeout=1).status_code == 200
            assert cancel.result(timeout=1).json()["status"] == "CANCELLED"
            assert not uploading.done()
        finally:
            release.set()
        assert uploading.result(timeout=5).status_code == 201


def test_cancel_during_matrix_planning_discards_late_approval(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from uuid import UUID

    entered, release = Event(), Event()
    original = Planner.plan

    def delayed(self, **kwargs):
        entered.set()
        assert release.wait(15)
        return original(self, **kwargs)

    monkeypatch.setattr(Planner, "plan", delayed)
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client, ThreadPoolExecutor(1) as pool:
        prefix = setup(client)
        raw = (Path(__file__).parents[2] / "fixtures/counts_deseq2.csv").read_bytes()
        draft = client.post(prefix, files={"file": ("m.csv", raw)}).json()
        confirming = pool.submit(
            client.post, prefix + "/" + draft["id"] + "/confirm", json=confirmation()
        )
        try:
            assert entered.wait(30), (
                confirming.result().text if confirming.done() else "planner not reached"
            )
            turn = app.state.dependencies.workbench.active_turn(UUID(prefix.split("/")[-2]))
            assert turn is not None
            cancelled = client.post(f"/api/v1/workbench/turns/{turn.id}/cancel")
            assert cancelled.json()["status"] == "CANCELLED"
        finally:
            release.set()
        assert confirming.result(timeout=10).status_code == 200
        record = client.get(prefix).json()
        assert record["status"] == "CANCELLED", record
        saved_turn = client.get(f"/api/v1/workbench/turns/{turn.id}").json()
        assert saved_turn["status"] == "CANCELLED" and saved_turn["run_id"] is None
        messages = app.state.dependencies.workbench.list_messages(turn.conversation_id).items
        assert not any("请核对" in m.content for m in messages if m.turn_id == turn.id)
        run_ids = [p.name for p in (tmp_path / "runs").iterdir() if p.is_dir()]
        assert len(run_ids) == 1
        late_run = run_ids[0]
        assert client.get(f"/api/v1/runs/{late_run}").json()["status"] == "CANCELLED"
        assert (
            client.post(
                f"/api/v1/runs/{late_run}/approval", json={"action": "approve", "plan_revision": 1}
            ).status_code
            == 409
        )
        assert not list((tmp_path / "runs" / late_run / "attempts").glob("*"))
        cookies = dict(client.cookies)
    with TestClient(make_app(tmp_path), base_url="http://localhost") as client:
        client.cookies.update(cookies)
        client.headers["X-CSRF-Token"] = client.get("/api/v1/workbench/bootstrap").json()[
            "csrf_token"
        ]
        assert client.get(prefix).json()["status"] == "CANCELLED"
        assert client.get(f"/api/v1/runs/{late_run}").json()["status"] == "CANCELLED"
        assert (
            client.post(
                f"/api/v1/runs/{late_run}/approval", json={"action": "approve", "plan_revision": 1}
            ).status_code
            == 409
        )


def test_matrix_publication_serializes_cancel_at_the_index_write(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from uuid import UUID

    entered, release, cancelling = Event(), Event(), Event()
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost") as client, ThreadPoolExecutor(2) as pool:
        prefix = setup(client)
        deps = app.state.dependencies
        original = deps.run_repository.write

        def paused_write(run_id, state):
            if state["status"] == "AWAITING_APPROVAL":
                entered.set()
                assert release.wait(10)
            return original(run_id, state)

        monkeypatch.setattr(deps.run_repository, "write", paused_write)
        raw = (Path(__file__).parents[2] / "fixtures/counts_deseq2.csv").read_bytes()
        draft = client.post(prefix, files={"file": ("m.csv", raw)}).json()
        confirming = pool.submit(
            client.post, prefix + "/" + draft["id"] + "/confirm", json=confirmation()
        )

        def cancel():
            cancelling.set()
            return deps.workbench.cancel_turn(UUID(turn_id))

        try:
            # Get the turn before publication takes its transaction lock.
            with MatrixService(tmp_path / "data/matrices.sqlite").db() as db:
                import json

                deadline = monotonic() + 30
                while True:
                    row = db.execute(
                        "SELECT record FROM matrices WHERE id=?", (draft["id"],)
                    ).fetchone()
                    record = json.loads(row[0])
                    if record.get("turn_id") or monotonic() > deadline:
                        break
                    sleep(0.02)
            turn_id = record["turn_id"]
            assert entered.wait(30)
            cancellation = pool.submit(cancel)
            assert cancelling.wait(2)
            assert not cancellation.done()
            with pytest.raises(TimeoutError):
                cancellation.result(timeout=0.1)
        finally:
            release.set()
        result = confirming.result(timeout=10)
        assert result.status_code == 200 and result.json()["status"] == "CONFIRMED"
        assert cancellation.result(timeout=5).status.value == "CANCELLED"


def test_matrix_publication_failure_revokes_public_approval(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        prefix = setup(client)
        deps = app.state.dependencies
        raw = (Path(__file__).parents[2] / "fixtures/counts_deseq2.csv").read_bytes()
        uploaded = client.post(prefix, files={"file": ("m.csv", raw)})
        assert uploaded.status_code == 201, (uploaded.status_code, uploaded.text)
        draft = uploaded.json()
        original = deps.workbench._insert_message
        injected = []

        def broken(db, message):
            if "请核对并批准" in message.content:
                injected.append(message.turn_id)
                raise RuntimeError("synthetic approval publication failure")
            return original(db, message)

        monkeypatch.setattr(deps.workbench, "_insert_message", broken)
        response = client.post(prefix + "/" + draft["id"] + "/confirm", json=confirmation())
        diagnostic = f"confirmation status={response.status_code}; body={response.text}"
        assert len(injected) == 1, f"publication fault was not reached exactly once; {diagnostic}"
        assert response.status_code == 500, diagnostic
        record_response = client.get(prefix)
        assert record_response.status_code == 200, (
            record_response.status_code, record_response.text
        )
        record = record_response.json()
        assert record["status"] == "FAILED", (record, diagnostic)
        assert record["error_code"] == "MATRIX_PLANNING_FAILED", (record, diagnostic)
        assert record["turn_id"] == str(injected[0]), (record, diagnostic)
        run_ids = [p.name for p in (tmp_path / "runs").iterdir() if p.is_dir()]
        assert len(run_ids) == 1, (run_ids, diagnostic)
        run_id = run_ids[0]
        assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "CANCELLED"
        assert (
            client.post(
                f"/api/v1/runs/{run_id}/approval", json={"action": "approve", "plan_revision": 1}
            ).status_code
            == 409
        )
