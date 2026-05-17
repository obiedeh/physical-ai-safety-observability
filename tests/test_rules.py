from datetime import UTC, datetime

from events.schemas import RuntimeContext
from rules.engine import SafetyPolicyEngine
from spatial.zones import Zone


def test_rules_engine_generates_required_findings() -> None:
    engine = SafetyPolicyEngine(
        zones=[
            Zone(
                zone_id="robot-cell-a",
                type="restricted",
                polygon=[[120, 60], [260, 60], [260, 260], [120, 260]],
            )
        ]
    )
    frame_context = {
        "camera_id": "cell-a-camera-1",
        "source_uri": "file://sample",
        "timestamp": datetime.now(UTC),
        "frame_id": "frame-1",
    }
    analysis = {
        "adapter_name": "mock_vlm",
        "model_version": "mock-vlm-structured-v1",
        "detections": [
            {
                "label": "person",
                "confidence": 0.93,
                "bbox": [130, 85, 185, 235],
                "ppe": {"hard_hat": False, "vest": True},
            },
            {"label": "robot", "confidence": 0.91, "bbox": [180, 90, 250, 240]},
        ],
    }

    events = engine.evaluate(
        frame_context=frame_context,
        analysis=analysis,
        runtime_context=RuntimeContext(),
    )

    rule_ids = {event.rule_id for event in events}
    assert "PPE_MISSING" in rule_ids
    assert "RESTRICTED_ZONE_ENTRY" in rule_ids
    assert "HUMAN_ROBOT_PROXIMITY" in rule_ids

