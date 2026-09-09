# Physical AI Safety Observability

**Runtime safety layer for robots and industrial workcells: structured safety events, an operator review API, and telemetry hooks. This is an engineering scaffold. No hardware or model performance has been measured yet.**

The system turns camera or video input, safety rules, runtime telemetry, and model outputs into safety events an operator can review. The goal is operational review, not demo object detection. Nothing here acts autonomously.

## Status at a Glance

| Layer | State | What exists | What does not exist yet |
|---|---|---|---|
| Event model and API | Implemented | FastAPI backend for health, camera registration, event ingestion, incident timelines and metrics; SQLite persistence; Alembic migrations; OpenAPI docs | Operator dashboard |
| Safety policy engine | Implemented | PPE, restricted zone, proximity risk and unsafe-event rules over structured detections | Zone geometry from camera calibration |
| Edge worker | Implemented | Frame sampling from synthetic, video-file and RTSP-style sources; adapter interface for models | Live camera deployment |
| Model adapters | Mock plus adapter paths | Deterministic mock VLM adapter; OpenAI-compatible and Cosmos-Reason2 adapter paths with hardened response parsing | Any measured run against a real model endpoint |
| Telemetry | Hooks implemented | Latency p95 and p99, event counts, memory pressure, queue depth, dropped frames, runtime snapshots | Any committed measurement from those hooks |
| Jetson path | Configuration only | `configs/jetson.json` and a deployment note | Latency, memory or sustained-runtime artifacts on a Jetson |
| Evidence chain | Implemented | Hashing and evidence-chain helpers under `evidence/` | Artifacts produced through them |

There are no measured numbers in this repository. The `artifacts/` directories hold placeholders. When a run is committed it will carry device, date, inputs and hashes, following the same rule as the sibling repositories.

## Architecture

```text
Camera / Video Source
        |
        v
Edge Worker -> VLM Adapter -> Safety Policy Engine -> FastAPI Backend
        |                                                |
        v                                                v
 Runtime Telemetry                              Operator/Event APIs
```

Diagrams: [system](docs/diagrams/system-architecture.mmd), [runtime flow](docs/diagrams/runtime-flow.mmd), [data flow](docs/diagrams/data-flow.mmd), [deployment view](docs/diagrams/deployment-view.mmd). Overview: [docs/architecture.md](docs/architecture.md).

## Repository Layout

```text
api/          FastAPI application and API routes
edge/         Edge worker, frame sampling, model adapter interfaces
rules/        Safety policy evaluation logic
telemetry/    Runtime metrics and observability helpers
evidence/     Hashing and evidence-chain helpers
configs/      Local and Jetson-oriented config examples
examples/     Demo events and sample video-source inputs
docs/         Architecture, deployment, schemas, roadmap
tests/        Unit tests for API and safety logic
```

## Quick Start

```bash
git clone https://github.com/obiedeh/physical-ai-safety-observability.git
cd physical-ai-safety-observability
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn api.main:app --reload --port 8080
```

In another terminal:

```bash
python -m edge.worker \
  --config configs/local.json \
  --source examples/sample_source.json \
  --backend http://127.0.0.1:8080
```

Open `http://127.0.0.1:8080/health`, `/docs`, and `/metrics`. Apply migrations manually when needed:

```bash
PHYSICAL_AI_CONFIG=configs/local.json alembic upgrade head
```

CI and the local verification path:

```bash
make install-dev
make verify
```

The CI gate runs Ruff and the test suite on Ubuntu. Docker: `docker compose --profile demo up --build`.

## Safety Event Model

Each event carries camera ID, timestamp, rule ID, severity, confidence, evidence, a human-review recommendation, and telemetry context. See [docs/event_schema.md](docs/event_schema.md) and [examples/sample_event.json](examples/sample_event.json).

## Model Integration

The VLM adapter is intentionally mocked so the event model, policy engine and review flow can be tested deterministically. Real adapters sit behind the same interface: NVIDIA Cosmos Reasoning or VLM endpoints, Gemma-style multimodal endpoints, local vLLM OpenAI-compatible APIs, Jetson-hosted inference services. Cosmos-Reason2 through NVIDIA NIM's OpenAI-compatible API is the intended first real backend:

```bash
python -m edge.worker \
  --config configs/cosmos_reasoning.json \
  --source examples/sample_source.json \
  --backend http://127.0.0.1:8080 \
  --adapter cosmos-reason2 \
  --adapter-endpoint http://127.0.0.1:8000/v1 \
  --model nvidia/cosmos-reason2-2b
```

Video or RTSP input needs the optional OpenCV dependency (`pip install -e .[opencv]`); set `source_type` to `video_file` or `rtsp` in the source JSON.

## Runtime Paths

- **Demo path, today:** Linux local development with the deterministic mock model.
- **Jetson path:** `PHYSICAL_AI_CONFIG=configs/jetson.json` with the same commands. This is a deployment shape, not hardware performance evidence. Latency, memory and sustained-runtime artifacts must be committed before any measured Jetson readiness is claimed.
- **Real VLM path:** `configs/cosmos_reasoning.json` with `COSMOS_API_KEY` set.

## What Is Not Established

- No model has been run against real camera input in this repository.
- No latency, memory, power or thermal measurement exists on any device.
- No operator dashboard exists; review is through the API.
- No zone geometry is derived from calibration; rules use configured regions.

## Next Work, in Order

1. One committed measured run: the mock path on a Jetson with telemetry hooks writing an artifact (latency p95 and p99, memory, dropped frames), device and date recorded.
2. Cosmos-Reason2 adapter run against a local endpoint with the same artifact shape.
3. RTSP camera source and calibration-derived zones.
4. Operator dashboard and human-in-the-loop review workflow.
5. Incident export and audit trails through the evidence chain.

## Related

Sibling systems: [jetson-edge-ai-security](https://github.com/obiedeh/jetson-edge-ai-security) (measured Thor inference and power evidence for a defensive telemetry runtime) and the [Physical AI case study](https://obiedeh.github.io/physical-ai-jetson-robotics.html).
