"""EdgeService: UI-configured cameras running in the API process.

One ``CameraWorker`` thread per enabled camera samples the camera's
latest-frame slot on the inference cadence, calls the VLM adapter, evaluates
the safety rules and hands events to the ``AsyncPoster``. Capture (PyAV
thread), inference (worker thread) and posting (poster thread) are three
independent loops; none blocks another.

Configuration changes from the API are applied here without a restart:
cameras (``refresh_camera`` / ``remove_camera``), model (``apply_model``),
inference cadence (``apply_inference``). A measured run can be recorded from
the UI (``start_run`` / ``stop_run``) and lands under ``reports/<host>/`` in
the same ``run-report-v1`` shape as the committed Thor runs.
"""
from __future__ import annotations

import io
import json
import logging
import platform
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from api.services.store import SQLiteStore
from edge.adapters.base import VLMAdapter
from edge.adapters.mock_vlm import MockVLMAdapter
from edge.adapters.openai_compatible import CosmosReason2Adapter, OpenAICompatibleAdapter
from edge.camera_profiles import CameraConfigError, get_profile
from edge.capture import (
    CameraSession,
    PushCameraSession,
    StreamCameraSession,
    SyntheticCameraSession,
)
from edge.config_models import CameraIn, CameraRecord, InferenceSettings, ModelSettings
from edge.model_guard import GuardResult, check_server, probe_constrained
from edge.model_server import ModelServerManager
from edge.poster import AsyncPoster, PostJob
from edge.redaction import REDACTOR, mask_url
from edge.results import ResultHub
from edge.secrets import SecretBox
from edge.worker import build_person_ppe_feedback
from evidence.hashing import hash_bytes
from rules.engine import SafetyPolicyEngine
from spatial.zones import Zone
from telemetry.run_report import RunRecorder
from telemetry.runtime import RuntimeMonitor, Timer

logger = logging.getLogger("edge.service")

STALE_FRAME_S = 10.0


# ── adapter construction ──────────────────────────────────────────────────────


def build_adapter_from_settings(settings: ModelSettings, api_key: str = "") -> VLMAdapter:
    if settings.backend == "mock":
        return MockVLMAdapter()
    if settings.backend == "openai-compatible":
        return OpenAICompatibleAdapter(
            endpoint=settings.normalized_endpoint(),
            model=settings.model,
            api_key=api_key or None,
            timeout=settings.timeout_s,
        )
    return CosmosReason2Adapter(
        endpoint=settings.normalized_endpoint(),
        model=settings.model,
        api_key=api_key or None,
        timeout=settings.timeout_s,
        max_tokens=settings.max_tokens,
        think=settings.think,
        json_schema=settings.json_schema,
    )


# ── camera worker ─────────────────────────────────────────────────────────────


