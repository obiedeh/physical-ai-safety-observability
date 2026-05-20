from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from events.schemas import Evidence, RuntimeContext
from evidence.hashing import hash_text


def build_evidence(
    *,
    frame_context: dict[str, Any],
    adapter_name: str,
    model_version: str,
    rule_version: str,
    runtime_context: RuntimeContext,
    detections: list[dict[str, Any]],
) -> Evidence:
    captured_at = frame_context.get("timestamp") or datetime.now(UTC)
    payload = f"{frame_context.get('camera_id')}:{captured_at}:{frame_context.get('frame_id')}"
    return Evidence(
        frame_hash=frame_context.get("frame_hash") or hash_text(payload),
        source_uri=redact_uri_credentials(frame_context["source_uri"]),
        adapter_name=adapter_name,
        model_version=model_version,
        rule_version=rule_version,
        captured_at=captured_at,
        telemetry_snapshot=runtime_context.model_dump(mode="json"),
        detections=detections,
    )


def redact_uri_credentials(uri: str) -> str:
    parts = urlsplit(uri)
    if not parts.username and not parts.password:
        return uri
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
