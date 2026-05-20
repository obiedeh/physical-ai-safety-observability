import argparse
import getpass
import signal
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from edge.source_loader import VideoSource
from edge.worker import build_adapter, run_worker
from runtime_settings import load_settings


CAMERA_PATHS = {
    "tapo": ["stream1", "stream2"],
    "generic": [
        "stream1",
        "stream2",
        "live",
        "h264",
        "Streaming/Channels/101",
        "cam/realmonitor?channel=1&subtype=0",
    ],
}


@dataclass(frozen=True)
class ProbeResult:
    camera_type: str
    uri: str
    redacted_uri: str
    width: int
    height: int


def _safe_userinfo(username: str, password: str) -> str:
    return f"{quote(username, safe='')}:{quote(password, safe='')}"


def _build_uri(host: str, port: int, path: str, username: str, password: str) -> str:
    clean_path = path.lstrip("/")
    return f"rtsp://{_safe_userinfo(username, password)}@{host}:{port}/{clean_path}"


def _redacted_uri(host: str, port: int, path: str) -> str:
    return f"rtsp://{host}:{port}/{path.lstrip('/')}"


def _candidate_profiles(camera_type: str) -> list[tuple[str, str]]:
    if camera_type != "auto":
        return [(camera_type, path) for path in CAMERA_PATHS[camera_type]]
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for profile in ("tapo", "generic"):
        for path in CAMERA_PATHS[profile]:
            key = f"{profile}:{path}"
            if key in seen:
                continue
            seen.add(key)
            candidates.append((profile, path))
    return candidates


def _probe_uri(uri: str, timeout_seconds: int) -> tuple[int, int] | None:
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is required for live RTSP probing. Install the opencv extra."
        ) from exc

    def timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError("RTSP probe timed out")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    capture = None
    try:
        capture = cv2.VideoCapture(uri)
        if not capture.isOpened():
            return None
        ok, frame = capture.read()
        if not ok or frame is None:
            return None
        return int(frame.shape[1]), int(frame.shape[0])
    except TimeoutError:
        return None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        if capture is not None:
            capture.release()


def probe_camera(
    *, host: str, port: int, camera_type: str, username: str, password: str, timeout_seconds: int
) -> ProbeResult:
    for profile, path in _candidate_profiles(camera_type):
        uri = _build_uri(host, port, path, username, password)
        redacted = _redacted_uri(host, port, path)
        print(f"Trying {profile} RTSP path: {redacted}")
        dimensions = _probe_uri(uri, timeout_seconds)
        if dimensions is None:
            continue
        width, height = dimensions
        return ProbeResult(profile, uri, redacted, width, height)
    raise RuntimeError(
        "No RTSP candidate opened. Check camera type, local camera account, password, RTSP setting, and network reachability."
    )


def _prompt(value: str | None, label: str, default: str | None = None) -> str:
    if value:
        return value
    suffix = f" [{default}]" if default else ""
    entered = input(f"{label}{suffix}: ").strip()
    if entered:
        return entered
    if default is not None:
        return default
    raise RuntimeError(f"{label} is required")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a live RTSP camera and run safety observability."
    )
    parser.add_argument("--host", help="Camera IP address or hostname")
    parser.add_argument("--port", type=int, default=554, help="RTSP port")
    parser.add_argument(
        "--camera-type", choices=["auto", "tapo", "generic"], help="Camera RTSP profile to probe"
    )
    parser.add_argument("--username", help="Local RTSP/camera-account username")
    parser.add_argument(
        "--password", help="Local RTSP/camera-account password. Omit to prompt securely."
    )
    parser.add_argument(
        "--config", default="configs/cosmos_reasoning.json", help="Runtime config path"
    )
    parser.add_argument("--backend", help="Safety API backend URL")
    parser.add_argument("--camera-id", default="live-camera", help="Camera ID for emitted events")
    parser.add_argument("--name", default="Live RTSP camera", help="Camera display name")
    parser.add_argument("--frame-count", type=int, default=3, help="Frames to sample per run")
    parser.add_argument(
        "--frame-stride", type=int, default=30, help="Decode stride for sampled frames"
    )
    parser.add_argument(
        "--probe-timeout", type=int, default=12, help="Seconds per RTSP candidate probe"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only verify the RTSP camera; do not run inference or post events",
    )
    parser.add_argument(
        "--once", action="store_true", help="Process one camera sampling pass and exit"
    )
    parser.add_argument(
        "--feedback-interval-seconds",
        type=float,
        help="Seconds between person/PPE feedback checks in continuous mode",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print structured worker logs instead of clean feedback-only output",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    host = _prompt(args.host, "Camera host/IP")
    camera_type = _prompt(args.camera_type, "Camera type (auto, tapo, generic)", "auto")
    username = _prompt(args.username, "RTSP username")
    password = args.password or getpass.getpass("RTSP password: ")

    result = probe_camera(
        host=host,
        port=args.port,
        camera_type=camera_type,
        username=username,
        password=password,
        timeout_seconds=args.probe_timeout,
    )
    print(
        f"Verified {result.camera_type} camera: {result.redacted_uri} ({result.width}x{result.height})"
    )
    if args.dry_run:
        return

    settings = load_settings(args.config)
    if args.backend:
        settings.worker.backend = args.backend
    if args.once:
        settings.worker.continuous = False
    if args.feedback_interval_seconds is not None:
        settings.worker.feedback_interval_seconds = args.feedback_interval_seconds
    if args.verbose:
        settings.worker.clean_feedback_terminal = False

    source = VideoSource(
        camera_id=args.camera_id,
        name=args.name,
        source_uri=result.uri,
        source_type="rtsp",
        frame_count=args.frame_count,
        frame_stride=args.frame_stride,
        sample_interval_ms=0,
        zones=[
            {
                "zone_id": f"{args.camera_id}-entry",
                "type": "restricted",
                "polygon": [
                    [0, 0],
                    [result.width, 0],
                    [result.width, result.height],
                    [0, result.height],
                ],
            }
        ],
    )
    events = run_worker(
        source=source,
        backend=settings.worker.backend,
        adapter=build_adapter(settings),
        post_events=settings.worker.post_events,
        continuous=settings.worker.continuous,
        feedback_interval_seconds=settings.worker.feedback_interval_seconds,
        clean_feedback_terminal=settings.worker.clean_feedback_terminal,
    )
    if not settings.worker.continuous:
        print(f"posted_events={len(events)}")


if __name__ == "__main__":
    main()