class CameraWorker(threading.Thread):
    def __init__(self, service: EdgeService, camera: CameraRecord, session: CameraSession) -> None:
        super().__init__(name=f"worker-{camera.camera_id}", daemon=True)
        self.service = service
        self.camera = camera
        self.session = session
        self.engine = SafetyPolicyEngine(zones=[])
        self.runtime = RuntimeMonitor()
        self._halt = threading.Event()
        self.frames_sampled = 0
        self.frames_skipped_same = 0
        self.inference_failures = 0
        self.consecutive_failures = 0
        self.last_error: str | None = None
        self.last_result_at: float | None = None
        self.events_emitted = 0
        self._last_seq = -1

    def stop(self) -> None:
        self._halt.set()

    def run(self) -> None:
        while not self._halt.is_set():
            settings = self.service.inference
            if self._halt.wait(max(settings.interval_ms, 100) / 1000):
                return
            record = self.session.slot.latest
            if record is None or (time.monotonic() - record.monotonic) > STALE_FRAME_S:
                self.service.publish_status(self.camera.camera_id, "no_frame", self)
                continue
            if record.seq == self._last_seq:
                self.frames_skipped_same += 1
                continue
            self._last_seq = record.seq
            if self.service.model_settings.json_schema and not self.service.constrained_allowed():
                self.service.publish_status(self.camera.camera_id, "blocked_constrained_mode", self)
                continue
            adapter = self.service.adapter
            try:
                frame_bytes, width, height = _resize_jpeg(record.jpeg, settings.width, settings.height)
            except Exception as exc:
                self.last_error = REDACTOR.redact(str(exc))
                continue
            captured_mono = record.monotonic
            frame_age_ms = (time.monotonic() - captured_mono) * 1000
            timestamp = datetime.fromtimestamp(record.wall_ms / 1000, tz=UTC)
            frame_context: dict[str, Any] = {
                "frame_id": f"{self.camera.camera_id}-{record.seq:08d}",
                "camera_id": self.camera.camera_id,
                "source_uri": self.session_masked_url(),
                "timestamp": timestamp,
                "frame_hash": hash_bytes(frame_bytes),
                "metadata": {
                    "source_type": self.session.kind,
                    "capture_seq": record.seq,
                    "width": width,
                    "height": height,
                    "display_size": [record.width, record.height],
                },
                "frame_bytes": frame_bytes,
                "detections": None,
            }
            self.engine.zones = _scale_zones(self.camera.zones, width, height)
            self.frames_sampled += 1
            self.runtime.frames_processed += 1
            self.runtime.frames_dropped = self.session.stats.frames_dropped
            self.runtime.queue_depth = self.service.poster.queue_depth
            with Timer() as inference_timer:
                try:
                    analysis = adapter.analyze_frame(frame_context)
                except Exception as exc:
                    self.inference_failures += 1
                    self.consecutive_failures += 1
                    self.last_error = REDACTOR.redact(f"{type(exc).__name__}: {exc}")
                    self.service.publish_status(self.camera.camera_id, "inference_unavailable", self)
                    continue
            self.consecutive_failures = 0
            self.last_error = None
            self.runtime.inference_latency_ms = inference_timer.elapsed_ms
            self.runtime.record_latency(inference_timer.elapsed_ms)
            detections = list(analysis.get("detections", []) or [])

            with Timer() as rule_timer:
                events = self.engine.evaluate(
                    frame_context=frame_context,
                    analysis=analysis,
                    runtime_context=self.runtime.snapshot(),
                )
            if self.camera.rules:
                events = [e for e in events if e.rule_id in set(self.camera.rules)]
            self.runtime.rule_eval_latency_ms = rule_timer.elapsed_ms
            payloads = [e.model_dump(mode="json") for e in events]
            feedback = build_person_ppe_feedback(frame_context=frame_context, detections=detections)

            if self.service.post_enabled:
                if settings.post_feedback:
                    self.service.poster.enqueue(
                        PostJob("feedback", feedback.model_dump(mode="json"), captured_mono)
                    )
                if payloads:
                    if settings.post_batch:
                        self.service.poster.enqueue(PostJob("events_batch", payloads, captured_mono))
                    else:
                        for payload in payloads:
                            self.service.poster.enqueue(PostJob("event", payload, captured_mono))
            if payloads:
                self.service.save_evidence_frame(str(frame_context["frame_hash"]), frame_bytes)
            self.events_emitted += len(payloads)
            self.last_result_at = time.time()
            capture_to_result_ms = (time.monotonic() - captured_mono) * 1000

            recorder = self.service.recorder_for(self.camera.camera_id)
            if recorder is not None:
                raw = analysis.get("raw_response") if isinstance(analysis, dict) else None
                recorder.record_frame(
                    frame_id=str(frame_context["frame_id"]),
                    inference_ms=inference_timer.elapsed_ms,
                    rule_ms=rule_timer.elapsed_ms,
                    post_ms=None,  # posting is asynchronous; see transport.post_latency_ms
                    events=payloads,
                    detections=len(detections),
                    usage=raw.get("usage") if isinstance(raw, dict) else None,
                    labels=[str(d.get("label")) for d in detections if isinstance(d, dict)],
                    capture_to_result_ms=capture_to_result_ms,
                    frame_age_ms=frame_age_ms,
                )
            self.service.hub.publish(
                self.camera.camera_id,
                {
                    "camera_id": self.camera.camera_id,
                    "status": "ok",
                    "frame_id": frame_context["frame_id"],
                    "capture_seq": record.seq,
                    "timestamp": timestamp.isoformat(),
                    "frame_size": [width, height],
                    "inference_ms": round(inference_timer.elapsed_ms, 1),
                    "rule_ms": round(rule_timer.elapsed_ms, 2),
                    "capture_to_result_ms": round(capture_to_result_ms, 1),
                    "detections": _public_detections(detections, width, height),
                    "feedback": feedback.message,
                    "events": [
                        {"event_id": e.event_id, "rule_id": e.rule_id, "severity": e.severity,
                         "confidence": e.confidence, "summary": e.summary,
                         "human_review_required": e.human_review_required}
                        for e in events
                    ],
                    "model": getattr(adapter, "model_version", type(adapter).__name__),
                    "reasoning_text": (
                        str(analysis.get("reasoning_text"))[:400]
                        if analysis.get("reasoning_text") else None
                    ),
                },
            )

    def session_masked_url(self) -> str:
        return getattr(self.session, "masked_url", f"{self.session.kind}://{self.camera.camera_id}")

    def status(self) -> dict[str, Any]:
        return {
            "frames_sampled": self.frames_sampled,
            "frames_skipped_same": self.frames_skipped_same,
            "inference_failures": self.inference_failures,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "last_result_age_s": (
                round(time.time() - self.last_result_at, 1) if self.last_result_at else None
            ),
            "events_emitted": self.events_emitted,
            "active_zones": len(self.camera.zones),
            "rules": self.camera.rules or "all",
        }


