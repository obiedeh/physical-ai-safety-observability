# Physical AI Safety Observability

**Status: Functional. Under active field validation and tuning on live cameras.**

Runtime safety layer for robots and industrial workcells: cameras configured in a web UI, a vision-language model inspecting frames on the device, safety rules turning its output into structured events, and an operator console to review them. Measured on Jetson AGX Thor: the pipeline's runtime overhead with a mock model, per-frame inference cost with Cosmos-Reason2 served locally by vLLM, and the constrained-decoding guard against the real model server. Detection quality is not measured; no labelled ground truth exists yet.

The goal is operational review, not demo object detection. Nothing here acts autonomously.

**Project overview:** [open the one-page showcase](https://obiedeh.github.io/physical-ai-safety-observability/docs/showcase/) for the workcell rules, the measured Thor results, the constrained-mode guard and screens from the running console. Also: [Thor evidence page](https://obiedeh.github.io/physical-ai-safety-observability/reports/index.html) · [case study](https://obiedeh.github.io/physical-ai-safety-observability.html) · source [`docs/showcase/index.html`](docs/showcase/index.html).

## Status at a Glance

| Layer | State | What exists | What does not exist yet |
|---|---|---|---|
| Event model and API | Implemented | FastAPI backend for health, event ingestion, incident timelines and metrics; SQLite persistence; Alembic migrations | Authentication (intended for an internal edge network) |
| Operator UI and configuration | Implemented | Web console served by the API: Live, Cameras, Model, Runs, Events. Cameras, model endpoint and inference cadence are set in the UI, stored in SQLite and applied without a restart | A committed live-camera run through it |
| Safety policy engine | Implemented | PPE, restricted zone, proximity risk and unsafe-event rules over structured detections; zones drawn per camera in the UI | Zone geometry from camera calibration |
| Live pipeline | Implemented | One capture thread per camera at native frame rate, an inference worker on its own cadence, and an asynchronous event poster; file and synthetic sources through the `edge.worker` CLI | Its capture rate and packet-to-event latency measured on the Thor |
| Model adapters | **Measured** (inference cost), 2026-09-09, Jetson AGX Thor, Cosmos-Reason2 2B and 8B via vLLM | Deterministic mock adapter; chat-completions and Cosmos-Reason2 adapters run against a local vLLM server on device | Any detection-quality measurement (no ground truth) |
| Constrained-mode guard | **Measured**, 2026-10-02, Jetson AGX Thor | Settings validation plus a live canary request that proves the server enforces the JSON schema before any worker uses it | n/a |
| Telemetry | **Measured**, 2026-09-09, Jetson AGX Thor | Run artifacts under `reports/thor/` with device provenance, per-frame timings, event counts, process RSS and tegrastats, for the mock and the real models | Sustained-runtime measurement |
| Evidence chain | Implemented | Frame hashing and evidence records on every event; the inference frame behind an event is kept and shown in the Events page | Incident export |

Nothing in this repository measures detection quality. Every run artifact carries device, date, inputs and hashes.

## What it does today

Each item is on `main` and covered by the test suite or by code at the named path. None of it is a performance claim. A diagram of what each rule looks for in a workcell is in the [showcase](https://obiedeh.github.io/physical-ai-safety-observability/docs/showcase/#plan-h).

**Configuration in the UI.** Cameras are added, edited, enabled, disabled and deleted in the Cameras page: vendor profile (Tapo, Hikvision, Dahua, Amcrest, Axis, Reolink, UniFi Protect, generic RTSP, HTTP MJPEG, browser webcam), host, port, credentials, stream path filled in from the profile, main or sub stream, restricted zones drawn on a snapshot, and which rules run on that camera (`edge/camera_profiles.py`, `api/routes/config.py`). Test connection decodes one frame and returns a thumbnail or a classified error: unreachable, authentication failed, wrong path, codec, timeout (`edge/probe.py`). Passwords are encrypted at rest with a key file outside the repository, are never returned by the API, are only reused for the host and port they were saved for, and are masked in logs, errors, events and run reports (`edge/secrets.py`, `edge/redaction.py`). The interactive command-line prompt is kept as an optional path over the same code (`edge/live_camera.py`).

**Model selection.** The Model page lists the Cosmos-Reason2 containers the device can run, with a memory preflight, and starts or stops the chosen one (`edge/model_server.py`). The endpoint is editable. The container keeps running across API restarts and stopping it needs an explicit, logged confirmation.

**Live pipeline.** Capture, inference and posting are three independent loops. A capture thread per camera decodes at the camera's native rate and streams MJPEG to the browser (`edge/capture.py`). An inference worker samples the latest frame on its own interval, runs the model and the rules (`edge/service.py`). Events and feedback go to an asynchronous poster: a bounded queue drained by its own thread, with retries, a drop counter, and latency measured from frame capture to the backend's acknowledgement (`edge/poster.py`). A model outage shows "inference unavailable" while video keeps playing; no event is invented.

**Constrained decoding is enforced, not documented.** Saving constrained mode against a server started with a reasoning parser is refused, and before any worker uses constrained mode a canary request must prove the server honours the schema (`edge/model_guard.py`). See the measured probe below.

**Measured runs from the UI.** The Runs page records a run and writes a `run-report-v1` artifact under `reports/<host>/` in the same shape as the committed Thor runs, with capture, transport and model-server blocks added. A run refuses to start when the model server is not ready and aborts, marked failed, if the server stays down mid-run.

**Deployment.** A systemd user unit runs the API and UI with a persistent log (`deploy/physical-ai-safety.service`).

## Measured on Jetson AGX Thor, 2026-09-09

Rendered view of the same artifacts: [evidence page](https://obiedeh.github.io/physical-ai-safety-observability/reports/index.html) (generated by `scripts/build_evidence_pages.py`, `make evidence-pages`), [case study](https://obiedeh.github.io/physical-ai-safety-observability.html), and a summary with a latency chart in the [showcase](https://obiedeh.github.io/physical-ai-safety-observability/docs/showcase/#thor-h).

Device: Jetson AGX Thor Developer Kit (`tegra264`), L4T R38.4.0, `nvpmodel` 120W, Python 3.12.3, repository commit `254ef27` as recorded by the artifacts, which is `0b3d9d0` on `main` today (see the evidence caveat below the four-run table). Written by `python -m edge.worker ... --report`; every artifact carries device provenance, per-frame timings, event and detection counts, token usage when the model reports it, peak RSS, and a 1 Hz `tegrastats` summary with a `*_tegrastats.jsonl` sidecar.

### Runtime overhead with the mock adapter

The mock adapter returns fixed detections at microsecond cost, so these figures are the cost of frame sampling, the safety policy engine, event construction and the backend path, not of any model.

| Run | Frames | Achieved rate | Rule evaluation p50 / p95 / p99 | Backend POST per frame, p50 / p95 | Board power VIN p50 | Artifact |
|---|---|---|---|---|---|---|
| 30 fps pacing, no posting | 1800 | **28.588 frames/s** | 0.8587 / 0.9877 / 1.2001 ms | n/a | 24604 mW | [`reports/thor/mock_30fps_no_post.json`](reports/thor/mock_30fps_no_post.json) |
| 30 fps pacing, posting to local FastAPI + SQLite | 400 | **4.357 frames/s** | 0.6036 / 0.7123 / 0.8267 ms | **160.9 / 180.4 ms** (four events per frame) | 25570 mW | [`reports/thor/mock_30fps_backend.json`](reports/thor/mock_30fps_backend.json) |
| 30 fps pacing, posting one batch per frame to `/events/batch` | 400 | **7.075 frames/s** | 0.6818 / 0.8565 / 0.9099 ms | **68.2 / 89.0 ms** (one request for four events) | 25158 mW | [`reports/thor/mock_30fps_backend_batched.json`](reports/thor/mock_30fps_backend_batched.json) |
| unpaced, no posting | 500 | 3078 frames/s | 0.1648 / 0.2257 / 0.2874 ms | n/a | run too short to sample | [`reports/thor/mock_no_post.json`](reports/thor/mock_no_post.json) |

- At camera-rate pacing the worker keeps up: 28.588 frames/s against a 30 frames/s source, rule evaluation under 1.2 ms p99, board power at the device's idle level (about 24 W).
- In these runs the synchronous POST to the backend is the bottleneck. Per-event posting costs 161 ms p50 per frame for four events and caps throughput at 4.357 frames/s. Batching the frame's events into one `/events/batch` request (one transaction) cuts that to 68 ms p50 and lifts throughput to 7.075 frames/s, still far from the 30 frames/s source: the remaining cost is per-event incident grouping inside SQLite. Posting is now asynchronous and off the capture and inference threads (`edge/poster.py`); its effect has not been measured on the Thor, so these synchronous figures remain the only committed numbers.
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
- The model does not hold the label vocabulary: 12 of the detections are a literal echo of the schema string and 47 use labels outside the schema (sphere 28, cube 15, ball 3, square 1) for the game pieces, 59 of 97 in all. The parser accepted them; the policy engine ignored them because none is a person. This is recorded, not hidden, and it is why no accuracy is claimed.
- Board power under a real model is 67 W p50 against about 24 W idle for the mock path. The first attempt at this run failed on a 60 s adapter timeout at frame 26 ([log](reports/thor/cosmos2b_video_60_attempt1_timeout.log)); the timeout is now a command-line option and a failed run writes a partial artifact with the error.
- No ground truth exists for this footage, so nothing here is precision or recall. That measurement needs the authored simulation scenes with known PPE and zone states; see Planned upgrades.

Four runs on the same 60 frames, same server, same device. Each column is one artifact under `reports/thor/`.

| | think block, 4096 cap | no think, 512 cap | + JSON-schema grammar, original prompt (**failure case: empty output**) | + JSON-schema grammar, JSON-only prompt |
|---|---|---|---|---|
| Artifact | [`cosmos2b_video_60.json`](reports/thor/cosmos2b_video_60.json) | [`..._nothink.json`](reports/thor/cosmos2b_video_60_nothink.json) | [`..._schema_v1prompt.json`](reports/thor/cosmos2b_video_60_schema_v1prompt.json) | [`..._schema.json`](reports/thor/cosmos2b_video_60_schema.json) |
| Inference p50 / p95 / max per frame | 4.35 / 12.85 / 15.41 s | 3.57 / 6.58 / 9.35 s | 0.31 / 0.33 / 4.19 s (not a speed result: the model produced nothing) | **2.69 / 3.36 / 8.03 s** |
| Completion tokens p50 / max | 260 / 977 | 157 / 415 | 7 / 7 | 135 / 512 |
| Throughput | 0.154 frames/s | 0.241 frames/s | 2.303 frames/s (empty answers) | 0.367 frames/s |
| Board power VIN p50 | 66.6 W | 60.3 W | 37.1 W | 62.5 W |
| Detections, total | 97 | 106 | 0 | 193 |
| Labels outside the schema vocabulary | 59 | 57 | 0 | **0** |
| "person" detections (footage has none) | 0 | 0 | 0 | **6** |
| Safety events fired | 0 | 0 | 0 | **7** (HUMAN_ROBOT_PROXIMITY 2, PPE_MISSING 5) |

What the four columns say together:

- Reasoning length drives the latency tail. Removing the think block halves the p95; the grammar removes generation almost entirely (p95 3.36 s), leaving about 2 to 3 s of prompt prefill and image encoding per frame on this device.
- The third column is a failure case, kept because it is instructive, not because it is fast. The original prompt still asked for an `<answer>` wrapper the grammar forbids, so the model emitted an empty list on every one of the 60 frames (7 completion tokens each, zero detections). Its 0.31 s p50 and 2.3 frames/s measure the cost of generating nothing and must not be read as constrained-decoding throughput; the honest constrained number is the fourth column.
- The grammar fixes the vocabulary completely: zero out-of-schema labels in the working constrained run, against 59 and 57 before (47 and 46 game-piece labels plus 12 and 11 echoes of the schema string). With a prompt written for JSON-only output it produced 193 in-vocabulary detections.
- Constrained output exposes the real problem: on footage with no people, the model labelled six detections "person", and five of those tripped PPE and proximity rules, seven false safety events. Vocabulary compliance is not detection quality. Only labelled ground truth can turn this into a precision and recall number, which is why that is the next step.
- A server detail worth recording: with vLLM 0.14's `--reasoning-parser qwen3` enabled, `response_format` JSON schema is accepted but not enforced. The two constrained runs used a second container without the parser (`cosmos2b-vllm-noreason`), otherwise identical. This is now enforced in code and measured: [`reports/thor/constrained_guard_probe.json`](reports/thor/constrained_guard_probe.json) (2026-10-02) shows the reasoning-parser container answering an enum-constrained canary with `banana` and the guard refusing constrained mode, and the no-reasoning container honouring the grammar.
- Evidence caveats for this table: every artifact records `git_sha 254ef27` because the recorder stores `HEAD`, but the `--report`, `--post-batch`, `--no-think`, `--max-tokens` and `--json-schema` flags used to produce them were committed afterwards (`a3a4f4c`, `5d7590a`, `aa20dc2`); the runs came from a working tree ahead of that commit. Commit messages on `main` were rewritten on 2026-10-03 with no change to any file, which changed commit ids from that point on: the commit the artifacts record as `254ef27` is `0b3d9d0` on `main`, with an identical tree. The run log of the JSON-only constrained run was not captured; the file that carried its name was a byte-for-byte copy of the failure case's log and has been removed. The JSON artifact and its tegrastats sidecar are the record for that run.

#### Constrained-mode guard, measured 2026-10-02

The application now starts the model container itself and refuses constrained runs against a server that would ignore the schema. `scripts/guard_probe.py` drove the API on the Thor against the real vLLM 0.14 containers; the result is committed as [`reports/thor/constrained_guard_probe.json`](reports/thor/constrained_guard_probe.json).

| Step | Result |
|---|---|
| Start the reasoning-parser container with constrained mode requested | Refused, HTTP 422 |
| Start the reasoning-parser container in think mode | Ready after 55.6 s |
| Save model settings with constrained mode and the reasoning-parser flag set | Refused, HTTP 422 |
| Canary request against the reasoning-parser server, parser flag left unknown | Server answered `banana` instead of the only value the schema allows; guard refused constrained mode |
| Start the container without the reasoning parser, constrained mode requested | Ready after 55.6 s |
| Canary request against that server | Schema value returned; constrained mode allowed |

The canary is one request whose schema permits a single value while the prompt asks for a different word. This confirms on the device what the table above could only state: vLLM 0.14 accepts a JSON schema but does not enforce it when the reasoning parser is on. No camera input was involved in this probe.

#### Model size: Cosmos-Reason2-8B on the same frames

Same server image, same device, `--gpu-memory-utilization 0.35`, no reasoning parser, same 60 frames.

| | 2B, grammar, JSON-only prompt | **8B, grammar, JSON-only prompt** | 2B, no think, 512 cap | 8B, no think, 512 cap |
|---|---|---|---|---|
| Artifact | [`cosmos2b_video_60_schema.json`](reports/thor/cosmos2b_video_60_schema.json) | [`cosmos8b_video_60_schema.json`](reports/thor/cosmos8b_video_60_schema.json) | [`cosmos2b_video_60_nothink.json`](reports/thor/cosmos2b_video_60_nothink.json) | [`cosmos8b_video_60_nothink.json`](reports/thor/cosmos8b_video_60_nothink.json) |
| Inference p50 / p95 / max | 2.69 / 3.36 / 8.03 s | 3.20 / 8.26 / 14.96 s | 3.57 / 6.58 / 9.35 s | 8.29 / 27.78 / 33.67 s |
| Completion tokens p50 / max | 135 / 512 | 47 / 157 | 157 / 415 | 126 / 512 |
| Board power VIN p50 / peak | 62.5 / 83.1 W | 66.0 / 131.6 W | 60.3 / 105.2 W | 69.1 / 108.4 W |
| Detections, total | 193 | 74 | 106 | 81 |
| Out-of-vocabulary labels | 0 | 0 | 57 | 20 |
| "person" on people-free footage | 6 | **0** | 0 | 0 |
| Safety events fired | 7 (false) | **0** | 0 | 0 |

- On this footage the larger model removes the phantom people: zero "person" labels and zero false events under the same grammar and prompt, where the 2B produced six and seven. Sixty frames of one simulation is a signal, not a rate; it does not say what the 8B does when a person is present.
- The 8B decodes at roughly 13 tokens/s on this device against about 60 for the 2B, so its p50 is 3.2 s constrained and 8.3 s unconstrained, with a tail near 34 s. Unconstrained, it still invents labels outside the schema (cube, cylinder, sphere): the grammar is needed at either size.
- Peak board power reached 132 W in the constrained 8B run; the p50 stays near 66 W for both sizes because prefill dominates the duty cycle.

Reproduce (server, then worker), on a Jetson with the weights under `~/models/cosmos-reason2-2b`:

```bash
docker run -d --name cosmos2b-vllm --runtime=nvidia --network host --ipc host \
  -v ~/models/cosmos-reason2-2b:/models/cosmos-reason2-2b:ro \
  ghcr.io/nvidia-ai-iot/vllm:0.14.0-r38.3-arm64-sbsa-cu130-24.04 \
  vllm serve /models/cosmos-reason2-2b --served-model-name nvidia/cosmos-reason2-2b \
  --host 0.0.0.0 --port 8000 --gpu-memory-utilization 0.25 --max-model-len 8192 --reasoning-parser qwen3
python -m edge.worker --source examples/thor_video_source.json --adapter cosmos-reason2 \
  --adapter-endpoint http://localhost:8000/v1 --model nvidia/cosmos-reason2-2b \
  --inference-timeout-seconds 240 --no-post --once --report reports/thor/cosmos2b_video_60.json
# constrained run: start the server WITHOUT --reasoning-parser, then add --no-think --max-tokens 512 --json-schema
```

Reproduce on a Jetson:

```bash
python -m edge.worker --source examples/synthetic_30fps_source.json --adapter mock --no-post --once --report reports/thor/run.json
```

## Architecture

The three loops and why they never wait on each other are summarised in the [showcase](https://obiedeh.github.io/physical-ai-safety-observability/docs/showcase/#flow-h).

```text
 camera (RTSP / HTTP MJPEG / browser webcam)        video file / synthetic source
        |                                                     |
        v                                                     v
 capture thread per camera -> latest-frame slot        edge.worker CLI
        |                          |                          |
        v                          v (inference interval)     |
 MJPEG to the Live page     vision-language model  <----------+
                            (Cosmos-Reason2 via vLLM, or mock)
                                   |
                                   v
                          safety policy engine
                                   |
                                   v
                 asynchronous poster -> FastAPI backend -> SQLite
                                                |
                                                v
                     operator console: Live, Cameras, Model, Runs, Events
```

## Repository Layout

```text
api/          FastAPI application and API routes
edge/         capture, live service, async poster, model server and guard,
              camera profiles, probe, secrets, redaction, worker CLI, adapters
rules/        safety policy evaluation logic
spatial/      zones and polygon tests
telemetry/    runtime metrics, run reports
evidence/     hashing and evidence records
web/          operator console (Vite, React, TypeScript)
deploy/       systemd unit
docs/         design notes; showcase/ holds the one-page project overview
scripts/      evidence page generator, guard probe
reports/      committed run artifacts and the generated evidence page
tests/        API, configuration, redaction, guard, poster and live-service tests
```

## Quick Start

```bash
git clone https://github.com/obiedeh/physical-ai-safety-observability.git
cd physical-ai-safety-observability
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cd web && pnpm install && pnpm build && cd ..
uvicorn api.main:app --port 8080
```

Open `http://localhost:8080`. Add a camera in Cameras (the "Synthetic test feed" profile needs no hardware), press Test connection, save. Choose the model in Model. Watch Live and Events. With no model server the default mock adapter produces fixed detections, labelled as such.

The file and synthetic worker still runs from the command line:

```bash
python -m edge.worker \
  --config configs/local.json \
  --source examples/sample_source.json \
  --backend http://localhost:8080 --once
```

Run as a service on the device: see the header of [`deploy/physical-ai-safety.service`](deploy/physical-ai-safety.service). API docs are at `/docs`, Prometheus metrics at `/metrics`. Apply migrations manually when needed:

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

The mock adapter is the default so the event model, policy engine and review flow can be tested deterministically. Real models sit behind the same interface: the Cosmos-Reason2 adapter and a generic chat-completions adapter, both measured or exercised against a local vLLM server on the Thor. In the UI the model is chosen in the Model page; from the command line:

```bash
python -m edge.worker \
  --config configs/cosmos_reasoning.json \
  --source examples/sample_source.json \
  --backend http://localhost:8080 \
  --adapter cosmos-reason2 \
  --adapter-endpoint http://localhost:8000/v1 \
  --model nvidia/cosmos-reason2-2b --once
```

Live cameras are decoded with PyAV, a core dependency. The `edge.worker` CLI reads video files through the optional OpenCV dependency (`pip install -e ".[opencv]"`).

## Not yet measured

The system runs end to end on the device, but none of the following has a committed measurement.

- **Live-camera latency and power on the Thor.** Every real-model run above used simulation footage read from a file. No run through a live camera has been committed, so capture rate, dropped frames, packet-to-event latency and board power with a camera attached are unknown. The asynchronous poster's effect on throughput is likewise unmeasured.
- **Rule accuracy against known scenes.** There is no labelled ground truth, so no precision or recall for any rule. The constrained 2B run reported people in people-free footage; only ground truth can turn that into a rate.
- **Calibration error.** Zones are drawn by hand on a snapshot and the proximity rule uses a fixed pixel distance. Neither is derived from camera calibration, and the error this introduces has not been characterised. This system does not estimate speed.
- **Long-run stability.** The committed runs last 60 to 390 seconds. Behaviour over hours or days (reconnects, memory, store growth) has not been measured.

## Planned upgrades

Not built or not run yet:

- A live-camera evidence run on the Thor, committed under `reports/thor/` in the existing run-report format
- Cosmos-Reason2-8B on live video
- Simulated scenes with ground truth for people, PPE and zone states, giving per-rule precision and recall. These results will be labelled simulation.

## Related

Project overview: [showcase](https://obiedeh.github.io/physical-ai-safety-observability/docs/showcase/). Sibling systems: [jetson-edge-ai-security](https://github.com/obiedeh/jetson-edge-ai-security) (measured Thor inference and power evidence for a defensive telemetry runtime) and the [Physical AI case study](https://obiedeh.github.io/physical-ai-jetson-robotics.html).

## License

MIT. See [LICENSE](LICENSE).
