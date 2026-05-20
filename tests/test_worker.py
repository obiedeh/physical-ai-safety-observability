from edge.source_loader import load_source
from edge.worker import iter_frame_contexts, person_ppe_feedback, run_worker


def test_worker_generates_events_without_backend_post() -> None:
    source = load_source("examples/sample_source.json")

    events = run_worker(source=source, backend="http://127.0.0.1:8080", post_events=False)

    rule_ids = {event["rule_id"] for event in events}
    assert "PPE_MISSING" in rule_ids
    assert "RESTRICTED_ZONE_ENTRY" in rule_ids
    assert "BLOCKED_EMERGENCY_PATH" in rule_ids


def test_worker_continuous_mode_can_be_bounded_for_tests() -> None:
    source = load_source("examples/sample_source.json")

    events = run_worker(
        source=source,
        backend="http://127.0.0.1:8080",
        post_events=False,
        continuous=True,
        feedback_interval_seconds=0.01,
        max_cycles=3,
    )

    assert events


def test_person_ppe_feedback_messages() -> None:
    assert person_ppe_feedback([]) == "No Person Detected"
    assert (
        person_ppe_feedback([{"label": "person", "ppe": {"hard_hat": False, "vest": True}}])
        == "Person Detected with No PPE"
    )
    assert (
        person_ppe_feedback([{"label": "person", "ppe": {"hard_hat": True, "vest": True}}])
        == "Person Detected with PPE"
    )


def test_continuous_frame_iteration_reports_one_capture_per_interval() -> None:
    source = load_source("examples/sample_source.json")

    frames = list(iter_frame_contexts(source, continuous=True, max_cycles=3))

    assert [frame["frame_id"] for frame in frames] == ["sample-0001"] * 3
