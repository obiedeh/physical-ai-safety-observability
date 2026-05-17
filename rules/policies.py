from dataclasses import dataclass
from math import hypot
from typing import Any

from events.schemas import Severity
from spatial.zones import Zone, bbox_center, bbox_intersects_polygon

RULE_VERSION = "safety-policy-v1"


@dataclass(frozen=True)
class RuleFinding:
    rule_id: str
    severity: Severity
    confidence: float
    summary: str
    detections: list[dict[str, Any]]


def _detections_by_label(detections: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [item for item in detections if item.get("label") == label]


def ppe_missing(detections: list[dict[str, Any]]) -> list[RuleFinding]:
    people = _detections_by_label(detections, "person")
    missing = [
        person
        for person in people
        if not person.get("ppe", {}).get("hard_hat") or not person.get("ppe", {}).get("vest")
    ]
    if not missing:
        return []
    confidence = max(float(item.get("confidence", 0.5)) for item in missing)
    return [
        RuleFinding(
            rule_id="PPE_MISSING",
            severity=Severity.HIGH,
            confidence=confidence,
            summary="Person detected without required PPE.",
            detections=missing,
        )
    ]


def restricted_zone_entry(
    detections: list[dict[str, Any]], zones: list[Zone]
) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    people = _detections_by_label(detections, "person")
    restricted_zones = [zone for zone in zones if zone.type == "restricted"]
    for zone in restricted_zones:
        matches = [
            person
            for person in people
            if "bbox" in person and bbox_intersects_polygon(tuple(person["bbox"]), zone.points())
        ]
        if matches:
            findings.append(
                RuleFinding(
                    rule_id="RESTRICTED_ZONE_ENTRY",
                    severity=Severity.CRITICAL,
                    confidence=max(float(item.get("confidence", 0.5)) for item in matches),
                    summary=f"Person entered restricted zone {zone.zone_id}.",
                    detections=matches,
                )
            )
    return findings


def human_robot_proximity(detections: list[dict[str, Any]], threshold_px: float = 90) -> list[RuleFinding]:
    people = _detections_by_label(detections, "person")
    robots = _detections_by_label(detections, "robot")
    matches: list[dict[str, Any]] = []
    for person in people:
        if "bbox" not in person:
            continue
        px, py = bbox_center(tuple(person["bbox"]))
        for robot in robots:
            if "bbox" not in robot:
                continue
            rx, ry = bbox_center(tuple(robot["bbox"]))
            if hypot(px - rx, py - ry) <= threshold_px:
                matches.extend([person, robot])
    if not matches:
        return []
    return [
        RuleFinding(
            rule_id="HUMAN_ROBOT_PROXIMITY",
            severity=Severity.HIGH,
            confidence=max(float(item.get("confidence", 0.5)) for item in matches),
            summary="Human detected within unsafe proximity of robot.",
            detections=matches,
        )
    ]


def blocked_emergency_path(detections: list[dict[str, Any]]) -> list[RuleFinding]:
    blocked = [
        item
        for item in detections
        if item.get("label") in {"pallet", "cart", "box"} and item.get("blocking_emergency_path")
    ]
    if not blocked:
        return []
    return [
        RuleFinding(
            rule_id="BLOCKED_EMERGENCY_PATH",
            severity=Severity.MEDIUM,
            confidence=max(float(item.get("confidence", 0.5)) for item in blocked),
            summary="Object appears to block an emergency path.",
            detections=blocked,
        )
    ]


def unsafe_event_summary(detections: list[dict[str, Any]]) -> list[RuleFinding]:
    summaries = [item for item in detections if item.get("label") == "unsafe_event"]
    if not summaries:
        return []
    return [
        RuleFinding(
            rule_id="UNSAFE_EVENT_SUMMARY",
            severity=Severity.LOW,
            confidence=max(float(item.get("confidence", 0.5)) for item in summaries),
            summary=summaries[0].get("summary", "Unsafe condition requires operator review."),
            detections=summaries,
        )
    ]

