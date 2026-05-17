# Physical AI Safety Observability

Edge-first safety observability platform for robotics, industrial workcells, and Physical AI environments.

This project turns camera/video input, safety rules, runtime telemetry, and multimodal model outputs into structured safety events that an operator can review. The goal is not demo object detection. The goal is operational awareness that can survive real edge deployment.

## What Works Now

This repository now includes a runnable production-grade skeleton:

- FastAPI backend for health, camera registration, event ingestion, incident timelines, and metrics
- SQLite-backed event, camera, and incident persistence
- Alembic-managed database schema migrations
- Edge worker CLI for synthetic, video-file, and RTSP-style frame sampling
- Mock VLM adapter that produces structured detections without pretending to be real AI
- OpenAI-compatible and Cosmos-Reason2 adapter paths with hardened response parsing
- Safety policy engine for PPE, restricted zones, proximity risk, and unsafe events
- Telemetry hooks for latency p95/p99, event counts, memory pressure, queue depth, dropped frames, and runtime snapshots
- Sample event schemas and demo payloads
- Tests, lint configuration, Dockerfile, Compose file, and CI workflow

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

## Repository Layout

```text
api/          FastAPI application and API routes
edge/         Edge worker, frame sampling, model adapter interfaces
rules/        Safety policy evaluation logic
telemetry/    Runtime metrics and observability helpers
configs/      Local and Jetson-oriented config examples
examples/     Demo events and sample video-source inputs
docs/         Architecture, deployment, schemas, and roadmap
tests/        Unit tests for API and safety logic
```

## Quick Start

```bash
cd projects/physical-ai-safety-observability
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

Open:

- API health: `http://127.0.0.1:8080/health`
- OpenAPI docs: `http://127.0.0.1:8080/docs`
- Metrics: `http://127.0.0.1:8080/metrics`

Apply migrations manually when needed:

```bash
PHYSICAL_AI_CONFIG=configs/local.json alembic upgrade head
```

## Docker

```bash
docker compose --profile demo up --build
```

## Safety Event Model

The platform emits structured events with:

- camera ID
- timestamp
- rule ID
- severity
- confidence
- evidence
- human-review recommendation
- telemetry context

See `docs/event_schema.md` and `examples/sample_event.json`.

## Model Integration Strategy

The current VLM adapter is intentionally mocked. That is not a weakness. It is the correct engineering move at this stage.

Real adapters should be added behind the same interface for:

- NVIDIA Cosmos Reasoning / VLM endpoints
- Gemma-style multimodal endpoints
- local vLLM OpenAI-compatible APIs
- Jetson-hosted inference services
- future RTSP/live camera pipelines

Do not hardwire the app to one model. Keep inference replaceable.

Cosmos-Reason2 is the recommended first real backend. Use it through the dedicated adapter
that targets NVIDIA NIM's OpenAI-compatible Chat Completions API:

```bash
python -m edge.worker \
  --config configs/cosmos_reasoning.json \
  --source examples/sample_source.json \
  --backend http://127.0.0.1:8080 \
  --adapter cosmos-reason2 \
  --adapter-endpoint http://127.0.0.1:8000/v1 \
  --model nvidia/cosmos-reason2-2b
```

## Runtime Paths

Demo path:

```bash
uvicorn api.main:app --reload --port 8080
python -m edge.worker --config configs/local.json --source examples/sample_source.json
```

Jetson path:

```bash
PHYSICAL_AI_CONFIG=configs/jetson.json uvicorn api.main:app --host 0.0.0.0 --port 8080
python -m edge.worker --config configs/jetson.json --source examples/sample_source.json
```

Real VLM path:

```bash
export COSMOS_API_KEY=...
python -m edge.worker --config configs/cosmos_reasoning.json --source examples/sample_source.json
```

Video or RTSP input uses the optional OpenCV dependency:

```bash
pip install -e .[opencv]
```

Set `source_type` to `video_file` or `rtsp` in the source JSON and provide the file path or RTSP URI in `source_uri`.

## Production Roadmap

1. Connect RTSP cameras and real frame extraction
2. Add Cosmos/VLM adapter using local OpenAI-compatible endpoint
3. Add zone geometry from camera calibration files
4. Add operator dashboard
5. Add Prometheus/Grafana deployment profile
6. Benchmark Jetson memory, latency, and sustained runtime stability
7. Add human-in-the-loop review workflow
8. Add incident export and audit trails

## Positioning

This project supports a broader engineering focus around:

- Physical AI safety
- Edge AI observability
- robotics workcell monitoring
- multimodal inference systems
- deployable Jetson AI pipelines
- operator-facing safety intelligence
