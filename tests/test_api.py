from fastapi.testclient import TestClient

from api.main import app
from api.services.store import store
from events.schemas import SafetyEvent
from edge.source_loader import load_json
from telemetry.metrics import metrics


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    ready = client.get("/ready")
    assert response.status_code == 200
    assert ready.status_code == 200
    assert response.json() == {"status": "ok"}


def test_event_ingestion_creates_incident() -> None:
    store.reset()
    metrics.reset()
    client = TestClient(app)
    payload = load_json("examples/sample_event.json")

    response = client.post("/events", json=payload)

    assert response.status_code == 200
    event = SafetyEvent.model_validate(response.json())
    incidents = client.get("/incidents").json()
    assert event.rule_id == "PPE_MISSING"
    assert incidents[0]["camera_id"] == "cell-a-camera-1"
    assert incidents[0]["rule_id"] == "PPE_MISSING"
    assert incidents[0]["grouping_severity"] == "high"
    assert incidents[0]["event_ids"] == ["sample-event-1"]


def test_events_incidents_and_metrics_endpoints() -> None:
    store.reset()
    metrics.reset()
    client = TestClient(app)
    payload = load_json("examples/sample_event.json")

    client.post("/events", json=payload)

    events = client.get("/events")
    incidents = client.get("/incidents")
    metrics_response = client.get("/metrics")

    assert events.status_code == 200
    assert incidents.status_code == 200
    assert metrics_response.status_code == 200
    assert len(events.json()) == 1
    assert len(incidents.json()) == 1
    assert "events_total 1.0" in metrics_response.text
    assert "latency_p95_ms" in metrics_response.text


def test_incident_grouping_uses_camera_rule_severity_and_window() -> None:
    store.reset()
    metrics.reset()
    client = TestClient(app)
    first = load_json("examples/sample_event.json")
    second = {**first, "event_id": "sample-event-2", "timestamp": "2026-01-01T00:05:00Z"}
    third = {
        **first,
        "event_id": "sample-event-3",
        "severity": "critical",
        "timestamp": "2026-01-01T00:06:00Z",
    }

    client.post("/events", json=first)
    client.post("/events", json=second)
    client.post("/events", json=third)

    incidents = client.get("/incidents").json()
    event_counts = sorted(len(incident["event_ids"]) for incident in incidents)
    assert len(incidents) == 2
    assert event_counts == [1, 2]


def test_feedback_ingestion_and_listing() -> None:
    store.reset()
    client = TestClient(app)
    payload = {
        "camera_id": "cell-a-camera-1",
        "frame_id": "frame-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": "Person Detected with PPE",
        "detections": [
            {"label": "person", "ppe": {"hard_hat": True, "vest": True}},
        ],
    }

    response = client.post("/feedback", json=payload)
    listed = client.get("/feedback")

    assert response.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["message"] == "Person Detected with PPE"
