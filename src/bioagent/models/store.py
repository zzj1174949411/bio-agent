"""Profiles share the workbench database, with an independent versioned table."""

import base64
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import SecretStr

from bioagent.config import Settings
from bioagent.models.profiles import ModelError, ModelProfile, ModelSnapshot
from bioagent.models.secrets import SecretStore
from bioagent.workbench.models import Page
from bioagent.workbench.store import WorkbenchStore

_ENV_PROVIDERS: tuple[Literal["deepseek", "ollama"], ...] = ("deepseek", "ollama")
_ENV_IDS = {
    provider: uuid5(NAMESPACE_URL, f"bioagent:environment:{provider}")
    for provider in _ENV_PROVIDERS
}
_EDITABLE = {"label", "provider", "model", "base_url", "structured_method", "thinking"}


class ModelProfileStore:
    def __init__(self, path: Path, settings: Settings, secrets: SecretStore) -> None:
        with WorkbenchStore(path):
            pass
        self._settings = settings
        self._secrets = secrets
        self._lock = RLock()
        self._db = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
        try:
            with self._transaction() as db:
                exists = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='model_schema_version'"
                ).fetchone()
                if exists is None:
                    db.execute("CREATE TABLE model_schema_version (version INTEGER NOT NULL)")
                    db.execute("INSERT INTO model_schema_version VALUES (1)")
                    db.execute("""CREATE TABLE model_profiles (id TEXT PRIMARY KEY,
                               record TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)""")
                versions = db.execute("SELECT version FROM model_schema_version").fetchall()
                if versions != [(1,)]:
                    raise ModelError("MODEL_SCHEMA_UNSUPPORTED")
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def _environment_profiles(self) -> tuple[ModelProfile, ...]:
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        return tuple(
            ModelProfile(
                id=identity,
                label=f"Environment / {provider}",
                provider=provider,
                model=getattr(self._settings, f"{provider}_model"),
                base_url=getattr(self._settings, f"{provider}_base_url"),
                credential_ref="env:deepseek" if provider == "deepseek" else None,
                structured_method="function_calling",
                thinking="disabled" if provider == "deepseek" else "default",
                revision=1,
                read_only=True,
                created_at=epoch,
                updated_at=epoch,
            )
            for provider, identity in _ENV_IDS.items()
        )

    def get(self, identity: UUID) -> ModelProfile:
        identity = UUID(str(identity))
        for profile in self._environment_profiles():
            if profile.id == identity:
                return profile
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM model_profiles WHERE id=? AND deleted=0", (str(identity),)
            ).fetchone()
        if row is None:
            raise ModelError("MODEL_NOT_CONFIGURED")
        return ModelProfile.model_validate_json(row[0])

    def create(self, **values: object) -> ModelProfile:
        if set(values) - _EDITABLE:
            raise ModelError("PROFILE_INVALID")
        identity = uuid4()
        data: dict[str, object] = {
            "id": identity,
            "credential_ref": None,
            "revision": 1,
            "structured_method": "function_calling",
            "thinking": "default",
            **values,
        }
        profile = self._validate(data)
        with self._transaction() as db:
            db.execute(
                "INSERT INTO model_profiles (id, record) VALUES (?, ?)",
                (str(profile.id), profile.model_dump_json()),
            )
        return profile

    @staticmethod
    def _validate(data: dict[str, object]) -> ModelProfile:
        if data.get("provider") in {"deepseek", "ollama"}:
            data["structured_method"] = "function_calling"
        if data.get("provider") == "deepseek":
            data["thinking"] = "disabled"
        return ModelProfile.model_validate(data)

    @staticmethod
    def _writable(profile: ModelProfile, revision: int | None = None) -> None:
        if profile.read_only:
            raise ModelError("PROFILE_READ_ONLY")
        if revision is not None and (type(revision) is not int or revision != profile.revision):
            raise ModelError("PROFILE_REVISION_CONFLICT")

    def update(self, identity: UUID, *, expected_revision: int, **changes: object) -> ModelProfile:
        if set(changes) - _EDITABLE:
            raise ModelError("PROFILE_INVALID")
        with self._transaction() as db:
            profile = self.get(identity)
            self._writable(profile, expected_revision)
            data = profile.model_dump()
            data.update(changes)
            data.update(revision=profile.revision + 1, updated_at=datetime.now(UTC))
            updated = self._validate(data)
            db.execute(
                "UPDATE model_profiles SET record=? WHERE id=?",
                (updated.model_dump_json(), str(identity)),
            )
        return updated

    def delete(self, identity: UUID, *, expected_revision: int) -> None:
        with self._transaction() as db:
            profile = self.get(identity)
            self._writable(profile, expected_revision)
            # Deleted profiles cannot be resolved for new requests. Existing turn
            # snapshots remain in workbench tables, independent of this tombstone.
            if profile.credential_ref is not None:
                try:
                    self._secrets.delete(profile.credential_ref)
                except Exception:
                    raise ModelError("SECRET_STORE_UNAVAILABLE") from None
            db.execute("UPDATE model_profiles SET deleted=1 WHERE id=?", (str(identity),))

    def _credential(self, profile: ModelProfile) -> SecretStr | None:
        if profile.credential_ref == "env:deepseek":
            value = self._settings.deepseek_api_key
        elif profile.credential_ref is None:
            value = None
        else:
            try:
                value = self._secrets.get(profile.credential_ref)
            except Exception:
                raise ModelError("SECRET_STORE_UNAVAILABLE") from None
        return value if value is not None and value.get_secret_value().strip() else None

    def public(self, profile: ModelProfile) -> dict[str, object]:
        try:
            configured = self._credential(profile) is not None
            return profile.public_dict(credential_configured=configured)
        except ModelError:
            return {
                **profile.public_dict(credential_configured=False),
                "credential_error": "SECRET_STORE_UNAVAILABLE",
            }

    def request_config(
        self, identity: UUID, fixed: ModelSnapshot | None = None
    ) -> tuple[ModelProfile, SecretStr | None]:
        with self._lock:
            profile = self.get(identity)
            # Ollama does not use the OpenAI credential field or system keyring.
            provider = fixed.provider if fixed is not None else profile.provider
            secret = None if provider == "ollama" else self._credential(profile)
            if provider != "ollama" and secret is None:
                raise ModelError("MODEL_NOT_CONFIGURED")
            return profile, secret

    def set_credential(self, identity: UUID, value: SecretStr) -> ModelProfile:
        with self._transaction() as db:
            profile = self.get(identity)
            self._writable(profile)
            if not value.get_secret_value().strip() or len(value.get_secret_value()) > 8192:
                raise ModelError("CREDENTIAL_INVALID")
            ref = profile.credential_ref or f"keyring:{profile.id}"
            try:
                self._secrets.set(ref, value)
            except Exception:
                raise ModelError("SECRET_STORE_UNAVAILABLE") from None
            updated = profile.model_copy(update={"credential_ref": ref})
            db.execute(
                "UPDATE model_profiles SET record=? WHERE id=?",
                (updated.model_dump_json(), str(identity)),
            )
            return updated

    def delete_credential(self, identity: UUID) -> ModelProfile:
        with self._transaction() as db:
            profile = self.get(identity)
            self._writable(profile)
            if profile.credential_ref is None:
                return profile
            try:
                self._secrets.delete(profile.credential_ref)
            except Exception:
                raise ModelError("SECRET_STORE_UNAVAILABLE") from None
            updated = profile.model_copy(update={"credential_ref": None})
            db.execute(
                "UPDATE model_profiles SET record=? WHERE id=?",
                (updated.model_dump_json(), str(identity)),
            )
            return updated

    def list(self, *, limit: int = 50, cursor: str | None = None) -> Page[ModelProfile]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ModelError("INVALID_LIMIT")
        with self._lock:
            rows = self._db.execute("SELECT record FROM model_profiles WHERE deleted=0").fetchall()
        profiles = [ModelProfile.model_validate_json(row[0]) for row in rows]
        profiles.extend(self._environment_profiles())
        profiles.sort(key=lambda p: (p.updated_at, p.id), reverse=True)
        if cursor is not None:
            try:
                if len(cursor) > 1024:
                    raise ValueError
                decoded = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if not isinstance(decoded, list) or len(decoded) != 3 or decoded[0] != "profiles":
                    raise ValueError
                stamp, identity = datetime.fromisoformat(decoded[1]), UUID(decoded[2])
                if stamp.tzinfo is None:
                    raise ValueError
                profiles = [p for p in profiles if (p.updated_at, p.id) < (stamp, identity)]
            except (ValueError, TypeError):
                raise ModelError("INVALID_CURSOR") from None
        next_cursor = None
        if len(profiles) > limit:
            last = profiles[limit - 1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(["profiles", last.updated_at.isoformat(), str(last.id)]).encode()
            ).decode()
        return Page[ModelProfile](items=tuple(profiles[:limit]), next_cursor=next_cursor)
