"""USB camera listing with a mocked device tree, validation and error wording."""
from __future__ import annotations

import time
import types

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes import config as config_routes
from edge.capture import UsbCameraSession
from edge.config_models import CameraIn
from edge.probe import classify_error
from edge.usb_devices import (
    UsbDevice,
    UsbMode,
    describe_device_error,
    list_usb_devices,
    v4l2_options,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    yield
    for cam in client.get("/config/cameras").json():
        client.delete(f"/config/cameras/{cam['camera_id']}")


def _fake_tree(tmp_path):
    dev, sys_dir = tmp_path / "dev", tmp_path / "sys"
    for node, index, name in (
        ("video0", "0", "Front USB cam"), ("video1", "1", "Front USB cam"),
        ("video2", "0", "Busy cam"), ("video10", "0", "Second cam"),
    ):
        (dev / node).parent.mkdir(parents=True, exist_ok=True)
        (dev / node).write_text("")
        (sys_dir / node).mkdir(parents=True, exist_ok=True)
        (sys_dir / node / "index").write_text(index + "\n")
        (sys_dir / node / "name").write_text(name + "\n")
    (dev / "video-not-a-node").write_text("")
    return dev, sys_dir


def _fake_query(path: str) -> list[UsbMode]:
    if path.endswith("video2"):
        raise OSError(16, "Device or resource busy")
    if path.endswith("video10"):
        return [UsbMode("YUYV", 640, 480, [30.0, 15.0])]
    return [UsbMode("MJPG", 1280, 720, [30.0]), UsbMode("YUYV", 640, 480, [30.0, 15.0])]


def test_list_usb_devices_skips_metadata_nodes_and_reports_errors(tmp_path) -> None:
    dev, sys_dir = _fake_tree(tmp_path)
    devices = list_usb_devices(dev, sys_dir, query_modes=_fake_query)
    expected = [str(dev / "video0"), str(dev / "video2"), str(dev / "video10")]
    assert [d.path for d in devices] == expected
    first = devices[0]
    assert first.name == "Front USB cam" and first.error is None
    assert first.modes[0].to_dict() == {"pixel_format": "MJPG", "width": 1280, "height": 720,
                                        "fps": [30.0]}
    assert "busy" in (devices[1].error or "") and devices[1].modes == []


def test_list_usb_devices_with_no_hardware(tmp_path) -> None:
    (tmp_path / "dev").mkdir()
    assert list_usb_devices(tmp_path / "dev", tmp_path / "sys", query_modes=_fake_query) == []


def test_v4l2_options_and_error_wording() -> None:
    assert v4l2_options(1280, 720, 30) == {"video_size": "1280x720", "framerate": "30"}
    assert v4l2_options(1280, 720, 30, "MJPG") == {
        "video_size": "1280x720", "framerate": "30", "input_format": "mjpeg",
    }
    assert v4l2_options(None, None, 7.5, "yuyv") == {"framerate": "7.5", "input_format": "yuyv422"}
    assert v4l2_options(None, None, None, "WEIRD") == {}
    assert "busy" in describe_device_error(OSError(16, "Device or resource busy"))
    assert "unplugged" in describe_device_error(FileNotFoundError("No such file or directory"))
    assert "video group" in describe_device_error(PermissionError("Permission denied"))
    assert "metadata" in describe_device_error(OSError(25, "Inappropriate ioctl for device"))
    assert classify_error("[Errno 16] Device or resource busy: '/dev/video0'")[0] == "device"
    assert classify_error("[Errno 2] No such file or directory: '/dev/video9'")[0] == "device"


def test_usb_devices_endpoint_uses_patched_lister(monkeypatch) -> None:
    devices = [UsbDevice("/dev/video0", "Front USB cam", [UsbMode("MJPG", 1280, 720, [30.0])])]
    monkeypatch.setattr(config_routes, "usb_lister", lambda: devices)
    body = client.get("/config/usb-devices").json()
    assert body["note"] is None
    assert body["devices"][0]["path"] == "/dev/video0"
    assert body["devices"][0]["modes"][0]["width"] == 1280
    monkeypatch.setattr(config_routes, "usb_lister", list)
    body = client.get("/config/usb-devices").json()
    assert body["devices"] == [] and "No USB camera found" in body["note"]


def test_usb_camera_validation_and_record() -> None:
    with pytest.raises(ValueError, match="/dev/video0"):
        CameraIn(name="Cam", profile="usb")
    with pytest.raises(ValueError, match="/dev/video0"):
        CameraIn(name="Cam", profile="usb", device="/etc/passwd")
    with pytest.raises(ValueError, match="together"):
        CameraIn(name="Cam", profile="usb", device="/dev/video0", capture_width=640)
    created = client.post(
        "/config/cameras",
        json={"name": "Desk cam", "profile": "usb", "device": "/dev/video0",
              "capture_width": 1280, "capture_height": 720, "capture_fps": 30,
              "capture_format": "mjpg", "enabled": False},
    )
    assert created.status_code == 201, created.text
    cam = created.json()
    assert cam["connector"] == "usb" and cam["source_kind"] == "usb"
    assert cam["device"] == "/dev/video0" and cam["capture_fps"] == 30
    assert cam["capture_format"] == "MJPG" and cam["masked_url"] == ""


def test_usb_session_reports_busy_device_clearly(monkeypatch) -> None:
    def fake_open(*args, **kwargs):
        raise OSError(16, "Device or resource busy: '/dev/video0'")

    monkeypatch.setitem(__import__("sys").modules, "av", types.SimpleNamespace(open=fake_open))
    session = UsbCameraSession("cam", "/dev/video0", width=640, height=480, fps=30,
                               reconnect_backoff_s=(0.05,))
    session.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and session.stats.last_error is None:
        time.sleep(0.02)
    session.stop()
    assert session.stats.last_error is not None and "busy" in session.stats.last_error
    assert session.status()["kind"] == "usb"
