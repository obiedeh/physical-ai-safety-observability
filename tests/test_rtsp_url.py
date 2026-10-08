"""Pasted RTSP links: parsing, credential stripping and redaction end to end."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import config as config_routes
from api.services.edge import edge_service
from edge.camera_profiles import CameraConfigError
from edge.config_models import CameraIn
from edge.redaction import REDACTOR
from edge.rtsp_url import parse_rtsp_url, with_credentials

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    yield
    for cam in client.get("/config/cameras").json():
        client.delete(f"/config/cameras/{cam['camera_id']}")


def test_parse_strips_embedded_credentials() -> None:
    parsed = parse_rtsp_url("rtsp://viewer:p%40ss%3Aword@192.0.2.9:8554/live/ch1?x=1#frag")
    assert (parsed.scheme, parsed.host, parsed.port) == ("rtsp", "192.0.2.9", 8554)
    assert parsed.path == "/live/ch1?x=1"
    assert (parsed.username, parsed.password) == ("viewer", "p@ss:word")
    assert parsed.stripped_url == "rtsp://192.0.2.9:8554/live/ch1?x=1"
    assert parsed.has_credentials


def test_parse_without_credentials_and_default_ports() -> None:
    plain = parse_rtsp_url("  RTSP://cam.example.test/stream  ")
    assert plain.stripped_url == "rtsp://cam.example.test/stream"
    assert plain.port == 554 and not plain.has_credentials
    assert parse_rtsp_url("rtsps://192.0.2.30:7441/AbC123").port == 7441
    assert parse_rtsp_url("rtsps://192.0.2.30/x").port == 322


@pytest.mark.parametrize(
    "bad", ["", "http://192.0.2.9/stream", "rtsp://", "rtsp:///path", "rtsp://host:notaport/x"]
)
def test_parse_rejects_bad_links_without_echoing_them(bad: str) -> None:
    with pytest.raises(CameraConfigError) as exc:
        parse_rtsp_url(bad)
    assert "notaport" not in str(exc.value)


def test_with_credentials_round_trip_quotes_special_characters() -> None:
    url = with_credentials("rtsp://192.0.2.9:554/a?b=1", "us er", "p@ss/w:rd")
    assert url == "rtsp://us%20er:p%40ss%2Fw%3Ard@192.0.2.9:554/a?b=1"
    assert parse_rtsp_url(url).password == "p@ss/w:rd"
    assert with_credentials("rtsp://h/x", None, None) == "rtsp://h/x"


def test_camera_in_moves_link_credentials_into_fields() -> None:
    cam = CameraIn(name="Gate", profile="rtsp_url", source_url="rtsp://u:pw@192.0.2.9/s1")
    assert cam.source_url == "rtsp://192.0.2.9/s1"
    assert (cam.username, cam.password, cam.host, cam.port) == ("u", "pw", "192.0.2.9", 554)
    typed = CameraIn(name="Gate", profile="rtsp_url", source_url="rtsp://u:pw@192.0.2.9/s1",
                     username="typed", password="typed-pw")
    assert (typed.username, typed.password) == ("typed", "typed-pw")
    plain = CameraIn(name="Open", profile="rtsp_url", source_url="rtsps://192.0.2.30:7441/tok")
    assert plain.password == "" and plain.port == 7441
    with pytest.raises(ValueError, match="rtsp://"):
        CameraIn(name="Bad", profile="rtsp_url", source_url="http://192.0.2.9/s1")


def test_api_never_returns_or_stores_the_raw_link() -> None:
    raw = "rtsp://viewer:link-secret-9@192.0.2.9:8554/live/ch1"
    created = client.post(
        "/config/cameras",
        json={"name": "Pasted", "profile": "rtsp_url", "source_url": raw, "enabled": False},
    )
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["source_url"] == "rtsp://192.0.2.9:8554/live/ch1"
    assert cam["masked_url"] == "rtsp://***:***@192.0.2.9:8554/live/ch1"
    assert cam["username"] == "viewer" and cam["has_password"] is True
    assert (cam["host"], cam["port"]) == ("192.0.2.9", 8554)
    assert cam["connector"] == "rtsp_url" and cam["source_kind"] == "live_rtsp"
    assert "link-secret-9" not in created.text and "password" not in cam

    cfg = edge_service.store.get_camera_config(cam["camera_id"])
    assert cfg is not None
    assert cfg["source_url"] == "rtsp://192.0.2.9:8554/live/ch1"
    assert cfg["password_enc"].startswith("enc:v1:")
    assert "link-secret-9" not in json.dumps(cfg)
    assert edge_service.feed_url(cam["camera_id"]) == raw
    assert "link-secret-9" not in REDACTOR.redact(f"failed opening {raw}")

    updated = client.put(
        f"/config/cameras/{cam['camera_id']}",
        json={"name": "Pasted", "profile": "rtsp_url",
              "source_url": "rtsp://192.0.2.9:8554/live/ch1", "username": "viewer",
              "password": "", "enabled": False},
    )
    assert updated.status_code == 200 and updated.json()["has_password"] is True
    assert edge_service.feed_url(cam["camera_id"]) == raw


def test_validation_error_for_a_bad_link_does_not_echo_it() -> None:
    bad = "http://viewer:oops-secret@192.0.2.9/not-rtsp"
    res = client.post(
        "/config/cameras", json={"name": "Bad", "profile": "rtsp_url", "source_url": bad}
    )
    assert res.status_code == 422
    assert "oops-secret" not in res.text
    assert "rtsp://" in res.json()["detail"][0]["msg"]


def test_test_endpoint_probes_pasted_link_with_stored_password(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_probe(url: str, **kwargs):
        from edge.probe import ProbeResult

        seen["url"] = url
        return ProbeResult(ok=True, stage="ok", masked_url="masked")

    monkeypatch.setattr(config_routes, "probe_stream", fake_probe)
    cam = client.post(
        "/config/cameras",
        json={"name": "Pasted", "profile": "rtsp_url",
              "source_url": "rtsp://u:probe-secret@192.0.2.9/s1", "enabled": False},
    ).json()
    res = client.post(f"/config/cameras/{cam['camera_id']}/test")
    assert res.status_code == 200 and res.json()["ok"] is True
    assert seen["url"] == "rtsp://u:probe-secret@192.0.2.9/s1"
    assert "probe-secret" not in res.text
    res = client.post(
        "/config/cameras/test",
        json={"name": "Pasted", "profile": "rtsp_url", "source_url": "rtsp://192.0.2.9/s1",
              "username": "u", "password": "", "camera_id": cam["camera_id"]},
    )
    assert res.status_code == 200 and seen["url"] == "rtsp://u:probe-secret@192.0.2.9/s1"
    res = client.post(
        "/config/cameras/test",
        json={"name": "Pasted", "profile": "rtsp_url", "source_url": "rtsp://192.0.2.10/s1",
              "username": "u", "password": "", "camera_id": cam["camera_id"]},
    )
    assert res.json()["ok"] is False and "stored password" in res.json()["error"]
