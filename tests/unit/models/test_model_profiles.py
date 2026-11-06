import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from bioagent.config import Settings
from bioagent.models.adapters import ModelAdapter, structured_options
from bioagent.models.profiles import ModelProfile, ModelSnapshot
from bioagent.models.secrets import SystemSecretStore
from bioagent.models.store import ModelProfileStore
from bioagent.workbench.store import WorkbenchStore


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def set(self, ref, value):
        self.values[ref] = value

    def get(self, ref):
        return self.values.get(ref)

    def delete(self, ref):
        self.values.pop(ref, None)


def profile(**changes):
    return ModelProfile(
        id=uuid4(),
        label="本地",
        provider="ollama",
        model="model-a",
        base_url="http://127.0.0.1:11434",
        credential_ref=None,
        structured_method="function_calling",
        thinking="default",
        revision=1,
        **changes,
    )


def settings():
    return Settings(_env_file=None, deepseek_api_key=None)


def test_snapshot_survives_profile_change():
    original = profile()
    snapshot = original.snapshot()
    changed = original.model_copy(update={"model": "model-b", "revision": 2})
    assert isinstance(snapshot, ModelSnapshot)
    assert snapshot.model == "model-a"
    assert changed.snapshot().model == "model-b"
    assert "credential_ref" not in snapshot.model_dump()
    assert "credential_ref" not in original.public_dict(credential_configured=False)
    with pytest.raises(ValidationError):
        snapshot.model = "mutate"
    with pytest.raises(ValidationError):
        original.model_copy(update={"revision": 0})


@pytest.mark.parametrize(
    "url",
    [
        "file:///local",
        "http://user:password@host",
        "https://host/?key=x",
        "https://host/#x",
        "http://",
        "https://host/\npath",
    ],
)
def test_profile_rejects_credentials_and_invalid_urls(url):
    with pytest.raises(ValueError):
        profile().model_copy(update={"base_url": url})


def test_store_revision_reopen_deletion_preserves_turn_snapshot(tmp_path):
    path = tmp_path / "wb.sqlite"
    secrets = MemorySecrets()
    with ModelProfileStore(path, settings(), secrets) as store:
        created = store.create(
            label="local", provider="ollama", model="a", base_url="http://localhost:11434"
        )
        with WorkbenchStore(path) as wb:
            chat = wb.create_conversation(wb.create_project("p").id, "chat")
            turn = wb.begin_turn(chat.id, uuid4(), "hello", created.snapshot())
        updated = store.update(created.id, expected_revision=1, model="b")
        assert updated.revision == 2
        with pytest.raises(ValueError, match="PROFILE_REVISION_CONFLICT"):
            store.update(created.id, expected_revision=1, model="c")
        store.delete(created.id, expected_revision=2)
        with pytest.raises(ValueError, match="MODEL_NOT_CONFIGURED"):
            store.get(created.id)
    with (
        ModelProfileStore(path, settings(), secrets) as store,
        pytest.raises(ValueError, match="MODEL_NOT_CONFIGURED"),
    ):
        store.get(created.id)
    with WorkbenchStore(path) as wb:
        assert wb.get_turn(turn.id).model_snapshot.model == "a"


def test_concurrent_revision_and_environment_profiles_are_read_only(tmp_path):
    path = tmp_path / "wb.sqlite"
    secrets = MemorySecrets()
    config = settings()
    config.deepseek_api_key = SecretStr("synthetic-env-value")
    with ModelProfileStore(path, config, secrets) as store:
        env = next(p for p in store.list().items if p.read_only and p.provider == "deepseek")
        assert store.request_config(env.id)[1].get_secret_value() == "synthetic-env-value"
        for action in (
            lambda: store.update(env.id, expected_revision=1, model="bad"),
            lambda: store.delete(env.id, expected_revision=1),
            lambda: store.set_credential(env.id, SecretStr("synthetic-value")),
            lambda: store.delete_credential(env.id),
        ):
            with pytest.raises(ValueError, match="PROFILE_READ_ONLY"):
                action()
        created = store.create(
            label="local", provider="ollama", model="a", base_url="http://localhost:11434"
        )

    def update(i):
        with ModelProfileStore(path, config, secrets) as store:
            try:
                return store.update(created.id, expected_revision=1, model=str(i)).revision
            except ValueError as exc:
                return str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(update, range(4)))
    assert results.count(2) == 1
    assert results.count("PROFILE_REVISION_CONFLICT") == 3
    assert b"synthetic-env-value" not in path.read_bytes()


