"""Camera CRUD, enable/disable, connection test and credential handling via the API."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import config as config_routes
from api.services.edge import edge_service
from api.services.store import store

client = TestClient(app)

TAPO = {
    "name": "Cell A entry",
    "profile": "tapo",
    "host": "192.0.2.20",
    "username": "viewer",
    "password": "s3cret-pass",
    "stream_quality": "sub",
    "zones": [{"zone_id": "gate", "type": "restricted",
               "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]}],
}


@pytest.fixture(autouse=True)
def _clean():
    yield
    for cam in client.get("/config/cameras").json():
        client.delete(f"/config/cameras/{cam['camera_id']}")


def test_profiles_cover_required_vendors() -> None:
    types = {p["model_type"] for p in client.get("/config/profiles").json()}
    assert {"tapo", "hikvision", "dahua", "amcrest", "axis", "reolink", "unifi_protect",
            "generic_rtsp", "http_mjpeg", "browser_webrtc"} <= types


def test_create_get_update_delete() -> None:
    created = client.post("/config/cameras", json=TAPO)
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["camera_id"] == "cell-a-entry"
    assert cam["port"] == 554
    assert cam["effective_stream_path"] == "/stream2"
    assert cam["has_password"] is True and "password" not in cam
    assert cam["masked_url"] == "rtsp://***:***@192.0.2.20:554/stream2"
    assert len(cam["zones"]) == 1
    # Camera is running (a stream session exists even though the host is a TEST-NET address).
    assert cam["runtime"] is not None

    updated = client.put(
        f"/config/cameras/{cam['camera_id']}",
        json={**TAPO, "password": "", "stream_quality": "main", "name": "Cell A"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["has_password"] is True
    assert updated.json()["effective_stream_path"] == "/stream1"

    assert client.get(f"/config/cameras/{cam['camera_id']}").json()["name"] == "Cell A"
    assert client.delete(f"/config/cameras/{cam['camera_id']}").status_code == 204
    assert client.get(f"/config/cameras/{cam['camera_id']}").status_code == 404
    assert edge_service.session(cam["camera_id"]) is None


def test_password_encrypted_at_rest_and_never_returned() -> None:
    cam = client.post("/config/cameras", json=TAPO).json()
    raw = store.get_camera_config(cam["camera_id"])
    assert raw is not None and raw["password_enc"].startswith("enc:v1:")
    assert "s3cret-pass" not in raw["password_enc"]
    assert "s3cret-pass" not in client.get("/config/cameras").text
    assert "s3cret-pass" not in client.get("/runtime/status").text
    # The runtime can still rebuild the credentialed URL.
    assert edge_service.feed_url(cam["camera_id"]) == "rtsp://viewer:s3cret-pass@192.0.2.20:554/stream2"


def test_enable_disable_stops_and_starts_session() -> None:
    cam = client.post("/config/cameras", json=TAPO).json()
    off = client.post(f"/config/cameras/{cam['camera_id']}/enabled", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert edge_service.session(cam["camera_id"]) is None
    on = client.post(f"/config/cameras/{cam['camera_id']}/enabled", json={"enabled": True})
    assert on.json()["enabled"] is True
    assert edge_service.session(cam["camera_id"]) is not None


def test_validation_errors() -> None:
    assert client.post("/config/cameras", json={**TAPO, "profile": "nope"}).status_code == 422
    assert client.post("/config/cameras", json={**TAPO, "host": ""}).status_code == 422
    r = client.post("/config/cameras", json={"name": "h", "profile": "hikvision", "host": "192.0.2.3"})
    assert r.status_code == 422


def test_test_connection_uses_stored_credentials(monkeypatch) -> None:
    seen: dict = {}

    def fake_probe(url: str, transport: str) -> dict:
        seen["url"] = url
        return {"ok": False, "stage": "auth", "error": "Authentication failed", "masked_url": "m"}

    monkeypatch.setattr(config_routes, "_probe", fake_probe)
    r = client.post("/config/cameras/test", json=TAPO)
    assert r.status_code == 200 and r.json()["stage"] == "auth"
    assert seen["url"] == "rtsp://viewer:s3cret-pass@192.0.2.20:554/stream2"
    cam = client.post("/config/cameras", json=TAPO).json()
    r = client.post(f"/config/cameras/{cam['camera_id']}/test")
    assert r.status_code == 200
    assert seen["url"] == "rtsp://viewer:s3cret-pass@192.0.2.20:554/stream2"


def test_legacy_registration_redacts_source_uri() -> None:
    r = client.post(
        "/cameras",
        json={"camera_id": "legacy", "name": "L", "source_uri": "rtsp://u:pw@192.0.2.9/s"},
    )
    assert r.status_code == 200
    assert r.json()["source_uri"] == "rtsp://***:***@192.0.2.9/s"
    assert "pw@" not in client.get("/cameras").text
