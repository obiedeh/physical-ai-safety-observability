"""Stream probe: open a camera URL, decode one frame, classify any failure.

Used by "Test connection" in the UI and by the camera-check CLI. Runs the
blocking PyAV open/decode in a worker thread with a hard timeout so a hung
camera can never block the API, and never returns the credentialed URL.
"""
from __future__ import annotations

import io
import socket
import threading
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from edge.redaction import REDACTOR, mask_url

ProbeStage = str  # "reachability" | "auth" | "path" | "codec" | "timeout" | "decode" | "ok"


@dataclass
class ProbeResult:
    ok: bool
    stage: ProbeStage
    error: str | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    fps: float | None = None
    open_ms: float | None = None
    thumbnail_jpeg: bytes | None = None
    masked_url: str = ""

    def to_dict(self, *, include_thumbnail: bool = True) -> dict[str, Any]:
        data = asdict(self)
        thumb = data.pop("thumbnail_jpeg")
        if include_thumbnail and thumb:
            import base64

            encoded = base64.b64encode(thumb).decode()
            data["thumbnail_data_url"] = "data:image/jpeg;base64," + encoded
        else:
            data["thumbnail_data_url"] = None
        return data


def classify_error(message: str) -> tuple[ProbeStage, str]:
    """Map libav/socket error text onto an operator-readable category."""
    text = (message or "").lower()
    if "401" in text or "unauthorized" in text or "authentication" in text or "403" in text:
        return "auth", "Authentication failed — check the username and password."
    if "404" in text or "not found" in text or "stream not found" in text:
        return "path", "Stream path not found on the camera — check the stream path / channel."
    if "454" in text or "session not found" in text:
        return "path", "Camera rejected the stream path (RTSP 454)."
    if "timed out" in text or "timeout" in text or "immediate exit" in text:
        return "timeout", "Timed out waiting for the camera — host reachable but no stream data."
    if (
        "connection refused" in text or "no route to host" in text
        or "network is unreachable" in text
        or "name or service not known" in text or "nodename nor servname" in text
        or "host is down" in text or "unreachable" in text or "connection reset" in text
    ):
        return "reachability", "Camera unreachable — check the host, port and network."
    if "invalid data found" in text or "could not find codec" in text or "decoder" in text or \
            "unsupported codec" in text or "codec" in text or "no frame" in text:
        return "codec", "Connected but the video could not be decoded (unsupported codec/stream)."
    return "decode", REDACTOR.redact(message)


def tcp_reachable(host: str, port: int, timeout: float = 2.0) -> str | None:
    """Return None if the TCP port accepts a connection, else an error string."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return str(exc)


def probe_stream(
    url: str,
    *,
    timeout_s: float = 8.0,
    rtsp_transport: str = "tcp",
    thumbnail_width: int = 320,
) -> ProbeResult:
    masked = mask_url(url)
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (554 if parsed.scheme.startswith("rtsp") else 80)
    if host:
        reach_err = tcp_reachable(host, port, timeout=min(3.0, timeout_s))
        if reach_err:
            return ProbeResult(
                ok=False, stage="reachability", masked_url=masked,
                error=f"Camera unreachable at {host}:{port} — {REDACTOR.redact(reach_err)}",
            )

    result: dict[str, Any] = {}

    def worker() -> None:
        try:
            result["value"] = _decode_one(url, timeout_s, rtsp_transport, thumbnail_width, masked)
        except Exception as exc:  # pragma: no cover - defensive; _decode_one catches its own
            result["value"] = ProbeResult(
                ok=False, stage="decode", error=REDACTOR.redact(str(exc)), masked_url=masked
            )

    thread = threading.Thread(target=worker, daemon=True, name="camera-probe")
    thread.start()
    thread.join(timeout_s + 2.0)
    if thread.is_alive() or "value" not in result:
        return ProbeResult(
            ok=False, stage="timeout", masked_url=masked,
            error=f"Timed out after {timeout_s:.0f}s waiting for the first frame.",
        )
    value: ProbeResult = result["value"]
    return value


def _decode_one(
    url: str, timeout_s: float, rtsp_transport: str, thumbnail_width: int, masked: str
) -> ProbeResult:
    import time

    import av

    options = {}
    if url.startswith("rtsp"):
        options = {
            "rtsp_transport": rtsp_transport or "tcp",
            "stimeout": str(int(timeout_s * 1_000_000)),
        }
    started = time.perf_counter()
    try:
        container = av.open(url, options=options, timeout=timeout_s)
    except Exception as exc:
        stage, message = classify_error(str(exc))
        return ProbeResult(ok=False, stage=stage, error=message, masked_url=masked)
    try:
        open_ms = (time.perf_counter() - started) * 1000
        stream = next((s for s in container.streams if s.type == "video"), None)
        if stream is None:
            return ProbeResult(
                ok=False, stage="codec", error="No video stream in the feed.", masked_url=masked
            )
        codec = stream.codec_context.name
        fps = float(stream.average_rate) if stream.average_rate else None
        for frame in container.decode(video=0):
            image = frame.to_image()
            width, height = image.size
            if width > thumbnail_width:
                image = image.resize(
                    (thumbnail_width, max(1, int(height * thumbnail_width / width)))
                )
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=75)
            return ProbeResult(
                ok=True, stage="ok", width=width, height=height, codec=codec, fps=fps,
                open_ms=round(open_ms, 1), thumbnail_jpeg=buf.getvalue(), masked_url=masked,
            )
        return ProbeResult(
            ok=False, stage="codec", error="Stream opened but produced no frames.",
            codec=codec, masked_url=masked,
        )
    except Exception as exc:
        stage, message = classify_error(str(exc))
        return ProbeResult(ok=False, stage=stage, error=message, masked_url=masked)
    finally:
        try:
            container.close()
        except Exception:
            pass
