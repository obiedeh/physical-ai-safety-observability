import json
import sqlite3
from pathlib import Path
from threading import Lock

from api.models.camera import Camera, CameraRegistration
from api.services.migrations import run_migrations
from events.lifecycle import can_group_event, merge_event_into_incident
from events.schemas import Incident, PersonPPEFeedback, SafetyEvent
from runtime_settings import load_settings
from telemetry.metrics import metrics


class SQLiteStore:
    def __init__(
        self, database_path: str | None = None, incident_window_seconds: int | None = None
    ) -> None:
        settings = load_settings()
        self.database_path = database_path or settings.app.database_path
        self.incident_window_seconds = (
            incident_window_seconds or settings.app.incident_window_seconds
        )
        self._lock = Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        if self.database_path != ":memory:":
            run_migrations(self.database_path)
            return
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    registered_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    incident_id TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_events_incident ON events(incident_id);
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    grouping_severity TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_grouping
                    ON incidents(camera_id, rule_id, grouping_severity, updated_at);
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    frame_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp);
                """
            )

    def reset(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute("DELETE FROM events")
                connection.execute("DELETE FROM incidents")
                connection.execute("DELETE FROM cameras")
                connection.execute("DELETE FROM feedback")

    def register_camera(self, registration: CameraRegistration) -> Camera:
        camera = Camera(**registration.model_dump())
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO cameras(camera_id, payload, registered_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(camera_id) DO UPDATE SET
                        payload=excluded.payload,
                        registered_at=excluded.registered_at
                    """,
                    (
                        camera.camera_id,
                        camera.model_dump_json(),
                        camera.registered_at.isoformat(),
                    ),
                )
        return camera

    def list_cameras(self) -> list[Camera]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM cameras ORDER BY registered_at"
                ).fetchall()
            return [Camera.model_validate_json(row["payload"]) for row in rows]

    def add_feedback(self, feedback: PersonPPEFeedback) -> PersonPPEFeedback:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO feedback(feedback_id, camera_id, frame_id, message, timestamp, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(feedback_id) DO UPDATE SET
                        message=excluded.message,
                        payload=excluded.payload
                    """,
                    (
                        feedback.feedback_id,
                        feedback.camera_id,
                        feedback.frame_id,
                        feedback.message,
                        feedback.timestamp.isoformat(),
                        feedback.model_dump_json(),
                    ),
                )
        return feedback

    def list_feedback(self) -> list[PersonPPEFeedback]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM feedback ORDER BY timestamp"
                ).fetchall()
            return [PersonPPEFeedback.model_validate_json(row["payload"]) for row in rows]

    def add_event(self, event: SafetyEvent) -> SafetyEvent:
        with self._lock:
            with self._connect() as connection:
                incident = self._find_groupable_incident(connection, event)
                incident = merge_event_into_incident(incident, event)
                connection.execute(
                    """
                    INSERT INTO incidents(
                        incident_id, camera_id, rule_id, grouping_severity,
                        opened_at, updated_at, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        updated_at=excluded.updated_at,
                        payload=excluded.payload
                    """,
                    (
                        incident.incident_id,
                        incident.camera_id,
                        incident.rule_id or "",
                        str(incident.grouping_severity or ""),
                        incident.opened_at.isoformat(),
                        incident.updated_at.isoformat(),
                        incident.model_dump_json(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO events(event_id, camera_id, rule_id, severity, timestamp, incident_id, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        incident_id=excluded.incident_id,
                        payload=excluded.payload
                    """,
                    (
                        event.event_id,
                        event.camera_id,
                        event.rule_id,
                        event.severity,
                        event.timestamp.isoformat(),
                        event.incident_id,
                        event.model_dump_json(),
                    ),
                )
        metrics.observe_event(event)
        return event

    def list_events(self) -> list[SafetyEvent]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM events ORDER BY timestamp"
                ).fetchall()
            return [SafetyEvent.model_validate_json(row["payload"]) for row in rows]

    def list_incidents(self) -> list[Incident]:
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM incidents ORDER BY updated_at DESC"
                ).fetchall()
            return [Incident.model_validate_json(row["payload"]) for row in rows]

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM incidents WHERE incident_id = ?",
                    (incident_id,),
                ).fetchone()
            if row is None:
                return None
            return Incident.model_validate_json(row["payload"])

    def _find_groupable_incident(
        self, connection: sqlite3.Connection, event: SafetyEvent
    ) -> Incident | None:
        rows = connection.execute(
            """
            SELECT payload FROM incidents
            WHERE camera_id = ? AND rule_id = ? AND grouping_severity = ?
            ORDER BY updated_at DESC
            LIMIT 5
            """,
            (event.camera_id, event.rule_id, str(event.severity)),
        ).fetchall()
        for row in rows:
            incident = Incident.model_validate(json.loads(row["payload"]))
            if can_group_event(incident, event, self.incident_window_seconds):
                return incident
        return None


store = SQLiteStore()
