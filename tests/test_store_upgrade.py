"""A database written by the previous main opens unchanged after the connector migration.

``tests/fixtures/store_main.sql`` is a dump of a database created by the code
on ``main`` before the video-feed connectors existed (Alembic head 0003),
with seven cameras, model and inference settings. ``store_main.expected.json``
holds what that code returned for them. The test loads the dump, runs the
current migrations (0004 adds ``uploads``) and checks every camera, secret,
URL and setting comes back identical, with the new fields at their defaults.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from api.services.store import SQLiteStore
from edge.camera_profiles import CameraConfigError
from edge.secrets import SecretBox
from edge.service import EdgeService

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "store_main.expected.json").read_text())


@pytest.fixture
def legacy_db(tmp_path) -> str:
    db = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript((FIXTURES / "store_main.sql").read_text())
    conn.commit()
    conn.close()
    return str(db)


def test_fixture_is_from_the_old_schema(legacy_db) -> None:
    conn = sqlite3.connect(legacy_db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()
    assert "uploads" not in tables and "camera_configs" in tables
    assert version == "0003_camera_configs_and_settings"
    assert len(EXPECTED["cameras"]) == 7


def test_cameras_and_settings_survive_the_upgrade(legacy_db) -> None:
    SQLiteStore(database_path=legacy_db)  # runs Alembic to head
    store2 = SQLiteStore(database_path=legacy_db)  # idempotent
    conn = sqlite3.connect(legacy_db)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0004_uploads"
    conn.close()
    svc = EdgeService(store2, secrets=SecretBox(key=EXPECTED["secret_key"]),
                      backend="http://127.0.0.1:1", post_enabled=False)
    cameras = {c.camera_id: c for c in svc.list_cameras()}
    assert list(cameras) == [c["camera_id"] for c in EXPECTED["cameras"]]
    for expected in EXPECTED["cameras"]:
        got = cameras[expected["camera_id"]].model_dump()
        for key, value in expected.items():
            assert got[key] == value, (expected["camera_id"], key)
        assert got["source_url"] == "" and got["device"] == "" and got["upload_id"] == ""
        assert got["capture_format"] == "" and got["playback"] == "loop" and got["upload"] is None
        connector = {"browser_webrtc": "browser", "synthetic": "synthetic"}.get(
            expected["profile"], "network"
        )
        assert got["connector"] == connector
        assert got["source_kind"] == {"browser": "browser", "synthetic": "synthetic"}.get(
            connector, "live_rtsp"
        )
        record = svc.get_camera(expected["camera_id"])
        assert record is not None and record.model_dump() == got
    for camera_id, secret in EXPECTED["camera_secrets"].items():
        cfg = store2.get_camera_config(camera_id)
        assert cfg is not None
        assert svc.secrets.decrypt(cfg.get("password_enc") or "") == secret
    for camera_id, url in EXPECTED["feed_urls"].items():
        if url.startswith("ERROR:"):
            with pytest.raises(CameraConfigError):
                svc.feed_url(camera_id)
        else:
            assert svc.feed_url(camera_id) == url
    assert svc.get_model_settings().model_dump() == EXPECTED["model"]
    assert svc.model_api_key() == EXPECTED["model_api_key"]
    assert svc.get_inference_settings().model_dump() == EXPECTED["inference"]
    assert store2.list_uploads() == []
