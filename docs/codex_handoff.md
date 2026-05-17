# Codex Handoff: Physical AI Safety Observability Platform

## Mission

Turn this repository from a conceptual architecture into a runnable, production-grade, edge-first Physical AI observability platform.

This is NOT a toy computer vision dashboard.

The system must support:

- edge-first deployment
- multimodal inference adapters
- structured safety events
- runtime-aware confidence
- evidence traceability
- operational observability
- future Jetson deployment
- future cloud/hybrid scaling

The primary goal is:

```text
camera/video input
    -> edge inference adapter
    -> safety rules engine
    -> evidence event
    -> API ingestion
    -> incident timeline
    -> observability metrics
```

The pipeline is the product.

---

# Required Repository Structure

```text
api/
  main.py
  routes/
  models/
  services/

edge/
  worker.py
  frame_sampler.py
  source_loader.py
  adapters/

rules/
  engine.py
  policies.py
  severity.py

telemetry/
  metrics.py
  runtime.py
  logging.py

events/
  schemas.py
  lifecycle.py

evidence/
  evidence_chain.py
  hashing.py

spatial/
  zones.py
  calibration.py

replay/
  incident_replay.py

configs/
examples/
docs/
tests/
```

---

# Backend Requirements

Build a FastAPI backend.

Required endpoints:

```text
GET  /health
GET  /ready
POST /cameras
GET  /cameras
POST /events
GET  /events
GET  /incidents
GET  /incidents/{incident_id}
GET  /metrics
```

The backend must:

- accept structured event ingestion
- maintain incident timelines
- expose metrics
- support replay workflows later
- use typed Pydantic models

---

# Edge Worker Requirements

The worker must:

1. load a camera/video source
2. simulate or sample frames
3. call a VLM adapter
4. evaluate safety rules
5. generate structured events
6. POST events to the backend
7. emit runtime telemetry

Required execution:

```bash
python -m edge.worker \
  --source examples/sample_source.json \
  --backend http://127.0.0.1:8080
```

Do NOT require a real camera initially.

RTSP support should be modular.

---

# VLM Adapter Requirements

Create adapter abstraction.

Base interface:

```python
class VLMAdapter:
    def analyze_frame(self, frame_context):
        pass
```

Required adapters:

```text
mock_vlm.py
openai_compatible.py
```

The architecture must NOT hardwire:

- Cosmos
- Gemma
- Ollama
- vLLM

Adapters must remain replaceable.

---

# Safety Rules Engine

Required rules:

```text
PPE_MISSING
RESTRICTED_ZONE_ENTRY
HUMAN_ROBOT_PROXIMITY
BLOCKED_EMERGENCY_PATH
UNSAFE_EVENT_SUMMARY
```

Every event must include:

```json
{
  "event_id": "...",
  "camera_id": "...",
  "timestamp": "...",
  "rule_id": "...",
  "severity": "low|medium|high|critical",
  "confidence": 0.0,
  "human_review_required": true,
  "runtime_context": {},
  "evidence": {}
}
```

---

# Runtime-Aware Confidence

This is a core differentiator.

The system must include runtime state awareness:

- latency
- queue depth
- dropped frames
- GPU memory pressure
- runtime degradation
- thermal pressure hooks

Example:

```json
{
  "event_confidence": 0.82,
  "runtime_status": "degraded",
  "human_review_required": true
}
```

Do NOT assume model output is always trustworthy.

---

# Evidence Chain

Every event must preserve:

- frame hash
- timestamps
- adapter name
- model version
- telemetry snapshot
- rule version
- source URI

This transforms the system from:

```text
AI alerts
```

into:

```text
Operational evidence pipeline
```

---

# Spatial Awareness

Support configurable restricted zones.

Example:

```json
{
  "zone_id": "robot-cell-a",
  "type": "restricted",
  "polygon": [[0,0], [100,0], [100,100], [0,100]]
}
```

Rules must support polygon intersection logic.

---

# Replay System

Create replay skeleton:

```bash
python -m replay.incident_replay \
  --incident examples/sample_incident.json
```

Replay output should summarize:

- incident timeline
- evidence
- severity escalation
- runtime degradation
- operator review recommendation

---

# Metrics and Observability

Expose Prometheus-style metrics.

Required metrics:

```text
events_total
critical_events_total
frames_processed_total
frames_dropped_total
inference_latency_ms
rule_eval_latency_ms
backend_post_latency_ms
```

Structured logging required.

---

# Deployment Profiles

Prepare for:

```text
local
jetson
edge-cluster
cloud-hybrid
```

Do NOT tightly couple deployment assumptions.

---

# Testing Requirements

Required tests:

- health endpoint
- event ingestion
- rules engine
- evidence hashing
- worker event generation

Commands that must pass:

```bash
pytest
ruff check .
```

---

# Docker Requirements

Provide:

```bash
docker compose up --build
```

Services:

- api
- edge-worker

---

# CI Requirements

GitHub Actions must:

- install dependencies
- run Ruff
- run pytest

Avoid heavyweight GPU dependencies in CI.

---

# Documentation Requirements

Create:

```text
architecture.md
deployment_local.md
deployment_jetson.md
safety_policy_model.md
event_schema.md
evidence_chain.md
roadmap.md
```

---

# Critical Architectural Constraints

Do NOT:

- build a fake AI demo
- hardcode one model vendor
- prioritize UI over pipeline
- tightly couple components
- assume cloud-only deployment
- skip evidence traceability
- skip runtime telemetry

Do:

- build replaceable interfaces
- keep systems observable
- preserve operational evidence
- support future Jetson deployment
- maintain deterministic rule evaluation
- treat runtime state as part of safety confidence

---

# Final Goal

The repository should become:

```text
Runtime-Aware Physical AI Observability Platform
```

not:

```text
another AI camera demo
```

The end state should feel like deployable infrastructure, not a hackathon prototype.
