"""``source_kind`` on cameras, live results, events, evidence frames and run reports."""
from __future__ import annotations

import io
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import app
from api.services.store import SQLiteStore
from edge.camera_profiles import CAMERA_PROFILES, SOURCE_KINDS, source_kind_for
from edge.config_models import CameraIn, InferenceSettings, ModelSettings, UploadRecord
from edge.evidence_label import evidence_note, stamp_evidence
from edge.poster import PostJob
from edge.secrets import SecretBox
from edge.service import EdgeService
from edge.uploads import probe_video_file, sha256_of
from tests.test_service_live import NoPPEAdapter

client = TestClient(app)


def test_every_profile_maps_to_a_known_source_kind() -> None:
    kinds = {p: source_kind_for(p) for p in CAMERA_PROFILES}
    assert set(kinds.values()) <= set(SOURCE_KINDS)
    assert kinds["tapo"] == kinds["generic_rtsp"] == kinds["http_mjpeg"] == "live_rtsp"
    assert kinds["rtsp_url"] == "live_rtsp" and kinds["usb"] == "usb"
    assert kinds["browser_webrtc"] == "browser" and kinds["synthetic"] == "synthetic"
    assert source_kind_for("uploaded_video", "recorded") == "uploaded_recorded"
    assert source_kind_for("uploaded_video", "generated") == "uploaded_generated"


def test_evidence_is_stamped_for_non_live_sources_only() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), (40, 40, 40)).save(buf, format="JPEG")
    jpeg = buf.getvalue()
    assert stamp_evidence(jpeg, "live_rtsp") == jpeg and stamp_evidence(jpeg, None) == jpeg
    stamped = stamp_evidence(jpeg, "uploaded_generated")
    assert stamped != jpeg
    top = Image.open(io.BytesIO(stamped)).crop((0, 0, 320, 8)).convert("RGB")
    assert max(top.tobytes()) > 60  # banner is visibly drawn over the dark frame
    assert evidence_note("synthetic") and evidence_note("usb") is None


def test_ingested_events_carry_source_kind() -> None:
    event = {
        "camera_id": "cam-ingest", "rule_id": "PPE_MISSING", "severity": "high",
        "confidence": 0.9, "human_review_required": True, "summary": "test",
        "source_kind": "usb",
        "evidence": {"frame_hash": "abc", "source_uri": "usb:///dev/video0", "adapter_name": "t",
                     "model_version": "t", "rule_version": "1", "captured_at": "2026-10-08T00:00:00Z"},
    }
    stored = client.post("/events", json=event).json()
    assert stored["source_kind"] == "usb"
    listed = [e for e in client.get("/events").json() if e["event_id"] == stored["event_id"]]
    assert listed and listed[0]["source_kind"] == "usb"
    without = client.post("/events", json={**event, "source_kind": None}).json()
    assert without["source_kind"] is None


class _Capture:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.lock = threading.Lock()


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = SQLiteStore(database_path=str(tmp_path / "svc.sqlite3"), incident_window_seconds=900)
    svc = EdgeService(store, secrets=SecretBox(key_file=tmp_path / "k"),
                      backend="http://127.0.0.1:1", post_enabled=True,
                      reports_dir=tmp_path / "reports")
    captured = _Capture()

    def fake_post(job: PostJob):
        with captured.lock:
            if job.kind == "events_batch":
                captured.events.extend(job.payload)
            elif job.kind == "event":
                captured.events.append(job.payload)
        return True, 1.0

    monkeypatch.setattr(svc.poster, "_post", fake_post)
    svc.store.put_setting("model", ModelSettings(backend="mock").model_dump())
    svc.store.put_setting(
        "inference", InferenceSettings(interval_ms=100, width=320, height=180).model_dump()
    )
    svc.start()
    svc.adapter = NoPPEAdapter()
    svc.captured = captured  # type: ignore[attr-defined]
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


def test_synthetic_events_results_and_runs_are_labelled(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Demo", profile="synthetic"))
    captured = service.captured  # type: ignore[attr-defined]
    assert _wait(lambda: len(captured.events) >= 1)
    event = captured.events[0]
    assert event["source_kind"] == "synthetic"
    assert "not a live camera" in event["evidence"]["evidence_note"]
    assert service.evidence_frame_path(event["evidence"]["frame_hash"]) is not None
    def latest() -> dict:
        value = service.hub.latest
        return value() if callable(value) else value

    assert _wait(lambda: latest().get(cam.camera_id) is not None)
    assert latest()[cam.camera_id]["source_kind"] == "synthetic"
    assert service.status()["cameras"][0]["source_kind"] == "synthetic"
    service.start_run(cam.camera_id, "label-check")
    time.sleep(0.3)
    written = service.stop_run()["written"]
    report = json.loads(Path(written).read_text(encoding="utf-8"))
    assert report["source"]["source_kind"] == "synthetic"
    assert "not a live camera" in report["source"]["evidence_note"]


def test_uploaded_generated_footage_is_labelled(service: EdgeService, make_mp4) -> None:
    path = make_mp4(frames=50, fps=25)
    service.store.upload_dir.mkdir(parents=True, exist_ok=True)
    stored = service.store.upload_dir / "clip-abc.mp4"
    shutil.copy(path, stored)
    info = probe_video_file(stored)
    service.store.add_upload(UploadRecord(
        id="clip-abc", filename="clip.mp4", stored_name=stored.name, content_type="video/mp4",
        size_bytes=stored.stat().st_size, sha256=sha256_of(stored), source_kind="generated",
        **info.to_dict(),
    ))
    cam = service.create_camera(
        CameraIn(name="Replay", profile="uploaded_video", upload_id="clip-abc", playback="loop")
    )
    assert cam.source_kind == "uploaded_generated" and cam.upload is not None
    captured = service.captured  # type: ignore[attr-defined]
    assert _wait(lambda: len(captured.events) >= 1)
    event = captured.events[0]
    assert event["source_kind"] == "uploaded_generated"
    assert event["evidence"]["evidence_note"].startswith("GENERATED FOOTAGE")
    session = service.session(cam.camera_id)
    assert session is not None and session.kind == "file"
    assert service.status()["cameras"][0]["source_kind"] == "uploaded_generated"


def test_browser_camera_events_are_live_and_unstamped(service: EdgeService) -> None:
    cam = service.create_camera(CameraIn(name="Browser", profile="browser_webrtc"))
    push = service.push_session(cam.camera_id)
    assert push is not None
    push.push_image(Image.new("RGB", (320, 180), (10, 10, 10)))
    captured = service.captured  # type: ignore[attr-defined]
    assert _wait(lambda: len(captured.events) >= 1)
    event = captured.events[0]
    assert event["source_kind"] == "browser"
    assert event["evidence"]["evidence_note"] is None
