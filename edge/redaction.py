"""Credential redaction for logs, status payloads, events and artifacts.

Two layers:

* ``mask_url`` strips ``user:password@`` from any URL-like string.
* ``Redactor`` additionally replaces every registered secret (and its
  URL-quoted form) with ``***`` so a password that leaks through a library
  error message is still removed before it is logged or returned.

``install_logging_filter`` attaches the redactor to the root logger so every
log record is scrubbed, including messages produced by third-party modules.
"""
from __future__ import annotations

import logging
import re
import threading
from collections.abc import Iterable
from urllib.parse import quote

_URL_CREDS = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@")
_QUERY_SECRETS = re.compile(r"((?:password|pass|pwd|token|api_key|apikey)=)([^&\s]+)", re.IGNORECASE)


def mask_url(text: str) -> str:
    """Replace ``user:pass@`` with ``***:***@`` in every URL in ``text``."""
    if not text or "@" not in text:
        return _QUERY_SECRETS.sub(r"\1***", text) if text else text
    masked = _URL_CREDS.sub(lambda m: f"{m.group('scheme')}***:***@", text)
    return _QUERY_SECRETS.sub(r"\1***", masked)


class Redactor:
    def __init__(self) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def register(self, *secrets: str | None) -> None:
        with self._lock:
            for secret in secrets:
                if secret and len(secret) >= 3:
                    self._secrets.add(secret)
                    quoted = quote(secret, safe="")
                    if quoted != secret:
                        self._secrets.add(quoted)

    def forget(self, *secrets: str | None) -> None:
        with self._lock:
            for secret in secrets:
                if secret:
                    self._secrets.discard(secret)
                    self._secrets.discard(quote(secret, safe=""))

    def redact(self, text: str | None) -> str:
        if not text:
            return ""
        out = mask_url(str(text))
        with self._lock:
            # Longest first so a secret that contains another is replaced whole.
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            if secret in out:
                out = out.replace(secret, "***")
        return out

    def redact_lines(self, lines: Iterable[str]) -> list[str]:
        return [self.redact(line) for line in lines]


REDACTOR = Redactor()


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        redacted = REDACTOR.redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_logging_filter(logger: logging.Logger | None = None) -> None:
    target = logger or logging.getLogger()
    if not any(isinstance(f, _RedactingFilter) for f in target.filters):
        target.addFilter(_RedactingFilter())
    for handler in target.handlers:
        if not any(isinstance(f, _RedactingFilter) for f in handler.filters):
            handler.addFilter(_RedactingFilter())
