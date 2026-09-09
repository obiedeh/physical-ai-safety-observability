# Physical AI Safety Observability

**Runtime safety layer for robots and industrial workcells: structured safety events, an operator review API, and telemetry hooks. Measured on Jetson AGX Thor: the pipeline's runtime overhead with a mock model, and per-frame inference cost with Cosmos-Reason2-2B served locally by vLLM. Detection quality is not measured; no labelled ground truth exists yet.**

The system turns camera or video input, safety rules, runtime telemetry, and model outputs into safety events an operator can review. The goal is operational review, not demo object detection. Nothing here acts autonomously.

## Status at a Glance

| Layer | State | What exists | What does not exist yet |
|---|---|---|---|
| Event model and API | Implemented | FastAPI backend for health, camera registration, event ingestion, incident timelines and metrics; SQLite persistence; Alembic migrations; OpenAPI docs | Operator dashboard |
| Safety policy engine | Implemented | PPE, restricted zone, proximity risk and unsafe-event rules over structured detections | Zone geometry from camera calibration |
| Edge worker | Implemented | Frame sampling from synthetic, video-file and RTSP-style sources; adapter interface for models | Live camera deployment |
| Model adapters | **Measured** (inference cost), 2026-09-09, Jetson AGX Thor, Cosmos-Reason2-2B via vLLM | Deterministic mock adapter; OpenAI-compatible and Cosmos-Reason2 adapters, the latter run against a local vLLM server on device | Any detection-quality measurement (no ground truth) |
| Telemetry | **Measured** (mock model), 2026-09-09, Jetson AGX Thor | Run artifacts under `reports/thor/` with device provenance, per-frame timings, event counts, process RSS and tegrastats | Any measurement with a real model |
| Jetson path | **Measured**: worker, backend and a real model on Thor | Worker, FastAPI backend and Cosmos-Reason2-2B inference measured on Thor; see the section below | Sustained-runtime artifacts; live camera |
| Evidence chain | Implemented | Hashing and evidence-chain helpers under `evidence/` | Artifacts produced through them |

Nothing in this repository measures detection quality. Every run artifact carries device, date, inputs and hashes.

## Measured on Jetson AGX Thor, 2026-09-09

Device: Jetson AGX Thor Developer Kit (`tegra264`), L4T R38.4.0, `nvpmodel` 120W, Python 3.12.3, repository commit `254ef27`. Written by `python -m edge.worker ... --report`; every artifact carries device provenance, per-frame timings, event and detection counts, token usage when the model reports it, peak RSS, and a 1 Hz `tegrastats` summary with a `*_tegrastats.jsonl` sidecar.

### Runtime overhead with the mock adapter

The mock adapter returns fixed detections at microsecond cost, so these figures are the cost of frame sampling, the safety policy engine, event construction and the backend path, not of any model.

| Run | Frames | Achieved rate | Rule evaluation p50 / p95 / p99 | Backend POST per frame, p50 / p95 | Board power VIN p50 | Artifact |
|---|---|---|---|---|---|---|
| 30 fps pacing, no posting | 1800 | **28.588 frames/s** | 0.8587 / 0.9877 / 1.2001 ms | n/a | 24604 mW | [`reports/thor/mock_30fps_no_post.json`](reports/thor/mock_30fps_no_post.json) |
| 30 fps pacing, posting to local FastAPI + SQLite | 400 | **4.357 frames/s** | 0.6036 / 0.7123 / 0.8267 ms | **160.9 / 180.4 ms** (four events per frame) | 25570 mW | [`reports/thor/mock_30fps_backend.json`](reports/thor/mock_30fps_backend.json) |
| 30 fps pacing, posting one batch per frame to `/events/batch` | 400 | **7.075 frames/s** | 0.6818 / 0.8565 / 0.9099 ms | **68.2 / 89.0 ms** (one request for four events) | 25158 mW | [`reports/thor/mock_30fps_backend_batched.json`](reports/thor/mock_30fps_backend_batched.json) |
| unpaced, no posting | 500 | 3078 frames/s | 0.1648 / 0.2257 / 0.2874 ms | n/a | run too short to sample | [`reports/thor/mock_no_post.json`](reports/thor/mock_no_post.json) |