# ── service ───────────────────────────────────────────────────────────────────


class EdgeService:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        secrets: SecretBox | None = None,
        backend: str = "http://127.0.0.1:8080",
        post_enabled: bool = True,
        reports_dir: str | Path = "reports",
    ) -> None:
        self.store = store
        self.secrets = secrets or SecretBox()
        self.backend = backend
        self.post_enabled = post_enabled
        self.reports_dir = Path(reports_dir)
        db = getattr(store, "database_path", ":memory:")
        self.evidence_dir = (
            Path(db).parent / "evidence" if db != ":memory:" else Path("data") / "evidence"
        )
        self.hub = ResultHub()
        self.poster = AsyncPoster(backend)
        self.model_server = ModelServerManager()
        self.model_settings = ModelSettings()
        self.inference = InferenceSettings()
        self.adapter: VLMAdapter = MockVLMAdapter()
        self.guard: GuardResult | None = None
        self.sessions: dict[str, CameraSession] = {}
        self.workers: dict[str, CameraWorker] = {}
        self.cameras: dict[str, CameraRecord] = {}
        self._recorders: dict[str, RunRecorder] = {}
        self._run: dict[str, Any] | None = None
        self._lock = threading.RLock()
        self.started_at: float | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self.started_at = time.time()
        self.poster.start()
        self.apply_model()
        self.apply_inference()
        for cfg in self.store.list_camera_configs(enabled_only=True):
            self.refresh_camera(cfg["camera_id"])

    def stop(self) -> None:
        for camera_id in list(self.workers):
            self._stop_camera(camera_id)
        self.poster.stop()
        # The model server may be shared with another app on the device; an API
        # restart must not take it down. Explicit stop is POST /models/server/stop.
        self.model_server.detach()

    # ── cameras ───────────────────────────────────────────────────────────────

    def list_cameras(self) -> list[CameraRecord]:
        return [self._record(c) for c in self.store.list_camera_configs()]

    def get_camera(self, camera_id: str) -> CameraRecord | None:
        cfg = self.store.get_camera_config(camera_id)
        return self._record(cfg) if cfg else None

    def create_camera(self, data: CameraIn, camera_id: str | None = None) -> CameraRecord:
        new_id = (camera_id or "").strip() or self._unique_id(_slug(data.name))
        payload = self._payload(data, existing=None)
        self.store.save_camera_config(new_id, payload, enabled=data.enabled)
        record = self.get_camera(new_id)
        assert record is not None
        self.refresh_camera(new_id)
        return record

    def update_camera(self, camera_id: str, data: CameraIn) -> CameraRecord | None:
        existing = self.store.get_camera_config(camera_id)
        if existing is None:
            return None
        payload = self._payload(data, existing=existing)
        self.store.save_camera_config(camera_id, payload, enabled=data.enabled)
        self.refresh_camera(camera_id)
        return self.get_camera(camera_id)

    def set_enabled(self, camera_id: str, enabled: bool) -> CameraRecord | None:
        if self.store.set_camera_config_enabled(camera_id, enabled) is None:
            return None
        self.refresh_camera(camera_id)
        return self.get_camera(camera_id)

    def delete_camera(self, camera_id: str) -> bool:
        self.remove_camera(camera_id)
        return self.store.delete_camera_config(camera_id)

    def feed_url(self, camera_id: str) -> str:
        cfg = self.store.get_camera_config(camera_id)
        if cfg is None:
            raise KeyError(camera_id)
        password = self.secrets.decrypt(cfg.get("password_enc") or "")
        REDACTOR.register(password)
        return _build_url(cfg, password)

    def refresh_camera(self, camera_id: str) -> None:
        with self._lock:
            self._stop_camera(camera_id)
            cfg = self.store.get_camera_config(camera_id)
            if cfg is None or not cfg.get("enabled", True):
                self.cameras.pop(camera_id, None)
                self.hub.forget(camera_id)
                return
            record = self._record(cfg)
            self.cameras[camera_id] = record
            session = self._build_session(record)
            session.start()
            self.sessions[camera_id] = session
            worker = CameraWorker(self, record, session)
            worker.start()
            self.workers[camera_id] = worker

    def remove_camera(self, camera_id: str) -> None:
        with self._lock:
            self._stop_camera(camera_id)
            self.cameras.pop(camera_id, None)
            self.hub.forget(camera_id)

    def _stop_camera(self, camera_id: str) -> None:
        worker = self.workers.pop(camera_id, None)
        if worker is not None:
            worker.stop()
            if worker.is_alive() and worker is not threading.current_thread():
                worker.join(5.0)
        session = self.sessions.pop(camera_id, None)
        if session is not None:
            session.stop()

    def _build_session(self, camera: CameraRecord) -> CameraSession:
        kw: dict[str, Any] = {
            "display_max_width": self.inference.display_max_width,
            "jpeg_quality": self.inference.jpeg_quality,
        }
        if camera.profile == "synthetic":
            return SyntheticCameraSession(camera.camera_id, **kw)
        if camera.profile == "browser_webrtc":
            return PushCameraSession(camera.camera_id, **kw)
        return StreamCameraSession(
            camera.camera_id, self.feed_url(camera.camera_id),
            rtsp_transport=camera.rtsp_transport, **kw,
        )

    def session(self, camera_id: str) -> CameraSession | None:
        return self.sessions.get(camera_id)

    def push_session(self, camera_id: str) -> PushCameraSession | None:
        session = self.sessions.get(camera_id)
        return session if isinstance(session, PushCameraSession) else None

    def _payload(self, data: CameraIn, existing: dict[str, Any] | None) -> dict[str, Any]:
        if data.password:
            enc = self.secrets.encrypt(data.password)
            password = data.password
            REDACTOR.register(password)
        else:
            enc = (existing or {}).get("password_enc") or ""
            password = self.secrets.decrypt(enc)
        payload = data.model_dump(mode="json")
        payload.pop("password", None)
        payload.pop("enabled", None)
        payload["password_enc"] = enc
        _validate_url(data, password)
        return payload

    def _record(self, cfg: dict[str, Any]) -> CameraRecord:
        profile = get_profile(cfg.get("profile") or "generic_rtsp")
        quality = cfg.get("stream_quality") or "main"
        channel = int(cfg.get("channel") or 1)
        effective = (cfg.get("stream_path") or "") or (
            profile.stream_path(quality, channel) if profile.requires_host else ""
        )
        masked = ""
        if profile.requires_host and cfg.get("host"):
            masked = mask_url(_build_url(cfg, "x" if cfg.get("password_enc") else ""))
        return CameraRecord(
            camera_id=cfg["camera_id"],
            name=cfg.get("name") or cfg["camera_id"],
            profile=profile.model_type,
            host=cfg.get("host") or "",
            port=cfg.get("port"),
            username=cfg.get("username") or "",
            has_password=bool(cfg.get("password_enc")),
            stream_path=cfg.get("stream_path") or "",
            effective_stream_path=effective,
            stream_quality=quality,
            channel=channel,
            rtsp_transport=cfg.get("rtsp_transport") or "tcp",
            enabled=bool(cfg.get("enabled", True)),
            location=cfg.get("location"),
            zones=[Zone.model_validate(z) for z in cfg.get("zones") or []],
            rules=list(cfg.get("rules") or []),
            masked_url=masked,
            created_at=cfg.get("created_at"),
            updated_at=cfg.get("updated_at"),
        )

    def _unique_id(self, base: str) -> str:
        existing = {c["camera_id"] for c in self.store.list_camera_configs()}
        candidate, n = base, 2
        while candidate in existing:
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    # ── model / inference settings ────────────────────────────────────────────

    def get_model_settings(self) -> ModelSettings:
        raw = self.store.get_setting("model") or {}
        settings = ModelSettings.model_validate({k: v for k, v in raw.items() if k != "api_key_enc"})
        settings.has_api_key = bool(raw.get("api_key_enc"))
        settings.api_key = ""
        return settings

    def put_model_settings(self, settings: ModelSettings) -> ModelSettings:
        raw = self.store.get_setting("model") or {}
        data = settings.model_dump()
        api_key = data.pop("api_key", "")
        data.pop("has_api_key", None)
        if api_key:
            REDACTOR.register(api_key)
            data["api_key_enc"] = self.secrets.encrypt(api_key)
        else:
            data["api_key_enc"] = raw.get("api_key_enc", "")
        self.store.put_setting("model", data)
        self.apply_model()
        return self.get_model_settings()

    def model_api_key(self) -> str:
        raw = self.store.get_setting("model") or {}
        key = self.secrets.decrypt(raw.get("api_key_enc") or "")
        REDACTOR.register(key)
        return key

    def apply_model(self) -> None:
        settings = self.get_model_settings()
        self.model_settings = settings
        self.adapter = build_adapter_from_settings(settings, self.model_api_key())
        self.guard = None
        if settings.backend != "mock":
            threading.Thread(target=self.run_guard, name="model-guard", daemon=True).start()

    def run_guard(self) -> GuardResult:
        """Check the server; when json_schema is on, prove the grammar is enforced."""
        settings = self.model_settings
        if settings.backend == "mock":
            self.guard = GuardResult(True, "ok", "mock adapter", [])
            return self.guard
        key = self.model_api_key() or None
        result = check_server(settings.normalized_endpoint(), settings.model, api_key=key)
        if result.ok and settings.json_schema:
            result = probe_constrained(
                settings.normalized_endpoint(), settings.model, api_key=key,
                timeout_s=min(settings.timeout_s, 120),
            )
        self.guard = result
        return result

    def constrained_allowed(self) -> bool:
        return self.guard is not None and self.guard.ok and self.guard.constrained_enforced is True

    def get_inference_settings(self) -> InferenceSettings:
        return InferenceSettings.model_validate(self.store.get_setting("inference") or {})

    def put_inference_settings(self, settings: InferenceSettings) -> InferenceSettings:
        self.store.put_setting("inference", settings.model_dump())
        self.apply_inference()
        return settings

    def apply_inference(self) -> None:
        self.inference = self.get_inference_settings()
        for session in self.sessions.values():
            session.display_max_width = self.inference.display_max_width
            session.jpeg_quality = self.inference.jpeg_quality

    def publish_status(self, camera_id: str, status: str, worker: CameraWorker) -> None:
        self.hub.publish(
            camera_id,
            {
                "camera_id": camera_id,
                "status": status,
                "timestamp": datetime.now(UTC).isoformat(),
                "detections": [],
                "events": [],
                "camera_state": worker.session.stats.state,
                "model_error": worker.last_error,
                "guard": self.guard.to_dict() if self.guard else None,
            },
        )

    # ── evidence frames ───────────────────────────────────────────────────────

    def save_evidence_frame(self, frame_hash: str, jpeg: bytes) -> None:
        """Keep the inference frame behind a SafetyEvent, keyed by its evidence.frame_hash."""
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path = self.evidence_dir / f"{frame_hash}.jpg"
            if not path.exists():
                path.write_bytes(jpeg)
        except OSError as exc:
            logger.warning("could not store evidence frame: %s", exc)

    def evidence_frame_path(self, frame_hash: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{16,128}", frame_hash or ""):
            return None
        path = self.evidence_dir / f"{frame_hash}.jpg"
        return path if path.is_file() else None

    # ── measured runs ─────────────────────────────────────────────────────────

    def recorder_for(self, camera_id: str) -> RunRecorder | None:
        return self._recorders.get(camera_id)

    def start_run(self, camera_id: str, name: str, *, notes: str = "") -> dict[str, Any]:
        with self._lock:
            if self._run is not None:
                raise RuntimeError("a run is already recording; stop it first")
            if camera_id not in self.workers:
                raise KeyError(camera_id)
            camera = self.cameras[camera_id]
            settings = self.model_settings
            recorder = RunRecorder(
                adapter_name=getattr(self.adapter, "adapter_name", type(self.adapter).__name__),
                model_version=str(getattr(self.adapter, "model_version", "unknown")),
                source_path=None,
                source_info={
                    "camera_id": camera_id,
                    "source_type": self.sessions[camera_id].kind,
                    "profile": camera.profile,
                    "stream_quality": camera.stream_quality,
                    "masked_url": camera.masked_url,
                    "zones": len(camera.zones),
                    "frame_count": None,
                    "sample_interval_ms": self.inference.interval_ms,
                },
                config={
                    "adapter": settings.backend,
                    "adapter_endpoint": settings.normalized_endpoint(),
                    "model": settings.model,
                    "inference_timeout_seconds": settings.timeout_s,
                    "post_batch": self.inference.post_batch,
                    "max_tokens": settings.max_tokens,
                    "think": settings.think,
                    "json_schema": settings.json_schema,
                    "post_events": self.post_enabled,
                    "backend": self.backend if self.post_enabled else None,
                    "continuous": True,
                    "inference_interval_ms": self.inference.interval_ms,
                    "inference_resolution": [self.inference.width, self.inference.height],
                    "notes": notes,
                },
            )
            recorder.start_tegrastats()
            self._run = {
                "name": _slug(name),
                "camera_id": camera_id,
                "started_at": time.time(),
                "poster_baseline": self.poster.stats(),
                "capture_baseline": dict(self.sessions[camera_id].stats.to_dict()),
            }
            self._recorders[camera_id] = recorder
            return self.run_status()

    def stop_run(self) -> dict[str, Any]:
        with self._lock:
            if self._run is None:
                raise RuntimeError("no run is recording")
            run = self._run
            camera_id = run["camera_id"]
            recorder = self._recorders.pop(camera_id)
            session = self.sessions.get(camera_id)
            capture = session.stats.to_dict() if session else None
            if capture is not None:
                base = run["capture_baseline"]
                capture = {
                    **capture,
                    "frames_decoded_in_run": capture["frames_decoded"] - base.get("frames_decoded", 0),
                    "frames_published_in_run": capture["frames_published"] - base.get("frames_published", 0),
                    "frames_dropped_in_run": capture["frames_dropped"] - base.get("frames_dropped", 0),
                    "reconnects_in_run": capture["reconnects"] - base.get("reconnects", 0),
                    "capture_fps_in_run": (
                        round((capture["frames_published"] - base.get("frames_published", 0))
                              / max(time.time() - run["started_at"], 1e-6), 3)
                    ),
                    "frames_sampled_for_inference": len(recorder.frames),
                }
            worker = self.workers.get(camera_id)
            recorder.extra = {
                "capture": capture,
                "transport": self.poster.stats(),
                "worker": worker.status() if worker else None,
                "server": {
                    "managed": self.model_server.status(),
                    "guard": self.guard.to_dict() if self.guard else None,
                    "reasoning_parser": self.model_settings.reasoning_parser,
                },
            }
            host = platform.node() or "host"
            out_dir = self.reports_dir / host
            out = recorder.write(out_dir / f"{run['name']}.json")
            self._run = None
            return {"recording": False, "written": str(out), "frames": len(recorder.frames)}

    def run_status(self) -> dict[str, Any]:
        run = self._run
        if run is None:
            return {"recording": False}
        recorder = self._recorders.get(run["camera_id"])
        return {
            "recording": True,
            "name": run["name"],
            "camera_id": run["camera_id"],
            "elapsed_s": round(time.time() - run["started_at"], 1),
            "frames": len(recorder.frames) if recorder else 0,
            "events": sum(recorder.events_by_rule.values()) if recorder else 0,
        }

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in sorted(self.reports_dir.glob("*/*.json")):
            if path.name.endswith("_tegrastats.jsonl"):
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("schema") != "run-report-v1":
                continue
            runs.append(
                {
                    "path": str(path),
                    "name": path.stem,
                    "host": path.parent.name,
                    "status": data.get("status"),
                    "started_at": data.get("started_at"),
                    "frames": data.get("frames_processed"),
                    "fps": data.get("frames_per_second"),
                    "model": (data.get("adapter") or {}).get("model_version"),
                    "events": (data.get("events") or {}).get("total"),
                    "inference_p50_ms": ((data.get("latency") or {}).get("inference") or {}).get("p50"),
                }
            )
        return runs

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        cameras = []
        for camera_id, session in self.sessions.items():
            worker = self.workers.get(camera_id)
            camera = self.cameras.get(camera_id)
            cameras.append(
                {
                    **session.status(),
                    "name": camera.name if camera else camera_id,
                    "profile": camera.profile if camera else None,
                    "worker": worker.status() if worker else None,
                }
            )
        return {
            "started_at": self.started_at,
            "backend": self.backend,
            "post_enabled": self.post_enabled,
            "model": {
                **self.model_settings.model_dump(exclude={"api_key"}),
                "endpoint": self.model_settings.normalized_endpoint(),
                "adapter": getattr(self.adapter, "adapter_name", type(self.adapter).__name__),
                "guard": self.guard.to_dict() if self.guard else None,
                "constrained_allowed": self.constrained_allowed(),
            },
            "model_server": self.model_server.status(),
            "inference": self.inference.model_dump(),
            "transport": self.poster.stats(),
            "run": self.run_status(),
            "cameras": cameras,
        }


# ── helpers ───────────────────────────────────────────────────────────────────


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or f"run-{uuid.uuid4().hex[:6]}"


def _build_url(cfg: dict[str, Any], password: str) -> str:
    profile = get_profile(cfg.get("profile") or "generic_rtsp")
    return profile.build_url(
        host=cfg.get("host") or "",
        username=cfg.get("username") or None,
        password=password or None,
        port=int(cfg["port"]) if cfg.get("port") else None,
        channel=int(cfg.get("channel") or 1),
        quality=cfg.get("stream_quality") or "main",
        path=cfg.get("stream_path") or None,
    )


def _validate_url(data: CameraIn, password: str) -> None:
    profile = get_profile(data.profile)
    if not profile.requires_host:
        return
    try:
        profile.build_url(
            host=data.host, username=data.username or None, password=password or None,
            port=data.port, channel=data.channel, quality=data.stream_quality,
            path=data.stream_path or None,
        )
    except CameraConfigError as exc:
        raise ValueError(str(exc)) from exc


def _scale_zones(zones: list[Zone], width: int, height: int) -> list[Zone]:
    """Zones are stored normalised 0..1; the rules work in frame pixels."""
    scaled = []
    for zone in zones:
        pts = zone.polygon
        if pts and max(max(p[0], p[1]) for p in pts) <= 1.0:
            pts = [[p[0] * width, p[1] * height] for p in pts]
        scaled.append(Zone(zone_id=zone.zone_id, type=zone.type, polygon=pts))
    return scaled


def _public_detections(detections: list[dict[str, Any]], width: int, height: int) -> list[dict[str, Any]]:
    out = []
    for det in detections:
        if not isinstance(det, dict):
            continue
        bbox = det.get("bbox")
        norm = None
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                x1, y1, x2, y2 = (float(v) for v in bbox[:4])
                peak = max(x1, y1, x2, y2)
                if peak <= 1.0:
                    norm = [x1, y1, x2 - x1, y2 - y1]
                elif peak > max(width, height) * 1.05 and peak <= 1000:
                    norm = [x1 / 1000, y1 / 1000, (x2 - x1) / 1000, (y2 - y1) / 1000]
                else:
                    norm = [x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height]
                norm = [round(min(max(v, 0.0), 1.0), 4) for v in norm]
            except (TypeError, ValueError):
                norm = None
        out.append(
            {
                "label": det.get("label"),
                "confidence": det.get("confidence"),
                "bbox": norm,
                "ppe": det.get("ppe"),
                "blocking_emergency_path": det.get("blocking_emergency_path"),
            }
        )
    return out


def _resize_jpeg(jpeg: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    image: Image.Image = Image.open(io.BytesIO(jpeg))
    image.load()
    if image.width > width or image.height > height:
        scale = min(width / image.width, height / image.height)
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    if image.mode != "RGB":
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), image.width, image.height
