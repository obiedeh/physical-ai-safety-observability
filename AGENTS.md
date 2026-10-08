# AGENTS.md: physical-ai-safety-observability

Runtime-aware Physical AI safety observability pipeline. Ingests VLM detections from edge
cameras, runs a rule engine, groups events into incidents, and stores evidence chains.

---

## Architecture

```
edge/service.py         ← EdgeService: one CameraWorker thread per enabled camera
                           (latest frame → VLM adapter → rules → AsyncPoster); run recorder
edge/capture.py         ← PyAV CameraSession per camera, native-rate latest-frame slot;
                           Stream (RTSP/HTTP), Usb (V4L2), File (uploads, loop/once),
                           Push (browser), Synthetic sessions
edge/rtsp_url.py        ← pasted RTSP links: parse, strip credentials, rebuild for the decoder
edge/usb_devices.py     ← /dev/video* enumeration with V4L2 ioctls (names, modes)
edge/uploads.py         ← upload validation (type, signature, size), PyAV probe
edge/evidence_label.py  ← source_kind notes and the banner stamped on non-live evidence
api/tls_proxy.py        ← optional HTTPS front door (opt-in) for LAN browser cameras
edge/poster.py          ← AsyncPoster: queue + thread, retries, packet-to-event latency
edge/model_guard.py     ← server check + json_schema canary (refuses reasoning-parser servers)
edge/model_server.py    ← catalog + app-managed Cosmos vLLM container (docker) on Jetson
edge/camera_profiles.py ← vendor profiles (main/sub paths) and connector profiles
                           (rtsp_url, usb, uploaded_video, browser, synthetic);
                           source_kind_for(); edge/probe.py decodes one frame
edge/secrets.py         ← Fernet encryption for stored credentials; edge/redaction.py masks
edge/worker.py          ← file/synthetic worker CLI (unchanged contract)
edge/live_camera.py     ← optional CLI over EdgeService (UI is the primary path)
edge/adapters/          ← VLMAdapter ABC: mock | openai-compatible | cosmos-reason2
rules/policies.py       ← pure rule functions (PPE_MISSING, RESTRICTED_ZONE_ENTRY, ...)
rules/engine.py         ← orchestrates policies → SafetyEvent list
api/                    ← FastAPI: /events /incidents /cameras /metrics /health plus
                           /config/* /models/* /stream/* /live/* /runs/* /runtime/status
api/services/store.py   ← SQLiteStore: thread-safe, Alembic-migrated (0003 adds
                           camera_configs + settings)
web/                    ← Operator UI (Live, Cameras, Model, Runs, Events); built to web/dist
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

# Start API with the UI (build once: cd web && pnpm install && pnpm build)
uvicorn api.main:app --host 0.0.0.0 --port 8080   # cameras/model configured at http://host:8080/

# Run the file/synthetic edge worker once (mock adapter, no backend post)
python -m edge.worker --source examples/sample_source.json --no-post --once

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

- No new top-level packages without explicit approval (approved 2026-10-02: `web/`)
- No new dependencies without explicit approval (approved 2026-10-02: av, Pillow,
  cryptography; opencv stays optional for `edge.worker` file sources)
- Every camera has a `source_kind` (live_rtsp, usb, browser, uploaded_recorded,
  uploaded_generated, synthetic). Workers stamp it on results and SafetyEvents;
  evidence frames from non-live sources get a visible banner. Never drop it.
- Schema changes are additive: camera fields live in the JSON payload with defaults,
  new tables come as Alembic migrations with `if_not_exists`; `tests/test_store_upgrade.py`
  must keep passing. Uploads, certificates and keys live outside the repo (gitignored).
- No secrets, credentials, or real deployment topology in this repo (public).
  Camera passwords and API keys are entered in the UI and Fernet-encrypted in
  SQLite; the key file lives outside the repo. Tests use TEST-NET addresses.
- Constrained (json_schema) runs are enforced in code: `ModelSettings` refuses
  `json_schema` with `reasoning_parser=True`, and `edge/model_guard.py` must
  prove the server honours the grammar before a worker uses it
- `store.py` is the single source of truth for persistence; do not add a second DB or cache
- `rules/policies.py` functions must remain pure (no I/O, no side effects)
- Confidence adjustment lives only in `rules/severity.py`
- All timestamps must be UTC-aware (`datetime.now(UTC)`, not `datetime.utcnow()`)

---

## Known Constraints

- SQLite is the only supported DB. Designed for single-process edge deployments.
- `spatial/calibration.py` is not wired into the main pipeline yet; zones come from the
  camera configuration (normalised 0..1, scaled to the inference frame) or `VideoSource`.
- No authentication on the API; intended for internal/edge network use only.