@pytest.mark.parametrize(
    "provider,method",
    [
        ("deepseek", "function_calling"),
        ("ollama", "function_calling"),
        ("openai_compatible", "function_calling"),
        ("openai_compatible", "json_schema"),
    ],
)
def test_probe_uses_fixed_schema_and_fresh_credentials(tmp_path, monkeypatch, provider, method):
    secrets = MemorySecrets()
    clients = []

    def constructor(**kwargs):
        client = Mock()
        client.with_structured_output.return_value.ainvoke = AsyncMock(return_value={"ok": True})
        clients.append((client, kwargs))
        return client

    monkeypatch.setattr("bioagent.models.adapters.ChatOpenAI", constructor)
    monkeypatch.setattr("bioagent.models.adapters.ChatOllama", constructor)
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), secrets) as store:
        created = store.create(
            label="test",
            provider=provider,
            model="model",
            base_url="http://localhost:11434",
            structured_method=method,
        )
        store.set_credential(created.id, SecretStr("synthetic-first"))
        adapter = ModelAdapter(store)
        assert asyncio.run(adapter.probe(created.id)).ok
        store.set_credential(created.id, SecretStr("synthetic-second"))
        assert asyncio.run(adapter.probe(created.id)).ok
        assert len(clients) == 2
        for client, kwargs in clients:
            assert client.with_structured_output.call_args.kwargs == {"method": method}
            prompt = client.with_structured_output.return_value.ainvoke.call_args.args[0]
            assert "synthetic" not in str(prompt)
            assert "ok" in str(prompt)
            if provider == "deepseek":
                assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
            else:
                assert "extra_body" not in kwargs
        if provider != "ollama":
            assert clients[0][1]["api_key"].get_secret_value() == "synthetic-first"
            assert clients[1][1]["api_key"].get_secret_value() == "synthetic-second"
            assert clients[0][1]["timeout"] == 60 and clients[0][1]["max_retries"] == 0
        assert "credential_ref" not in json.dumps(created.snapshot().model_dump())


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "MODEL_AUTH_FAILED"),
        (429, "MODEL_RATE_LIMITED"),
        (400, "MODEL_PROTOCOL_UNSUPPORTED"),
        (500, "MODEL_SERVER_ERROR"),
        (402, "MODEL_PAYMENT_REQUIRED"),
        (404, "MODEL_NOT_FOUND"),
    ],
)
def test_probe_errors_are_whitelisted_without_fallback(tmp_path, monkeypatch, status, code):
    request = httpx.Request("POST", "https://mock.invalid")
    error = httpx.HTTPStatusError(
        "synthetic-private-body", request=request, response=httpx.Response(status, request=request)
    )
    client = Mock()
    client.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=error)
    constructor = Mock(return_value=client)
    monkeypatch.setattr("bioagent.models.adapters.ChatOllama", constructor)
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), MemorySecrets()) as store:
        created = store.create(
            label="test", provider="ollama", model="model", base_url="http://localhost:11434"
        )
        result = asyncio.run(ModelAdapter(store).probe(created.id))
        assert result.code == code and not result.ok
        assert "synthetic-private-body" not in result.model_dump_json()
        assert constructor.call_count == 1
        assert client.with_structured_output.return_value.ainvoke.call_count == 1


