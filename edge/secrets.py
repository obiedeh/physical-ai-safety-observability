"""Encryption at rest for camera passwords and API keys.

Secrets are Fernet-encrypted before they reach SQLite. The key never lives in
the repository: it is read from ``PHYSICAL_AI_SECRET_KEY`` (a Fernet key) or
from the file named by ``PHYSICAL_AI_SECRET_KEY_FILE`` (default
``~/.config/urban-edge/secret.key``), which is created with mode 0600 on first
use. Losing the key means stored passwords must be re-entered in the UI.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_DEFAULT_KEY_FILE = Path.home() / ".config" / "physical-ai-safety" / "secret.key"
_PREFIX = "enc:v1:"


class SecretBox:
    def __init__(self, key: str | None = None, key_file: str | Path | None = None) -> None:
        if key is None:
            key = os.getenv("PHYSICAL_AI_SECRET_KEY") or None
        if key is None:
            path = Path(key_file or os.getenv("PHYSICAL_AI_SECRET_KEY_FILE") or _DEFAULT_KEY_FILE)
            key = _load_or_create_key(path)
        self._fernet = Fernet(key.encode("ascii") if isinstance(key, str) else key)

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return _PREFIX + self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str | None) -> str:
        if not token:
            return ""
        if not token.startswith(_PREFIX):
            # Legacy plaintext row — return as-is so it can be re-encrypted on next save.
            return token
        try:
            return self._fernet.decrypt(token[len(_PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise SecretKeyMismatch(
                "Stored secret cannot be decrypted with the current key. "
                "Re-enter the credential in the UI."
            ) from exc

    @staticmethod
    def is_encrypted(token: str | None) -> bool:
        return bool(token) and str(token).startswith(_PREFIX)


class SecretKeyMismatch(RuntimeError):
    """The stored ciphertext was produced with a different key."""


def _load_or_create_key(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="ascii").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode("ascii")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(key + "\n")
    return key
