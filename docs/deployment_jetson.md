# Jetson Deployment

The project keeps GPU dependencies out of the Python package. On Jetson, run the API and
worker beside a local inference service that exposes an OpenAI-compatible `/v1/chat/completions`
endpoint, then select the OpenAI-compatible adapter from the worker CLI.

Cosmos-Reason2 is the recommended first real backend for this project because the safety
events need scene-level reasoning, not only object labels. NVIDIA NIM exposes Cosmos-Reason2
through an OpenAI-compatible Chat Completions API. Wire it through the dedicated adapter:

```bash
export COSMOS_API_KEY=...
python -m edge.worker \
  --config configs/cosmos_reasoning.json \
  --source examples/sample_source.json \
  --adapter cosmos-reason2 \
  --adapter-endpoint http://127.0.0.1:8000/v1 \
  --model nvidia/cosmos-reason2-2b
```

The model name and endpoint are deployment configuration, not rule-engine dependencies.
For the larger NIM, use `--model nvidia/cosmos-reason2-8b`.

Runtime telemetry includes GPU memory and thermal pressure fields so future Jetson probes can
reduce confidence and force operator review when the edge device is degraded.

For RTSP cameras, install the optional OpenCV profile and set the source file:

```json
{
  "camera_id": "cell-a-camera-1",
  "name": "Cell A RTSP",
  "source_type": "rtsp",
  "source_uri": "rtsp://user:pass@camera/stream1",
  "frame_count": 5,
  "frame_stride": 30
}
```
