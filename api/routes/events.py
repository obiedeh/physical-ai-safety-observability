from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from api.services.store import store
from events.schemas import Incident, PersonPPEFeedback, SafetyEvent
from telemetry.metrics import metrics

router = APIRouter()


@router.post("/events", response_model=SafetyEvent)
def ingest_event(event: SafetyEvent) -> SafetyEvent:
    return store.add_event(event)


@router.get("/events", response_model=list[SafetyEvent])
def list_events() -> list[SafetyEvent]:
    return store.list_events()


@router.get("/incidents", response_model=list[Incident])
def list_incidents() -> list[Incident]:
    return store.list_incidents()


@router.get("/incidents/{incident_id:path}", response_model=Incident)
def get_incident(incident_id: str) -> Incident:
    incident = store.get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@router.post("/feedback", response_model=PersonPPEFeedback)
def ingest_feedback(feedback: PersonPPEFeedback) -> PersonPPEFeedback:
    return store.add_feedback(feedback)


@router.get("/feedback", response_model=list[PersonPPEFeedback])
def list_feedback() -> list[PersonPPEFeedback]:
    return store.list_feedback()


@router.get("/metrics", response_class=PlainTextResponse)
def get_metrics() -> str:
    return metrics.render_prometheus()