- At camera-rate pacing the worker keeps up: 28.588 frames/s against a 30 frames/s source, rule evaluation under 1.2 ms p99, board power at the device's idle level (about 24 W).
- The synchronous POST to the backend is the bottleneck. Per-event posting costs 161 ms p50 per frame for four events and caps throughput at 4.357 frames/s. Batching the frame's events into one `/events/batch` request (one transaction) cuts that to 68 ms p50 and lifts throughput to 7.075 frames/s, still far from the 30 frames/s source: the remaining cost is per-event incident grouping inside SQLite. Asynchronous posting off the capture thread is the next runtime fix.
- Peak process RSS 0.061 GB; junction temperature peak 40.8 C. These are 60 to 90 second runs, not sustained validation.
- Event counts are exactly four per frame because the mock detections trip every rule on every frame.

### Real-model inference cost: Cosmos-Reason2-2B on Thor

`nvidia/Cosmos-Reason2-2B` (bf16 weights from Hugging Face) served on the same device by vLLM 0.14 in NVIDIA's Jetson container `ghcr.io/nvidia-ai-iot/vllm:0.14.0-r38.3-arm64-sbsa-cu130-24.04` with `--gpu-memory-utilization 0.25 --max-model-len 8192 --reasoning-parser qwen3`. Input: one frame every 60 from the Isaac Sim Ludo workcell video in the [robotics repository](https://github.com/obiedeh/physical-ai-jetson-robotics/blob/main/reports/ludo_physical_game.mp4), 640 x 640, a simulation with a robot arm and game pieces and no people. The repo's `cosmos-reason2` adapter asks for a `<think>` block and a JSON `<answer>` with `max_tokens` 4096. No events were posted.

| Metric | Value | Source |
|---|---|---|
| Frames | 60 in 390 s, **0.154 frames/s** | [`reports/thor/cosmos2b_video_60.json`](reports/thor/cosmos2b_video_60.json) |
| Inference latency per frame | **p50 4.35 s, p95 12.85 s**, max 15.4 s, min 2.75 s | same |
| Model tokens per frame | prompt 574, completion p50 260, p95 815, max 977 | same |
| Implied decode rate | about 61 tokens/s | derived from the two rows above |
| Board power during the run | VIN **p50 66.6 W, peak 107.1 W**; GPU rail p50 16.5 W | [`reports/thor/cosmos2b_video_60_tegrastats.jsonl`](reports/thor/cosmos2b_video_60_tegrastats.jsonl), 388 samples |
| Temperatures | junction peak 58.7 C, GPU peak 57.9 C | same |
| Detections returned | 97 across 60 frames; by label: ball 3, cube 15, person_robot_pallet_cart_box_unsafe_event 12, robot 38, sphere 28, square 1 | `detections_by_label` in the artifact |
| Safety events | 0 (no person in the footage; PPE, zone and proximity rules need a person) | same |

What these numbers say, and do not say:

- Latency is dominated by reasoning length: the three slowest frames produced 977, 825 and 815 completion tokens at a steady 61 tokens/s. A 2B reasoning model on this device costs 3 to 15 s per frame with this prompt, so it is a periodic review model, not a per-frame detector. Capping `max_tokens` or disabling the think block is the obvious next measurement.
- The model does not hold the label vocabulary: 12 of the detections are a literal echo of the schema string and 46 use labels outside the schema (sphere, cube, ball, square) for the game pieces. The parser accepted them; the policy engine ignored them because none is a person. This is recorded, not hidden, and it is why no accuracy is claimed.
- Board power under a real model is 67 W p50 against about 24 W idle for the mock path. The first attempt at this run failed on a 60 s adapter timeout at frame 26 ([log](reports/thor/cosmos2b_video_60_attempt1_timeout.log)); the timeout is now a command-line option and a failed run writes a partial artifact with the error.
- No ground truth exists for this footage, so nothing here is precision or recall. That measurement needs the authored simulation scenes with known PPE and zone states; see Next Work.