@pytest.mark.parametrize(
    "output,code",
    [
        ({"ok": False}, "MODEL_OUTPUT_INVALID"),
        ({"ok": True, "extra": "x"}, "MODEL_OUTPUT_INVALID"),
        (TimeoutError("synthetic-private"), "MODEL_TIMEOUT"),
    ],
)
def test_probe_timeout_and_invalid_output(tmp_path, monkeypatch, output, code):
    client = Mock()
    invoke = (
        AsyncMock(side_effect=output)
        if isinstance(output, Exception)
        else AsyncMock(return_value=output)
    )
    client.with_structured_output.return_value.ainvoke = invoke
    monkeypatch.setattr("bioagent.models.adapters.ChatOllama", Mock(return_value=client))
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), MemorySecrets()) as store:
        created = store.create(
            label="test", provider="ollama", model="model", base_url="http://localhost:11434"
        )
        assert asyncio.run(ModelAdapter(store).probe(created.id)).code == code


@pytest.mark.parametrize(
    "error,expected",
    [
        (ValueError("MODEL_ACTION_INVALID"), "MODEL_ACTION_INVALID"),
        (ValueError("MODEL_ACTION_INVALID synthetic-private"), "MODEL_INTERNAL_ERROR"),
        (RuntimeError("synthetic-private C:/secret sk-test"), "MODEL_INTERNAL_ERROR"),
        (httpx.ConnectError("synthetic-private"), "MODEL_CONNECTION_FAILED"),
    ],
)
def test_error_classification_is_exact_and_private(error, expected):
    from bioagent.models.adapters import error_code

    assert error_code(error) == expected


def test_diagnostic_drops_untrusted_request_id_and_exception_names():
    from bioagent.models.diagnostics import diagnose

    request = httpx.Request("POST", "https://private.invalid")
    error = httpx.HTTPStatusError(
        "synthetic-private",
        request=request,
        response=httpx.Response(402, headers={"x-request-id": "sk-private"}, request=request),
    )
    diagnostic = diagnose(error, "generating")
    assert diagnostic.http_status == 402
    assert diagnostic.request_id is None
    assert "private" not in diagnostic.model_dump_json()

    class PrivateException(RuntimeError):
        pass

    assert diagnose(PrivateException("secret"), "generating").exception_category == "internal"


def test_missing_key_and_deleted_profile_never_construct_client(tmp_path, monkeypatch):
    constructor = Mock(side_effect=AssertionError("must not call"))
    monkeypatch.setattr("bioagent.models.adapters.ChatOpenAI", constructor)
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), MemorySecrets()) as store:
        created = store.create(
            label="test", provider="deepseek", model="model", base_url="https://mock.invalid"
        )
        assert asyncio.run(ModelAdapter(store).probe(created.id)).code == "MODEL_NOT_CONFIGURED"
        store.delete(created.id, expected_revision=1)
        assert asyncio.run(ModelAdapter(store).probe(created.id)).code == "MODEL_NOT_CONFIGURED"
    constructor.assert_not_called()


def test_unavailable_or_plaintext_keyring_never_writes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    backend = Mock()
    monkeypatch.setattr("keyring.get_keyring", lambda: backend)
    store = SystemSecretStore()
    for action in (
        lambda: store.set("keyring:" + str(uuid4()), SecretStr("synthetic-private")),
        lambda: store.get("keyring:" + str(uuid4())),
        lambda: store.delete("keyring:" + str(uuid4())),
    ):
        with pytest.raises(ValueError, match="SECRET_STORE_UNAVAILABLE"):
            action()
    assert list(tmp_path.iterdir()) == []
    backend.set_password.assert_not_called()


def test_structured_options_preserve_provider_contract():
    assert structured_options("deepseek", "json_schema") == {
        "method": "function_calling",
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    assert structured_options("ollama", "json_schema") == {"method": "function_calling"}


def test_profiles_without_credentials_do_not_touch_keyring_and_delete_cleans_reference(tmp_path):
    secrets = MemorySecrets()
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), secrets) as store:
        created = store.create(
            label="local", provider="ollama", model="model", base_url="http://localhost:11434"
        )
        assert created.credential_ref is None
        saved = store.set_credential(created.id, SecretStr("synthetic-deletable"))
        assert saved.credential_ref and secrets.get(saved.credential_ref)
        store.delete(created.id, expected_revision=1)
        assert secrets.values == {}


