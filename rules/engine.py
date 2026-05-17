from typing import Any

from events.schemas import RuntimeContext, SafetyEvent
from evidence.evidence_chain import build_evidence
from rules.policies import (
    RULE_VERSION,
    blocked_emergency_path,
    human_robot_proximity,
    ppe_missing,
    restricted_zone_entry,
    unsafe_event_summary,
)
from rules.severity import adjust_confidence, require_review
from spatial.zones import Zone


class SafetyPolicyEngine:
    def __init__(self, zones: list[Zone] | None = None) -> None:
        self.zones = zones or []

    def evaluate(
        self,
        *,
        frame_context: dict[str, Any],
        analysis: dict[str, Any],
        runtime_context: RuntimeContext,
    ) -> list[SafetyEvent]:
        detections = analysis.get("detections", [])
        findings = [
            *ppe_missing(detections),
            *restricted_zone_entry(detections, self.zones),
            *human_robot_proximity(detections),
            *blocked_emergency_path(detections),
            *unsafe_event_summary(detections),
        ]
        events: list[SafetyEvent] = []
        for finding in findings:
            confidence = adjust_confidence(finding.confidence, runtime_context)
            evidence = build_evidence(
                frame_context=frame_context,
                adapter_name=analysis.get("adapter_name", "unknown"),
                model_version=analysis.get("model_version", "unknown"),
                rule_version=RULE_VERSION,
                runtime_context=runtime_context,
                detections=finding.detections,
            )
            events.append(
                SafetyEvent(
                    camera_id=frame_context["camera_id"],
                    timestamp=frame_context["timestamp"],
                    rule_id=finding.rule_id,
                    severity=finding.severity,
                    confidence=confidence,
                    human_review_required=require_review(
                        finding.severity, confidence, runtime_context
                    ),
                    runtime_context=runtime_context,
                    evidence=evidence,
                    summary=finding.summary,
                )
            )
        return events

