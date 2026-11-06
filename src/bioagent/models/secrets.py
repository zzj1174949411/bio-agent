"""OS credentials only; never fall back to a file backend."""

from typing import Protocol

import keyring
from keyring.backend import KeyringBackend
from pydantic import SecretStr

from bioagent.models.profiles import ModelError


class SecretStore(Protocol):
    def set(self, ref: str, value: SecretStr) -> None: ...
    def get(self, ref: str) -> SecretStr | None: ...
    def delete(self, ref: str) -> None: ...


class SystemSecretStore:
    _SERVICE = "bioagent.model-profiles"
    _SYSTEM_BACKENDS = {
        ("keyring.backends.Windows", "WinVaultKeyring"),
        ("keyring.backends.macOS", "Keyring"),
        ("keyring.backends.SecretService", "Keyring"),
        ("keyring.backends.kwallet", "DBusKeyring"),
        ("keyring.backends.kwallet", "DBusKeyringKWallet4"),
        ("keyring.backends.kwallet", "DBusKeyringKWallet5"),
    }

    def _backend(self) -> KeyringBackend:
        backend = keyring.get_keyring()
        # Chainers may include an insecure third-party fallback. Fail closed;
        # users can configure an OS backend or use the environment profile.
        if (type(backend).__module__, type(backend).__name__) not in self._SYSTEM_BACKENDS:
            raise ModelError("SECRET_STORE_UNAVAILABLE")
        return backend

    def set(self, ref: str, value: SecretStr) -> None:
        try:
            self._backend().set_password(self._SERVICE, ref, value.get_secret_value())
        except Exception:
            raise ModelError("SECRET_STORE_UNAVAILABLE") from None

    def get(self, ref: str) -> SecretStr | None:
        try:
            value = self._backend().get_password(self._SERVICE, ref)
            return SecretStr(value) if value is not None else None
        except Exception:
            raise ModelError("SECRET_STORE_UNAVAILABLE") from None

    def delete(self, ref: str) -> None:
        try:
            backend = self._backend()
            if backend.get_password(self._SERVICE, ref) is not None:
                backend.delete_password(self._SERVICE, ref)
        except Exception:
            raise ModelError("SECRET_STORE_UNAVAILABLE") from None