def test_system_backend_uses_isolated_service_and_sanitizes_failure(monkeypatch):
    # A concrete fake type satisfies the OS-backend allowlist without OS access.
    fake_type = type("WinVaultKeyring", (), {"__module__": "keyring.backends.Windows"})
    fake = fake_type()
    fake.get_password = Mock(return_value="synthetic-os-value")
    fake.set_password = Mock()
    fake.delete_password = Mock()
    monkeypatch.setattr("keyring.get_keyring", lambda: fake)
    store = SystemSecretStore()
    ref = "keyring:" + str(uuid4())
    store.set(ref, SecretStr("synthetic-os-value"))
    assert store.get(ref).get_secret_value() == "synthetic-os-value"
    store.delete(ref)
    fake.set_password.assert_called_once_with("bioagent.model-profiles", ref, "synthetic-os-value")
    fake.delete_password.assert_called_once_with("bioagent.model-profiles", ref)
    fake.get_password.side_effect = RuntimeError("synthetic-private-error")
    with pytest.raises(ValueError, match="^SECRET_STORE_UNAVAILABLE$"):
        store.get(ref)


def test_probe_has_total_deadline_and_cancels_slow_response(tmp_path, monkeypatch):
    timeout = asyncio.timeout
    requested = []
    cancelled = []
    deadlines = []

    def bounded(seconds):
        requested.append(seconds)
        deadline = timeout(None)
        deadlines.append(deadline)
        return deadline

    async def slow(_):
        try:
            deadlines[0].reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    client = Mock()
    client.with_structured_output.return_value.ainvoke = slow
    monkeypatch.setattr("bioagent.models.adapters.ChatOllama", Mock(return_value=client))
    monkeypatch.setattr("bioagent.models.adapters.asyncio.timeout", bounded)
    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), MemorySecrets()) as store:
        created = store.create(
            label="local", provider="ollama", model="model", base_url="http://localhost:11434"
        )
        result = asyncio.run(ModelAdapter(store).probe(created.id))
        assert result.code == "MODEL_TIMEOUT"
        assert requested == [60] and cancelled == [True]


@pytest.mark.parametrize("method", ["function_calling", "json_schema"])
@pytest.mark.parametrize("valid", [True, False])
def test_actual_sdk_with_mock_transport_validates_output(
    tmp_path, monkeypatch, caplog, method, valid
):
    from langchain_openai import ChatOpenAI

    requests = []
    secret = "synthetic-transport-value"

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        content = '{"ok":true}' if valid else "not-json"
        message = {"role": "assistant", "content": content}
        if method == "function_calling":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "mock-call",
                        "type": "function",
                        "function": {"name": "ProbeOK", "arguments": content},
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "mock-completion",
                "object": "chat.completion",
                "created": 0,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if method == "function_calling" else "stop",
                    }
                ],
            },
        )

    async def run(store, identity):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:

            def constructor(**kwargs):
                return ChatOpenAI(**kwargs, http_async_client=http)

            monkeypatch.setattr("bioagent.models.adapters.ChatOpenAI", constructor)
            return await ModelAdapter(store).probe(identity)

    with ModelProfileStore(tmp_path / "wb.sqlite", settings(), MemorySecrets()) as store:
        created = store.create(
            label="mock",
            provider="openai_compatible",
            model="mock-model",
            base_url="https://mock.invalid",
            structured_method=method,
        )
        store.set_credential(created.id, SecretStr(secret))
        result = asyncio.run(run(store, created.id))
        assert result.code == ("OK" if valid else "MODEL_OUTPUT_INVALID")
    assert len(requests) == 1
    assert "thinking" not in requests[0]
    assert secret not in json.dumps(requests) + result.model_dump_json() + caplog.text
