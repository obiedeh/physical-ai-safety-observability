# Architecture

## System Purpose

This repository is the safety and observability layer for Physical AI environments. It turns camera or video-source detections, runtime telemetry, and safety rules into structured events, incidents, and operator-review evidence.

## Current Implementation Status

- **Implemented:** FastAPI backend, SQLite persistence, Pydantic schemas, safety rules, incident grouping, telemetry hooks, mock VLM adapter, Docker/Compose path, tests, and demo evidence generation.
- **Mock validation path:** deterministic mock detections prove schema, policy, event, telemetry, and reporting flow.
- **Planned Jetson deployment:** Jetson runtime metrics and camera/video evidence after real adapter and hardware artifacts are committed.
- **Future hardware validation:** real VLM/camera runs and operator-review screenshots.

## Main Components

- `edge/`: worker loop, frame sampling, source handling, and VLM adapter contract.
- `edge/adapters/`: mock and endpoint-oriented model adapter paths.
- `rules/`: safety policy evaluation for PPE, restricted zones, proximity, and unsafe events.
- `events/`: safety event and incident schemas.
- `api/`: FastAPI routes for health, events, incidents, cameras, and metrics.
- `telemetry/`: runtime metrics and observability helpers.
- `evidence/`: frame hashing and evidence-chain helpers.
- `examples/`: deterministic demo and sample source inputs.

## Runtime Flow

The current runnable path starts an API, samples synthetic or configured sources through the edge worker, evaluates detections against safety rules, persists events/incidents, and exposes metrics for review. `make demo-evidence` produces deterministic proof artifacts when available.

## Data / Telemetry Flow

Frame context and detections become normalized safety events. Events update incidents, telemetry counters, latency summaries, and evidence reports. Mock adapter outputs do not prove model accuracy.

## Deployment Modes

- **Local development:** FastAPI, SQLite, mock adapter, tests, and deterministic evidence generation.
- **Docker/Compose:** local service orchestration for repeatable reviewer smoke tests.
- **Planned Jetson deployment:** camera/video source, real VLM endpoint or local adapter, Jetson metrics, and sustained-run artifacts.
- **Future operator review:** dashboard or screenshots for human-in-the-loop incident review.

## Evidence Artifacts

- Deterministic evidence path: `reports/demo/` when generated.
- Artifact placeholders: `artifacts/sample-inputs/`, `artifacts/sample-outputs/`, `artifacts/logs/`, and `artifacts/reports/`.
- Diagram sources: `docs/diagrams/`.

## Known Limitations

- Mock adapter evidence does not prove real VLM accuracy.
- Jetson command paths are not benchmark evidence until hardware artifacts are committed.
- Synthetic/demo paths are validation scaffolds, not real-world deployment proof.

## Next Validation Step

Add one real-image or real-video adapter run with explicit limitations, runtime metrics, and operator-review evidence.
