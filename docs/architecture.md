# Architecture

The pipeline is edge-first:

```text
camera/video source -> edge worker -> VLM adapter -> safety rules -> evidence event -> API
```

The VLM adapter returns structured detections. Deterministic rules turn those detections,
runtime state, and spatial configuration into safety events. The API stores events and
rolls them into incident timelines. `/metrics` exposes Prometheus-style counters and gauges.

