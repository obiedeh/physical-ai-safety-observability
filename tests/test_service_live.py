"""EdgeService end to end: synthetic camera → mock adapter → rules → async poster → run report.

Also proves video keeps flowing while inference is unavailable, that
constrained mode is blocked until the guard has passed, and that nothing
credentialed reaches logs, status or the report.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from api.services.store import SQLiteStore
from edge.adapters.base import VLMAdapter
from edge.capture import SyntheticCameraSession
from edge.config_models import CameraIn, InferenceSettings, ModelSettings
from edge.model_guard import GuardResult
from edge.poster import AsyncPoster, PostJob
from edge.secrets import SecretBox
from edge.service import EdgeService


class NoPPEAdapter(VLMAdapter):
    adapter_name = "test"
    model_version = "test-1"

    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        w = frame_context["metadata"]["width"]
        h = frame_context["metadata"]["height"]
        return {
            "adapter_name": self.adapter_name,
            "model_version": self.model_version,
            "detections": [
                {"label": "person", "confidence": 0.9, "bbox": [w * 0.4, h * 0.4, w * 0.6, h * 0.9],
                 "ppe": {"hard_hat": False, "vest": True}}
            ],
        }


class BrokenAdapter(VLMAdapter):
    adapter_name = "broken"
    model_version = "x"

    def analyze_frame(self, frame_context: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionError("vLLM at rtsp://u:pw@nowhere is down")


class FakeBackend:
    """Collects what the poster would send; counts batches."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.feedback: list[dict] = []
        self.batches = 0
        self.lock = threading.Lock()


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = SQLiteStore(database_path=str(tmp_path / "svc.sqlite3"), incident_window_seconds=900)
    svc = EdgeService(
        store, secrets=SecretBox(key_file=tmp_path / "k"),
        backend="http://127.0.0.1:1", post_enabled=True, reports_dir=tmp_path / "reports",
    )
    backend = FakeBackend()

    def fake_post(job: PostJob):  # replaces the HTTP call; returns (ok, latency_ms)
        with backend.lock:
            if job.kind == "feedback":
                backend.feedback.append(job.payload)
            elif job.kind == "events_batch":
                backend.batches += 1
                backend.events.extend(job.payload)
            else:
                backend.events.append(job.payload)
        return True, 1.5

    monkeypatch.setattr(svc.poster, "_post", fake_post)
    svc.store.put_setting("model", ModelSettings(backend="mock").model_dump())
    svc.store.put_setting("inference", InferenceSettings(interval_ms=100, width=320, height=180).model_dump())
    svc.start()
    svc.backend_capture = backend  # type: ignore[attr-defined]
    try:
        yield svc
    finally:
        svc.stop()


def _wait(predicate, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_async_poster_never_blocks_and_counts_drops() -> None:
    poster = AsyncPoster("http://127.0.0.1:1", max_queue=3)
    for i in range(5):  # not started: queue fills, oldest dropped
        poster.enqueue(PostJob("event", {"i": i}, time.monotonic()))
    assert poster.queue_depth == 3 and poster.dropped == 2
    stats = poster.stats()
    assert stats["dropped"] == 2 and stats["packet_to_event_ms"] == {"n": 0}


def test_synthetic_camera_to_events_to_async_backend(service: EdgeService) -> None:
    backend = service.backend_capture  # type: ignore[attr-defined]
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic", zones=[
        {"zone_id": "z", "type": "restricted", "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]}
    ]))
    session = service.session(cam.camera_id)
    assert isinstance(session, SyntheticCameraSession)
    assert _wait(lambda: session.stats.frames_published >= 3)
    service.adapter = NoPPEAdapter()
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("model") == "test-1")
    assert _wait(lambda: len(backend.events) >= 2)
    rules = {e["rule_id"] for e in backend.events}
    assert "PPE_MISSING" in rules and "RESTRICTED_ZONE_ENTRY" in rules
    assert backend.batches >= 1  # posted as one batch per frame
    # The frame behind the event is kept, keyed by evidence.frame_hash.
    frame_hash = backend.events[0]["evidence"]["frame_hash"]
    assert service.evidence_frame_path(frame_hash) is not None
    assert service.evidence_frame_path("../etc/passwd") is None
    assert any(f["message"] == "Person Detected with No PPE" for f in backend.feedback)
    latest = service.hub.latest[cam.camera_id]
    assert latest["status"] == "ok" and latest["detections"][0]["bbox"][0] == pytest.approx(0.4, abs=0.01)
    status = service.status()
    assert status["transport"]["posted"] >= 2
    assert status["transport"]["packet_to_event_ms"]["n"] >= 1
    assert status["cameras"][0]["fps"] > 0