Second run, same 60 frames, `--no-think --max-tokens 512` ([`reports/thor/cosmos2b_video_60_nothink.json`](reports/thor/cosmos2b_video_60_nothink.json)):

| | think block, 4096 cap | no think, 512 cap |
|---|---|---|
| Inference p50 / p95 / max per frame | 4.35 / 12.85 / 15.41 s | **3.57 / 6.58 / 9.35 s** |
| Completion tokens p50 / max | 260 / 977 | 157 / 415 |
| Throughput | 0.154 frames/s | 0.241 frames/s |
| Board power VIN p50 / peak | 66.6 / 107.1 W | 60.3 / 105.2 W |
| Schema-echo detections | 12 of 97 | 11 of 106 |

Dropping the think block halves the p95 and removes the 13 to 15 s tail; the median moves less because about 2 s of every frame is prompt prefill and image encoding, not generation. Label compliance does not improve, so the vocabulary problem is prompt and model, not reasoning length.

Reproduce (server, then worker), on a Jetson with the weights under `~/models/cosmos-reason2-2b`:

```bash
docker run -d --name cosmos2b-vllm --runtime=nvidia --network host --ipc host \
  -v ~/models/cosmos-reason2-2b:/models/cosmos-reason2-2b:ro \
  ghcr.io/nvidia-ai-iot/vllm:0.14.0-r38.3-arm64-sbsa-cu130-24.04 \
  vllm serve /models/cosmos-reason2-2b --served-model-name nvidia/cosmos-reason2-2b \
  --host 0.0.0.0 --port 8000 --gpu-memory-utilization 0.25 --max-model-len 8192 --reasoning-parser qwen3
python -m edge.worker --source examples/thor_video_source.json --adapter cosmos-reason2 \
  --adapter-endpoint http://127.0.0.1:8000/v1 --model nvidia/cosmos-reason2-2b \
  --inference-timeout-seconds 240 --no-post --once --report reports/thor/cosmos2b_video_60.json
```

Reproduce on a Jetson:

```bash
python -m edge.worker --source examples/synthetic_30fps_source.json --adapter mock --no-post --once --report reports/thor/run.json
```

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

- No model has been run against real camera input in this repository; the real-model run used simulation footage.
- No detection-quality measurement exists: no labelled ground truth, so no precision or recall for any rule.
- The measured runs are 60 to 390 seconds, not sustained operation.
- No operator dashboard exists; review is through the API.
- No zone geometry is derived from calibration; rules use configured regions.

## Next Work, in Order

1. Done 2026-09-09: mock path on Jetson AGX Thor with run artifacts under `reports/thor/`.
2. Done 2026-09-09: Cosmos-Reason2-2B through a local vLLM server on Thor, inference cost and power measured on simulation footage.
2b. Done 2026-09-09: batched posting measured at 7.1 frames/s (from 4.4); asynchronous posting is next.
2c. Done 2026-09-09: no-think, 512-token run halves p95 latency; label compliance unchanged. Next: a constrained-output prompt or grammar (JSON schema mode) and a larger model, measured the same way.
3. RTSP camera source and calibration-derived zones.
4. Operator dashboard and human-in-the-loop review workflow.
5. Incident export and audit trails through the evidence chain.

## Related

Sibling systems: [jetson-edge-ai-security](https://github.com/obiedeh/jetson-edge-ai-security) (measured Thor inference and power evidence for a defensive telemetry runtime) and the [Physical AI case study](https://obiedeh.github.io/physical-ai-jetson-robotics.html).
