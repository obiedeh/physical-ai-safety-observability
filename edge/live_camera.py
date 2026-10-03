"""Optional CLI path for a live camera.

The supported way to run a camera is the web UI (Cameras → add → the API
hosts the capture and inference threads). This CLI keeps a terminal path for
the same code: either run a camera already saved in the UI (``--camera-id``),
or describe one on the command line / interactively, probe it, and run it
for a fixed duration, optionally writing a ``run-report-v1`` artifact.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import time

from api.services.store import SQLiteStore
from edge.camera_profiles import CAMERA_PROFILES, get_profile
from edge.config_models import CameraIn, InferenceSettings, ModelSettings
from edge.probe import probe_stream
from edge.redaction import REDACTOR
from edge.secrets import SecretBox
from edge.service import EdgeService
from runtime_settings import load_settings


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
    parser = argparse.ArgumentParser(description="Run a live camera through the safety pipeline.")
    parser.add_argument("--camera-id", help="Run a camera already saved in the UI")
    parser.add_argument("--host", help="Camera IP address or hostname")
    parser.add_argument("--port", type=int, help="Stream port (profile default when omitted)")
    parser.add_argument(
        "--camera-type", choices=sorted(k for k in CAMERA_PROFILES if k not in {"synthetic"}),
        help="Camera profile",
    )
    parser.add_argument("--stream-quality", choices=["main", "sub"], default="sub")
    parser.add_argument("--stream-path", help="Override the profile's stream path")
    parser.add_argument("--username", help="Camera account username")
    parser.add_argument("--password", help="Camera account password. Omit to prompt securely.")
    parser.add_argument("--config", help="Runtime config JSON (database path etc.)")
    parser.add_argument("--backend", help="Safety API backend URL for event posting")
    parser.add_argument("--no-post", action="store_true", help="Evaluate rules without posting")
    parser.add_argument("--adapter", choices=["mock", "cosmos-reason2", "openai-compatible"])
    parser.add_argument("--adapter-endpoint", help="OpenAI-compatible base URL")
    parser.add_argument("--model", help="Model name served at the endpoint")
    parser.add_argument("--json-schema", action="store_true", help="Constrained decoding")
    parser.add_argument("--think", action="store_true", help="Allow the model's think block")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--interval-ms", type=int, help="Inference cadence")
    parser.add_argument("--duration", type=float, default=60.0, help="Seconds to run (0 = until Ctrl-C)")
    parser.add_argument("--report", help="Write a run-report-v1 artifact to this path")
    parser.add_argument("--dry-run", action="store_true", help="Probe the camera and exit")
    parser.add_argument("--save", action="store_true", help="Save the camera to the UI config store")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings(args.config)
    store = SQLiteStore(database_path=settings.app.database_path)
    service = EdgeService(
        store, secrets=SecretBox(),
        backend=args.backend or settings.worker.backend,
        post_enabled=not args.no_post,
    )

    if args.camera_id:
        record = service.get_camera(args.camera_id)
        if record is None:
            sys.exit(f"camera '{args.camera_id}' is not in the config store")
        camera_id = record.camera_id
        print(f"camera={camera_id} profile={record.profile} url={record.masked_url}")
    else:
        host = _prompt(args.host, "Camera host/IP")
        camera_type = _prompt(args.camera_type, "Camera type", "tapo")
        profile = get_profile(camera_type)
        username = _prompt(args.username, "Camera username") if profile.requires_auth else (args.username or "")
        password = args.password or (getpass.getpass("Camera password: ") if profile.requires_auth else "")
        REDACTOR.register(password)
        camera = CameraIn(
            name=f"cli-{host}", profile=profile.model_type, host=host, port=args.port,
            username=username, password=password, stream_quality=args.stream_quality,
            stream_path=args.stream_path or "",
        )
        url = profile.build_url(
            host=host, username=username or None, password=password or None, port=camera.port,
            quality=camera.stream_quality, path=camera.stream_path or None,
        )
        result = probe_stream(url)
        print(f"probe: ok={result.ok} stage={result.stage} url={result.masked_url}")
        if not result.ok:
            sys.exit(result.error)
        print(f"stream: {result.width}x{result.height} {result.codec} {result.fps or '?'} fps")
        if args.dry_run:
            return
        record = service.create_camera(camera)
        camera_id = record.camera_id
        if not args.save:
            print("(camera not kept after this run; pass --save to keep it in the UI)")

    if args.adapter or args.adapter_endpoint or args.model or args.json_schema or args.think:
        current = service.get_model_settings()
        service.put_model_settings(
            ModelSettings(
                backend=args.adapter or ("cosmos-reason2" if current.backend == "mock" else current.backend),
                endpoint=args.adapter_endpoint or current.endpoint,
                model=args.model or current.model,
                json_schema=args.json_schema or current.json_schema,
                think=args.think,
                max_tokens=args.max_tokens or current.max_tokens,
                timeout_s=current.timeout_s,
                reasoning_parser=current.reasoning_parser,
            )
        )
    if args.interval_ms:
        current_inf = service.get_inference_settings()
        service.put_inference_settings(
            InferenceSettings(**{**current_inf.model_dump(), "interval_ms": args.interval_ms})
        )

    service.start()
    try:
        if service.model_settings.json_schema:
            guard = service.run_guard()
            if not guard.ok:
                sys.exit(f"refusing constrained run: {guard.message}")
        if args.report:
            service.start_run(camera_id, "cli-run")
        started = time.monotonic()
        last_print = 0.0
        while args.duration <= 0 or time.monotonic() - started < args.duration:
            time.sleep(0.5)
            latest = service.hub.latest.get(camera_id)
            if latest and time.monotonic() - last_print > 2.0:
                last_print = time.monotonic()
                print(
                    f"\r{latest.get('status'):<24} {latest.get('feedback', ''):<32} "
                    f"events={len(latest.get('events', []))}",
                    end="", flush=True,
                )
        print()
        if args.report:
            result = service.stop_run()
            print(f"report written: {result['written']} ({result['frames']} frames)")
    except KeyboardInterrupt:
        print()
        if args.report and service.run_status().get("recording"):
            print(f"report written: {service.stop_run()['written']}")
    finally:
        service.stop()
        if not args.camera_id and not args.save:
            service.delete_camera(camera_id)


if __name__ == "__main__":
    main()
