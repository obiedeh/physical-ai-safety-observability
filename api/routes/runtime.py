"""Runtime status, live results (SSE) and measured-run recording."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.services.edge import edge_service

router = APIRouter(tags=["runtime"])


@router.get("/runtime/status")
def runtime_status() -> dict:
    return edge_service.status()


@router.get("/live/latest")
def live_latest() -> dict:
    return edge_service.hub.latest


@router.get("/live/results")
async def live_results(request: Request, camera_id: str | None = None) -> StreamingResponse:
    async def generate():
        loop = asyncio.get_running_loop()
        seq = 0
        for cid, result in edge_service.hub.latest.items():
            if camera_id is None or cid == camera_id:
                seq = max(seq, int(result.get("seq", 0)))
                yield f"event: inference_result\ndata: {json.dumps(result)}\n\n"
        while not await request.is_disconnected():
            results = await loop.run_in_executor(None, edge_service.hub.wait_after, seq, 15.0)
            if not results:
                yield "event: ping\ndata: {}\n\n"
                continue
            for result in results:
                seq = max(seq, int(result.get("seq", 0)))
                if camera_id is not None and result.get("camera_id") != camera_id:
                    continue
                yield f"event: inference_result\ndata: {json.dumps(result)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


class StartRunIn(BaseModel):
    camera_id: str
    name: str = Field(min_length=1, max_length=80)
    notes: str = ""


@router.get("/runs")
def list_runs() -> list[dict]:
    return edge_service.list_runs()


@router.get("/runs/status")
def run_status() -> dict:
    return edge_service.run_status()


@router.post("/runs/start")
def start_run(req: StartRunIn) -> dict:
    try:
        return edge_service.start_run(req.camera_id, req.name, notes=req.notes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"camera {exc.args[0]} is not running") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/runs/stop")
def stop_run() -> dict:
    try:
        return edge_service.stop_run()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
