from __future__ import annotations

import logging

import pytest

from edge import probe as probe_mod
from edge.probe import classify_error, probe_stream
from edge.redaction import Redactor, install_logging_filter, mask_url
from edge.secrets import SecretBox, SecretKeyMismatch
from evidence.evidence_chain import redact_uri_credentials


def test_secret_box(tmp_path) -> None:
    box = SecretBox(key_file=tmp_path / "k")
    token = box.encrypt("hunter2")
    assert token.startswith("enc:v1:") and "hunter2" not in token
    assert box.decrypt(token) == "hunter2"
    assert (tmp_path / "k").stat().st_mode & 0o777 == 0o600
    with pytest.raises(SecretKeyMismatch):
        SecretBox(key_file=tmp_path / "other").decrypt(token)


def test_mask_url_and_query_secrets() -> None:
    assert mask_url("rtsp://admin:pw@192.0.2.5:554/s1") == "rtsp://***:***@192.0.2.5:554/s1"
    assert mask_url("http://h/api?user=a&password=zzz") == "http://h/api?user=a&password=***"
    assert redact_uri_credentials("rtsp://u:p@192.0.2.1:554/x?token=abc") == "rtsp://192.0.2.1:554/x?token=***"


def test_redactor_and_logging_filter() -> None:
    r = Redactor()
    r.register("p@ss word")
    out = r.redact("open rtsp://user:p%40ss%20word@cam/stream failed with p@ss word")
    assert "p@ss" not in out and "p%40ss" not in out and "rtsp://***:***@cam/stream" in out

    from edge.redaction import REDACTOR

    REDACTOR.register("topsecret99")
    logger = logging.getLogger("redaction-test")
    install_logging_filter(logger)
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger.addHandler(Capture())
    logger.setLevel(logging.INFO)
    logger.info("connecting with %s", "topsecret99")
    assert seen and "topsecret99" not in seen[0]


@pytest.mark.parametrize(
    "message,stage",
    [
        ("401 Unauthorized", "auth"),
        ("404 Not Found", "path"),
        ("Connection refused", "reachability"),
        ("Connection timed out", "timeout"),
        ("Invalid data found when processing input", "codec"),
    ],
)
def test_classify_error(message: str, stage: str) -> None:
    assert classify_error(message)[0] == stage


def test_probe_unreachable_and_fake_decode(monkeypatch) -> None:
    monkeypatch.setattr(probe_mod, "tcp_reachable", lambda h, p, timeout=2.0: "Connection refused")
    r = probe_stream("rtsp://u:p@192.0.2.1:554/stream1", timeout_s=1)
    assert not r.ok and r.stage == "reachability" and "p@" not in (r.error or "")

    import sys
    import types

    from PIL import Image

    class Frame:
        def to_image(self):
            return Image.new("RGB", (1280, 720))

    class Codec:
        name = "h264"

    class Stream:
        type = "video"
        codec_context = Codec()
        average_rate = 15

    class Container:
        streams = (Stream(),)

        def decode(self, video=0):
            yield Frame()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "av", types.SimpleNamespace(open=lambda *a, **k: Container()))
    monkeypatch.setattr(probe_mod, "tcp_reachable", lambda h, p, timeout=2.0: None)
    ok = probe_stream("rtsp://u:p@cam:554/stream1", timeout_s=2)
    assert ok.ok and (ok.width, ok.height) == (1280, 720) and ok.codec == "h264"
    assert ok.to_dict()["thumbnail_data_url"].startswith("data:image/jpeg;base64,")
