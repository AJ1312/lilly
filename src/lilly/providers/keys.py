"""Key stores. The system keychain is the home for API keys; a 0600 file is the labelled fallback."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import keyring
import keyring.errors
from keyring.backends import fail

from lilly.domain.ports import KeyStore, Secret


class KeychainStore(KeyStore):
    """The operating system's keychain (macOS Keychain, Secret Service, Windows Credential Locker)."""

    kind = "keychain"
    secure = True

    def __init__(self, service: str = "lilly") -> None:
        self._service = service

    @staticmethod
    def available() -> bool:
        """True when `keyring` found a real backend rather than its do-nothing fallback."""
        return not isinstance(keyring.get_keyring(), fail.Keyring)

    def get(self, ref: str) -> Secret | None:
        value = keyring.get_password(self._service, ref)
        return Secret(value) if value is not None else None

    def put(self, ref: str, value: Secret) -> None:
        keyring.set_password(self._service, ref, value.reveal())

    def delete(self, ref: str) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self._service, ref)


class FileKeyStore(KeyStore):
    """Keys in a 0600 JSON file. Weaker than a keychain (anything running as you can read it),
    so the UI says so whenever this is in use."""

    kind = "file"
    secure = False

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, data: Mapping[str, str]) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".keys-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(dict(data), f)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, ref: str) -> Secret | None:
        value = self._load().get(ref)
        return Secret(value) if value is not None else None

    def put(self, ref: str, value: Secret) -> None:
        data = self._load()
        data[ref] = value.reveal()
        self._save(data)

    def delete(self, ref: str) -> None:
        data = self._load()
        if data.pop(ref, None) is not None:
            self._save(data)


def open_key_store(config_dir: Path) -> KeychainStore | FileKeyStore:
    """The keychain when the system has one, otherwise the file fallback."""
    return KeychainStore() if KeychainStore.available() else FileKeyStore(config_dir / "keys.json")