def test_model_outage_keeps_video_and_reports_unavailable(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    session = service.session(cam.camera_id)
    service.adapter = BrokenAdapter()
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("status") == "inference_unavailable")
    before = session.stats.frames_published
    time.sleep(0.4)
    assert session.stats.frames_published > before
    worker = service.workers[cam.camera_id]
    assert worker.inference_failures >= 1
    assert "pw@" not in (worker.last_error or "")
    assert service.backend_capture.events == []  # type: ignore[attr-defined]


def test_constrained_mode_blocked_until_guard_passes(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    service.model_settings = ModelSettings(backend="cosmos-reason2", json_schema=True)
    service.adapter = NoPPEAdapter()
    service.guard = GuardResult(False, "constrained", "server ignored schema", [], False)
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("status") == "blocked_constrained_mode")
    assert service.backend_capture.events == []  # type: ignore[attr-defined]
    service.guard = GuardResult(True, "ok", "enforced", [], True)
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("status") == "ok")


def test_run_recording_writes_v1_report_with_capture_and_transport(service: EdgeService, tmp_path) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    service.adapter = NoPPEAdapter()
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("status") == "ok")
    status = service.start_run(cam.camera_id, "Live Demo Run", notes="unit test")
    assert status["recording"] is True
    assert _wait(lambda: service.run_status()["frames"] >= 3)
    result = service.stop_run()
    path = result["written"]
    data = json.loads(Path(path).read_text())
    assert data["schema"] == "run-report-v1"
    assert data["status"] == "complete"
    assert data["frames_processed"] >= 3
    assert data["config"]["inference_interval_ms"] == 100
    assert data["source"]["source_type"] == "synthetic"
    assert data["capture"]["frames_published_in_run"] >= 1
    assert data["capture"]["capture_fps_in_run"] > 0
    assert data["latency"]["capture_to_result"]["n"] >= 3
    assert data["transport"]["posted"] >= 1
    assert data["latency"]["packet_to_event"]["n"] >= 1
    assert data["events"]["total"] >= 1
    assert data["server"]["guard"] is None or "message" in data["server"]["guard"]
    assert "pw@" not in json.dumps(data)
    runs = service.list_runs()
    assert runs and runs[0]["name"] == "live-demo-run"
    with pytest.raises(RuntimeError):
        service.stop_run()


def test_disable_and_delete(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    assert service.session(cam.camera_id) is not None
    service.set_enabled(cam.camera_id, False)
    assert service.session(cam.camera_id) is None
    service.set_enabled(cam.camera_id, True)
    assert service.session(cam.camera_id) is not None
    assert service.delete_camera(cam.camera_id)
    assert service.session(cam.camera_id) is None and service.get_camera(cam.camera_id) is None


def test_run_refuses_when_model_server_not_ready_and_aborts_on_outage(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    service.model_settings = ModelSettings(backend="cosmos-reason2", endpoint="http://127.0.0.1:1")
    service.adapter = NoPPEAdapter()
    with pytest.raises(RuntimeError, match="not ready"):
        service.start_run(cam.camera_id, "should refuse")
    # Back to a working model: the run starts, then the server "goes down".
    service.model_settings = ModelSettings(backend="mock")
    service.outage_abort_s = 0.5
    assert _wait(lambda: service.hub.latest.get(cam.camera_id, {}).get("status") == "ok")
    service.start_run(cam.camera_id, "outage run")
    assert _wait(lambda: service.run_status()["frames"] >= 1)
    service.adapter = BrokenAdapter()
    assert _wait(lambda: service.run_status().get("recording") is False, timeout=8)
    runs = service.list_runs()
    report = json.loads(Path(runs[-1]["path"]).read_text())
    assert report["status"] == "failed" and "model server down" in report["error"]
    kinds = [e["kind"] for e in report["server"]["events_during_run"]]
    assert "outage started" in kinds
    assert "pw@" not in json.dumps(report)


def test_stop_endpoint_requires_confirm() -> None:
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    assert client.post("/models/server/stop", json={}).status_code == 409
    r = client.post("/models/server/stop", json={"confirm": True, "reason": "test"})
    assert r.status_code == 200 and r.json()["state"] == "stopped"
