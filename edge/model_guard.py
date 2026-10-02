"""Verify a model server before a run; enforce the constrained-mode rule.

vLLM 0.14 accepts ``response_format: json_schema`` but does not enforce it
when the server runs with ``--reasoning-parser``. Documentation alone did not
stop that misconfiguration, so this module checks it in code:

1. ``check_server`` confirms the endpoint answers ``/models`` and serves the
   configured model.
2. ``probe_constrained`` sends a tiny request whose schema allows exactly one
   value. If the server honours the grammar the answer is that value; a
   reasoning-parser server returns free text instead and the run is refused.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from edge.redaction import REDACTOR

_CANARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["grammar_ok"]}},
    "required": ["status"],
    "additionalProperties": False,
}


@dataclass
class GuardResult:
    ok: bool
    stage: str                  # server | model | constrained | ok
    message: str
    served_models: list[str]
    constrained_enforced: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_server(endpoint: str, model: str, *, api_key: str | None = None, timeout_s: float = 5.0) -> GuardResult:
    base = endpoint.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(f"{base}/models", headers=headers, timeout=timeout_s)
        response.raise_for_status()
        served = [m.get("id", "") for m in response.json().get("data", [])]
    except Exception as exc:
        return GuardResult(
            ok=False, stage="server",
            message=REDACTOR.redact(f"Model server at {base} is not reachable: {exc}"),
            served_models=[],
        )
    if model and served and model not in served:
        return GuardResult(
            ok=False, stage="model",
            message=f"Server at {base} serves {served}, not '{model}'.",
            served_models=served,
        )
    return GuardResult(ok=True, stage="ok", message="server reachable", served_models=served)


def probe_constrained(
    endpoint: str, model: str, *, api_key: str | None = None, timeout_s: float = 60.0
) -> GuardResult:
    """Return ok=False when the server does not enforce json_schema."""
    base = endpoint.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Reply with the single word banana and nothing else. "
                    "Do not output JSON."
                ),
            }
        ],
        "temperature": 0,
        "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "canary", "schema": _CANARY_SCHEMA, "strict": True},
        },
    }
    try:
        response = httpx.post(
            f"{base}/chat/completions", json=payload, headers=headers, timeout=timeout_s
        )
        response.raise_for_status()
        text = _assistant_text(response.json())
    except Exception as exc:
        return GuardResult(
            ok=False, stage="constrained",
            message=REDACTOR.redact(f"Constrained-mode probe failed: {exc}"),
            served_models=[], constrained_enforced=None,
        )
    enforced = _is_canary(text)
    if not enforced:
        return GuardResult(
            ok=False, stage="constrained",
            message=(
                "Server ignored response_format json_schema (got "
                f"{text.strip()[:60]!r}). It is most likely running with --reasoning-parser; "
                "use the no-reasoning container for constrained runs."
            ),
            served_models=[], constrained_enforced=False,
        )
    return GuardResult(
        ok=True, stage="ok", message="json_schema enforced by server",
        served_models=[], constrained_enforced=True,
    )


def _assistant_text(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
    return str(content or "")


def _is_canary(text: str) -> bool:
    try:
        parsed = json.loads(text.strip())
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and parsed.get("status") == "grammar_ok"
