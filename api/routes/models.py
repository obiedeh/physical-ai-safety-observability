"""Model catalog with host preflight, and the app-managed vLLM container."""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.services.edge import edge_service
from edge.config_models import ModelSettings
from edge.model_server import annotate_catalog, find_entry

router = APIRouter(prefix="/models", tags=["models"])
logger = logging.getLogger("api.models")


class StopServerIn(BaseModel):
    # The model server may be shared with another app on the device: stopping
    # it is deliberate, logged with the caller, and never implicit.
    confirm: bool = False
    reason: str = ""


class StartServerIn(BaseModel):
    key: str = Field(min_length=1)
    port: int = Field(default=8000, ge=1024, le=65535)
    model_path: str = ""
    apply: bool = True
    json_schema: bool | None = None


@router.get("/catalog")
def catalog() -> dict:
    return annotate_catalog()


@router.get("/server")
def server_status() -> dict:
    status = edge_service.model_server.status()
    status["ready"] = False
    if status.get("state") == "starting" and status.get("endpoint"):
        try:
            response = httpx.get(f"{status['endpoint']}/models", timeout=1.5)
            status["ready"] = response.status_code == 200
        except httpx.HTTPError:
            status["ready"] = False
    if status["ready"]:
        status["state"] = "ready"
    return status


@router.post("/server/start")
def server_start(req: StartServerIn) -> dict:
    entry = find_entry(req.key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown catalog entry '{req.key}'")
    try:
        status = edge_service.model_server.start(
            entry, port=req.port, model_path=req.model_path or None
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except MemoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    edge_service.note_server_event("started by operator", entry=entry.key, port=req.port)
    applied = None
    if req.apply:
        current = edge_service.get_model_settings()
        json_schema = current.json_schema if req.json_schema is None else req.json_schema
        if json_schema and entry.reasoning_parser:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{entry.label}' runs with --reasoning-parser; constrained (json_schema) "
                    "runs require the no-reasoning entry."
                ),
            )
        applied = edge_service.put_model_settings(
            ModelSettings(
                backend="cosmos-reason2",
                endpoint=f"http://127.0.0.1:{req.port}",
                model=entry.served_model_name,
                think=current.think if entry.reasoning_parser else False,
                json_schema=json_schema,
                max_tokens=current.max_tokens,
                timeout_s=current.timeout_s,
                reasoning_parser=entry.reasoning_parser is not None,
                label=entry.label,
            )
        )
    return {"server": status, "applied": applied}


@router.post("/server/stop")
def server_stop(req: StopServerIn, request: Request) -> dict:
    if not req.confirm:
        raise HTTPException(
            status_code=409,
            detail="Stopping the model server affects every app using it; send confirm=true.",
        )
    client = request.client.host if request.client else "unknown"
    logger.warning(
        "model server stop requested by %s (%s)", client, req.reason or "no reason given"
    )
    status = edge_service.model_server.stop()
    edge_service.note_server_event("stopped by operator", client=client, reason=req.reason)
    return status
