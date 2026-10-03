"""Live video to the browser (MJPEG / snapshot) and browser-webcam push."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from api.services.edge import edge_service

router = APIRouter(prefix="/stream", tags=["stream"])

_BOUNDARY = "safetyframe"


@router.get("/{camera_id}/snapshot.jpg")
async def snapshot(camera_id: str) -> Response:
    session = edge_service.session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="camera is not running")
    record = session.slot.latest
    if record is None:
        raise HTTPException(status_code=503, detail="no frame received yet")
    return Response(
        content=record.jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Frame-Seq": str(record.seq)},
    )


@router.get("/{camera_id}/live.mjpeg")
async def live_mjpeg(camera_id: str, request: Request, max_fps: float = 30.0) -> StreamingResponse:
    if edge_service.session(camera_id) is None:
        raise HTTPException(status_code=404, detail="camera is not running")
    min_interval = 1.0 / max(1.0, min(max_fps, 60.0))

    async def generate():
        last_seq = -1
        last_sent = 0.0
        loop = asyncio.get_running_loop()
        while not await request.is_disconnected():
            session = edge_service.session(camera_id)
            if session is None:
                break
            record = await loop.run_in_executor(None, session.slot.wait_newer, last_seq, 1.0)
            if record is None:
                continue
            now = loop.time()
            if now - last_sent < min_interval:
                last_seq = record.seq
                continue
            last_seq = record.seq
            last_sent = now
            yield (
                f"--{_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                f"Content-Length: {len(record.jpeg)}\r\nX-Frame-Seq: {record.seq}\r\n\r\n"
            ).encode() + record.jpeg + b"\r\n"

    return StreamingResponse(
        generate(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/{camera_id}/push", status_code=204)
async def push_frame(camera_id: str, request: Request) -> Response:
    """Browser webcam ingress: the page POSTs JPEG frames captured from a canvas."""
    session = edge_service.push_session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="camera is not an enabled browser_webrtc camera")
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty frame")
    try:
        await asyncio.get_running_loop().run_in_executor(None, session.push_jpeg, body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"not a decodable JPEG: {exc}") from exc
    return Response(status_code=204)


@router.get("/{camera_id}/status")
async def stream_status(camera_id: str) -> dict:
    session = edge_service.session(camera_id)
    if session is None:
        raise HTTPException(status_code=404, detail="camera is not running")
    return session.status()
