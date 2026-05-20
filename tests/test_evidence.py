from datetime import UTC, datetime

from events.schemas import RuntimeContext
from evidence.evidence_chain import build_evidence, redact_uri_credentials
from evidence.hashing import hash_text


def test_hash_text_is_deterministic() -> None:
    assert hash_text("frame-1") == hash_text("frame-1")
    assert hash_text("frame-1") != hash_text("frame-2")


def test_redact_uri_credentials_removes_rtsp_userinfo() -> None:
    assert (
        redact_uri_credentials("rtsp://user:secret@192.168.1.146:554/stream1")
        == "rtsp://192.168.1.146:554/stream1"
    )


def test_build_evidence_redacts_source_uri_credentials() -> None:
    evidence = build_evidence(
        frame_context={
            "camera_id": "front-door",
            "frame_id": "frame-1",
            "timestamp": datetime.now(UTC),
            "source_uri": "rtsp://user:secret@192.168.1.146:554/stream1",
        },
        adapter_name="cosmos_reason2",
        model_version="nvidia/cosmos-reason2-8b",
        rule_version="safety-policy-v1",
        runtime_context=RuntimeContext(),
        detections=[],
    )

    assert evidence.source_uri == "rtsp://192.168.1.146:554/stream1"
