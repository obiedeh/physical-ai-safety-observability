from edge.source_loader import load_source
from edge.worker import run_worker


def test_worker_generates_events_without_backend_post() -> None:
    source = load_source("examples/sample_source.json")

    events = run_worker(source=source, backend="http://127.0.0.1:8080", post_events=False)

    rule_ids = {event["rule_id"] for event in events}
    assert "PPE_MISSING" in rule_ids
    assert "RESTRICTED_ZONE_ENTRY" in rule_ids
    assert "BLOCKED_EMERGENCY_PATH" in rule_ids

