"""Video uploads: validation, size limit, playback (loop / once) and camera wiring."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import config as config_routes
from api.services.edge import edge_service
from edge.capture import FileCameraSession
from edge.uploads import check_size, safe_filename, upload_id_for

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    yield
    for cam in client.get("/config/cameras").json():
        client.delete(f"/config/cameras/{cam['camera_id']}")
    for up in client.get("/config/uploads").json():
        client.delete(f"/config/uploads/{up['id']}")


def _upload(data: bytes, filename: str = "clip.mp4", kind: str = "recorded"):
    return client.post(
        f"/config/uploads?filename={filename}&source_kind={kind}",
        content=data, headers={"Content-Type": "application/octet-stream"},
    )


def test_upload_registers_file_next_to_the_database(make_mp4) -> None:
    data = make_mp4().read_bytes()
    res = _upload(data, "My Clip (1).mp4", "generated")
    assert res.status_code == 201, res.text
    rec = res.json()
    assert rec["filename"] == "My_Clip_1.mp4" and rec["source_kind"] == "generated"
    assert rec["sha256"] == hashlib.sha256(data).hexdigest()
    assert (rec["width"], rec["height"], rec["fps"], rec["frames"]) == (64, 48, 25.0, 10)
    assert rec["codec"] == "mpeg4" and rec["size_bytes"] == len(data)
    assert rec["id"] == upload_id_for("My_Clip_1.mp4", rec["sha256"])
    store = edge_service.store
    path = store.upload_dir / rec["stored_name"]
    assert path.is_file() and path.read_bytes() == data
    assert store.upload_dir.parent.samefile(Path(store.database_path).parent)
    assert client.get(f"/config/uploads/{rec['id']}").json()["camera_ids"] == []
    assert [u["id"] for u in client.get("/config/uploads").json()] == [rec["id"]]


def test_upload_rejects_wrong_type_signature_kind_and_empty(make_mp4) -> None:
    data = make_mp4().read_bytes()
    assert _upload(data, "clip.avi").status_code == 415
    assert _upload(b"\x00" * 4096, "clip.mp4").status_code == 415
    assert _upload(b"\x00" * 4096, "clip.mkv").status_code == 415
    assert _upload(data, "clip.mp4", "fake").status_code == 422
    assert _upload(b"", "clip.mp4").status_code == 400
    assert _upload(data[:64] + b"\x00" * 2000, "clip.mp4").status_code == 422
    assert client.get("/config/uploads").json() == []
    assert list(edge_service.store.upload_dir.glob(".upload-*")) == []


def test_upload_size_limit_is_enforced(make_mp4, monkeypatch) -> None:
    data = make_mp4().read_bytes()
    monkeypatch.setattr(config_routes, "UPLOAD_MAX_BYTES", len(data) - 1)
    res = _upload(data)
    assert res.status_code == 413 and "limit" in res.json()["detail"]
    monkeypatch.setattr(config_routes, "UPLOAD_MAX_BYTES", len(data))
    assert _upload(data).status_code == 201
    with pytest.raises(Exception, match="limit"):
        check_size(2_000_000_001, 2_000_000_000)


def test_upload_wires_into_a_camera_and_delete_is_guarded(make_mp4) -> None:
    rec = _upload(make_mp4().read_bytes(), "road.mp4", "recorded").json()
    missing = client.post(
        "/config/cameras",
        json={"name": "Replay", "profile": "uploaded_video", "upload_id": "nope"},
    )
    assert missing.status_code == 422 and "not found" in missing.text
    created = client.post(
        "/config/cameras",
        json={"name": "Replay", "profile": "uploaded_video", "upload_id": rec["id"],
              "playback": "once"},
    )
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["connector"] == "upload" and cam["source_kind"] == "uploaded_recorded"
    assert cam["playback"] == "once" and cam["upload"]["filename"] == rec["filename"]
    assert client.get(f"/config/uploads/{rec['id']}").json()["camera_ids"] == [cam["camera_id"]]
    blocked = client.delete(f"/config/uploads/{rec['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["camera_ids"] == [cam["camera_id"]]
    deadline = time.monotonic() + 5
    state = None
    while time.monotonic() < deadline:
        state = client.get(f"/config/cameras/{cam['camera_id']}").json()["runtime"]
        if state and state["state"] == "ended":
            break
        time.sleep(0.05)
    assert state is not None and state["state"] == "ended"
    assert state["frames_decoded"] == 10
    assert state["frames_published"] + state["frames_dropped"] == 10
    assert client.post(f"/config/cameras/{cam['camera_id']}/restart").status_code == 200
    assert client.delete(f"/config/cameras/{cam['camera_id']}").status_code == 204
    path = edge_service.store.upload_dir / rec["stored_name"]
    assert path.exists()
    assert client.delete(f"/config/uploads/{rec['id']}").status_code == 204
    assert not path.exists()
    assert client.get(f"/config/uploads/{rec['id']}").status_code == 404


def test_file_session_loops_at_native_rate(make_mp4) -> None:
    path = make_mp4(frames=10, fps=25)
    session = FileCameraSession("replay", path, loop=True)
    started = time.monotonic()
    session.start()
    deadline = started + 6
    while time.monotonic() < deadline and session.stats.loops < 2:
        time.sleep(0.02)
    elapsed = time.monotonic() - started
    session.stop()
    assert session.stats.loops >= 2 and session.stats.frames_published >= 20
    assert session.stats.source_fps == 25.0 and session.stats.codec == "mpeg4"
    assert elapsed >= 0.7  # two passes of 10 frames at 25 fps cannot finish faster
    assert session.status()["kind"] == "file" and session.status()["loops"] >= 2


def test_file_session_plays_once_then_ends(make_mp4) -> None:
    path = make_mp4(frames=10, fps=25)
    session = FileCameraSession("replay", path, loop=False)
    session.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and session.running:
        time.sleep(0.02)
    assert session.stats.state == "ended"
    assert session.stats.frames_decoded == 10 and session.stats.loops == 0
    assert session.stats.frames_published + session.stats.frames_dropped == 10
    missing = FileCameraSession("replay", path.with_name("missing.mp4"), loop=True)
    missing.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and missing.running:
        time.sleep(0.02)
    assert missing.stats.state == "error" and "cannot open" in (missing.stats.last_error or "")


def test_safe_filename() -> None:
    assert safe_filename("../../etc/passwd.mp4") == "passwd.mp4"
    assert safe_filename("Dash Cam 2026-10-08 #1.MOV") == "Dash_Cam_2026-10-08_1.mov"
    assert safe_filename(".mkv") == "video.mkv"
