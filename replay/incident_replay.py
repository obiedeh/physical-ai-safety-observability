import argparse

from edge.source_loader import load_json
from events.schemas import Incident


def summarize_incident(incident: Incident) -> str:
    review_required = any(event.human_review_required for event in incident.timeline)
    runtime_states = sorted({event.runtime_context.runtime_status for event in incident.timeline})
    lines = [
        f"incident_id: {incident.incident_id}",
        f"camera_id: {incident.camera_id}",
        f"events: {len(incident.timeline)}",
        f"highest_severity: {incident.highest_severity}",
        f"runtime_states: {', '.join(runtime_states)}",
        f"operator_review_required: {review_required}",
        "timeline:",
    ]
    for event in incident.timeline:
        lines.append(
            f"- {event.timestamp.isoformat()} {event.rule_id} "
            f"{event.severity} confidence={event.confidence:.2f} "
            f"frame_hash={event.evidence.frame_hash}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay and summarize a safety incident.")
    parser.add_argument("--incident", required=True, help="Path to incident JSON")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    incident = Incident.model_validate(load_json(args.incident))
    print(summarize_incident(incident))


if __name__ == "__main__":
    main()

