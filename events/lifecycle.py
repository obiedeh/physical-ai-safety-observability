from datetime import timedelta

from events.schemas import Incident, SafetyEvent, Severity

SEVERITY_RANK = {
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


def incident_id_for(event: SafetyEvent) -> str:
    if event.incident_id:
        return event.incident_id
    bucket = event.timestamp.strftime("%Y%m%dT%H%M%S")
    return f"{event.camera_id}:{event.rule_id}:{event.severity}:{bucket}"


def can_group_event(incident: Incident, event: SafetyEvent, window_seconds: int) -> bool:
    if incident.camera_id != event.camera_id:
        return False
    if incident.rule_id != event.rule_id:
        return False
    if incident.grouping_severity != event.severity:
        return False
    return abs(event.timestamp - incident.updated_at) <= timedelta(seconds=window_seconds)


_MAX_TIMELINE_EVENTS = 100


def merge_event_into_incident(incident: Incident | None, event: SafetyEvent) -> Incident:
    if incident is None:
        incident_id = incident_id_for(event)
        event.incident_id = incident_id
        return Incident(
            incident_id=incident_id,
            camera_id=event.camera_id,
            rule_id=event.rule_id,
            grouping_severity=event.severity,
            opened_at=event.timestamp,
            updated_at=event.timestamp,
            highest_severity=event.severity,
            event_ids=[event.event_id],
            timeline=[event],
        )

    event.incident_id = incident.incident_id
    incident.updated_at = max(incident.updated_at, event.timestamp)
    if SEVERITY_RANK[event.severity] > SEVERITY_RANK[incident.highest_severity]:
        incident.highest_severity = event.severity
    incident.event_ids.append(event.event_id)
    incident.timeline.append(event)
    incident.timeline.sort(key=lambda item: item.timestamp)
    if len(incident.timeline) > _MAX_TIMELINE_EVENTS:
        incident.timeline = incident.timeline[-_MAX_TIMELINE_EVENTS:]
    return incident
