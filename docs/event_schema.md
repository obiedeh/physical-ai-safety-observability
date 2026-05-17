# Event Schema

Every safety event includes:

- `event_id`
- `camera_id`
- `timestamp`
- `rule_id`
- `severity`
- `confidence`
- `human_review_required`
- `runtime_context`
- `evidence`

See `events/schemas.py` for the typed Pydantic source of truth and
`examples/sample_event.json` for a concrete payload.

