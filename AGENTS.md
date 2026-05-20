# AGENTS.md — physical-ai-safety-observability

Runtime-aware Physical AI safety observability pipeline. Ingests VLM detections from edge
cameras, runs a rule engine, groups events into incidents, and stores evidence chains.

---

## Architecture

```
edge/worker.py          ← frame loop: sample → VLM adapter → rules engine → POST /events
edge/adapters/          ← VLMAdapter ABC: mock | openai-compatible | cosmos-reason2
rules/policies.py       ← pure rule functions (PPE_MISSING, RESTRICTED_ZONE_ENTRY, ...)
rules/engine.py         ← orchestrates policies → SafetyEvent list
api/                    ← FastAPI: /events /incidents /cameras /metrics /health
api/services/store.py   ← SQLiteStore: thread-safe, Alembic-migrated
events/                 ← SafetyEvent / Incident schemas + incident grouping logic
evidence/               ← SHA-256 frame hashing + Evidence chain builder
spatial/                ← Zone definitions + ray-cast polygon intersection
telemetry/              ← MetricsRegistry (Prometheus), RuntimeMonitor (p95/p99), JSON logging
replay/                 ← CLI tool: summarize an incident JSON offline
```

---

## Running

```bash
# Install
pip install -e ".[dev]"

# Start API
uvicorn api.main:app --host 0.0.0.0 --port 8080

# Run edge worker (mock adapter, no backend post)
python -m edge.worker --source examples/sample_source.json --no-post

# Full demo (Docker)
docker compose --profile demo up

# Tests  (PYTEST_DISABLE_PLUGIN_AUTOLOAD isolates from system pytest plugins)
make test

# Lint
make lint
```

Config is loaded from `PHYSICAL_AI_CONFIG` env var (JSON file). Falls back to built-in
defaults (mock adapter, `data/observability.sqlite3`).

---

## Rules

| Rule ID | Trigger | Severity |
|---|---|---|
| `PPE_MISSING` | Person without hard_hat or vest | HIGH |
| `RESTRICTED_ZONE_ENTRY` | Person bbox intersects a restricted zone polygon | CRITICAL |
| `HUMAN_ROBOT_PROXIMITY` | Person center within 90px of robot center | HIGH |
| `BLOCKED_EMERGENCY_PATH` | Pallet/cart/box with `blocking_emergency_path: true` | MEDIUM |
| `UNSAFE_EVENT_SUMMARY` | VLM-emitted `unsafe_event` label | LOW |

---

## Adapter Contract

Implement `VLMAdapter.analyze_frame(frame_context) -> dict` returning:
```json
{
  "adapter_name": "...",
  "model_version": "...",
  "detections": [{"label": "person|robot|...", "confidence": 0.9, "bbox": [x1,y1,x2,y2], "ppe": {...}}]
}
```

---

## Hard Rules

- No new top-level packages without explicit approval
- No new dependencies without explicit approval  
- No secrets, credentials, or real deployment topology in this repo (public)
- `store.py` is the single source of truth for persistence — do not add a second DB or cache
- `rules/policies.py` functions must remain pure (no I/O, no side effects)
- Confidence adjustment lives only in `rules/severity.py`
- All timestamps must be UTC-aware (`datetime.now(UTC)`, not `datetime.utcnow()`)

---

## Known Constraints

- SQLite is the only supported DB. Designed for single-process edge deployments.
- `spatial/calibration.py` is not wired into the main pipeline yet — zones come from `VideoSource`.
- `evidence/hashing.py:hash_file` is defined but unused by the main pipeline.
- No authentication on the API — intended for internal/edge network use only.
