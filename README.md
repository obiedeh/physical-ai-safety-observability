# Physical AI Safety Observability

**Runtime safety layer for robots and industrial workcells: structured safety events, an operator review API, and telemetry hooks. The pipeline's runtime overhead is measured on Jetson AGX Thor with a mock model; no real model inference or detection quality has been measured yet.**

The system turns camera or video input, safety rules, runtime telemetry, and model outputs into safety events an operator can review. The goal is operational review, not demo object detection. Nothing here acts autonomously.

## Status at a Glance

| Layer | State | What exists | What does not exist yet |
|---|---|---|---|
| Event model and API | Implemented | FastAPI backend for health, camera registration, event ingestion, incident timelines and metrics; SQLite persistence; Alembic migrations; OpenAPI docs | Operator dashboard |
| Safety policy engine | Implemented | PPE, restricted zone, proximity risk and unsafe-event rules over structured detections | Zone geometry from camera calibration |
| Edge worker | Implemented | Frame sampling from synthetic, video-file and RTSP-style sources; adapter interface for models | Live camera deployment |
| Model adapters | Mock plus adapter paths | Deterministic mock VLM adapter; OpenAI-compatible and Cosmos-Reason2 adapter paths with hardened response parsing | Any measured run against a real model endpoint |
| Telemetry | **Measured** (mock model), 2026-09-09, Jetson AGX Thor | Run artifacts under `reports/thor/` with device provenance, per-frame timings, event counts, process RSS and tegrastats | Any measurement with a real model |
| Jetson path | **Runtime measured** with the mock adapter; model inference not measured | Worker and FastAPI backend run on Thor; see the section below | Real-model latency, memory and sustained-runtime artifacts |
| Evidence chain | Implemented | Hashing and evidence-chain helpers under `evidence/` | Artifacts produced through them |

The measured numbers in this repository are runtime-overhead figures with a mock model; they say nothing about detection quality. Every run artifact carries device, date, inputs and hashes.

## Measured on Jetson AGX Thor, 2026-09-09

Device: Jetson AGX Thor Developer Kit (`tegra264`), L4T R38.4.0, `nvpmodel` 120W, Python 3.12.3, repository commit `254ef27`. Adapter: `mock_vlm` (fixed detections, microsecond cost), so the figures below are the cost of frame sampling, the safety policy engine, event construction and the backend path, not of any model. Written by `python -m edge.worker ... --report`.

| Run | Frames | Achieved rate | Rule evaluation p50 / p95 / p99 | Backend POST per frame, p50 / p95 | Board power VIN p50 | Artifact |
|---|---|---|---|---|---|---|
| 30 fps pacing, no posting | 1800 | **28.642 frames/s** | 0.8364 / 0.9677 / 1.1174 ms | n/a | 24252 mW | [`reports/thor/mock_30fps_no_post.json`](reports/thor/mock_30fps_no_post.json) |
| 30 fps pacing, posting to local FastAPI + SQLite | 400 | **4.51 frames/s** | 0.6189 / 0.7587 / 0.7847 ms | **156.2 / 181.6 ms** (four events per frame) | 25346 mW | [`reports/thor/mock_30fps_backend.json`](reports/thor/mock_30fps_backend.json) |
| unpaced, no posting | 500 | 3159 frames/s | 0.1621 / 0.2185 / 0.2686 ms | n/a | run too short to sample | [`reports/thor/mock_no_post.json`](reports/thor/mock_no_post.json) |

What the numbers say:

- At camera-rate pacing the worker keeps up: 28.642 frames/s against a 30 frames/s source, with rule evaluation under 1.1 ms p99 and board power at the device's idle level (about 24 W).
- The synchronous per-event POST to the backend is the bottleneck. With four events per frame the backend path costs 156 ms p50 per frame, which caps end-to-end throughput at 4.51 frames/s on this device. Batching events per frame or posting asynchronously is the first runtime fix this measurement points at.
- Peak process RSS was 0.061 GB. Junction temperature peaked at 39.7 C. These are 60 to 90 second runs, not sustained validation.
- Nothing here measures a model. The mock adapter returns fixed detections that trip every rule on every frame, which is why event counts are exactly four per frame.

Reproduce on a Jetson:

```bash
python -m edge.worker --source examples/synthetic_30fps_source.json --adapter mock --no-post --once --report reports/thor/run.json
```

`tegrastats` sidecars (`*_tegrastats.jsonl`) hold the 1 Hz rail and temperature samples for the paced runs.

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
- No real-model latency, memory, power or thermal measurement exists; the Thor figures above use a mock adapter.
- No operator dashboard exists; review is through the API.
- No zone geometry is derived from calibration; rules use configured regions.

## Next Work, in Order

1. Done 2026-09-09: mock path on Jetson AGX Thor with run artifacts under `reports/thor/`.
2. Cosmos-Reason2 adapter run against a local vLLM endpoint on Thor with the same artifact shape. Blocked on model weights: the Cosmos-Reason2 checkpoints are gated on Hugging Face and are not present on the device.
2b. Batch or async event posting, then re-measure the backend path.
3. RTSP camera source and calibration-derived zones.
4. Operator dashboard and human-in-the-loop review workflow.
5. Incident export and audit trails through the evidence chain.

## Related

Sibling systems: [jetson-edge-ai-security](https://github.com/obiedeh/jetson-edge-ai-security) (measured Thor inference and power evidence for a defensive telemetry runtime) and the [Physical AI case study](https://obiedeh.github.io/physical-ai-jetson-robotics.html).
