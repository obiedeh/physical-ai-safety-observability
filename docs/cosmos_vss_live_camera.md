# Cosmos/VSS Live Camera Design

## Role split

NVIDIA Cosmos Reason2 is the intelligence and inference layer. It receives live frame or clip evidence and returns structured observations: people, PPE state, unsafe conditions, confidence, bounding boxes, and a short summary.

NVIDIA VSS is the production video layer. It should own live RTSP ingestion, multi-stream processing, video search, summarization, alert generation, and historical retrieval when the deployment grows beyond a single local worker.

This application remains the safety observability and action layer. It normalizes model or VSS outputs into SafetyEvent records, groups incidents, exposes metrics, and later dispatches configurable agentic actions.

## Startup flow

1. Ask for camera host or IP address.
2. Ask for RTSP port, default 554.
3. Ask for camera type: auto, tapo, or generic.
4. Ask for local RTSP/camera-account username.
5. Ask for password using a hidden prompt.
6. Probe candidate RTSP paths before running inference.
7. Start Cosmos inference only after a frame is successfully decoded.
8. Store redacted evidence URIs so camera credentials are not persisted.

The interactive entry point is:

    python -m edge.live_camera --backend http://127.0.0.1:8081

For a non-interactive Tapo run:

    python -m edge.live_camera --host 192.168.1.146 --camera-type tapo --username CAMERA_USER --backend http://127.0.0.1:8081

Omit password from the command so it is prompted securely.

## Development mode

Local development can sample RTSP frames directly with OpenCV and send JPEG frame bytes to a Cosmos Reason2 NIM or OpenAI-compatible endpoint configured in configs/cosmos_reasoning.json.

Flow:

    RTSP camera -> edge.live_camera probe -> OpenCV frame sampler -> Cosmos Reason2 -> safety rules -> events/incidents/metrics

## VSS production mode

For production, VSS should ingest the RTSP streams and run real-time video intelligence. This app should consume VSS alerts or verified observations, normalize them into the same SafetyEvent schema, and keep the policy/action layer independent of the camera vendor.

Flow:

    RTSP cameras -> NVIDIA VSS -> Cosmos Reason2 alert verification -> normalized safety events -> configurable actions

## Action hooks

Actions should be rule-driven and replaceable. Early actions can be log-only or webhook-only. Later actions can include operator notification, doorbell or smart-home events, incident tickets, or agent workflows. Actions should consume SafetyEvent and Incident records rather than raw camera frames.
