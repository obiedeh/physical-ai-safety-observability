"""UI-driven configuration: cameras (CRUD, test, enable), model, inference."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.services.edge import edge_service
from edge.camera_profiles import CameraConfigError, get_profile, list_profiles
from edge.config_models import CameraIn, CameraRecord, InferenceSettings, ModelSettings
from edge.probe import probe_stream
from edge.redaction import REDACTOR

router = APIRouter(prefix="/config", tags=["config"])


class EnableIn(BaseModel):
    enabled: bool


class CameraOut(CameraRecord):
    runtime: dict | None = None


def _out(record: CameraRecord) -> CameraOut:
    session = edge_service.session(record.camera_id)
    worker = edge_service.workers.get(record.camera_id)
    runtime = None
    if session is not None:
        runtime = {**session.status(), "worker": worker.status() if worker else None}
    return CameraOut(**record.model_dump(), runtime=runtime)


@router.get("/profiles")
def camera_profiles() -> list[dict]:
    return list_profiles()


@router.get("/cameras", response_model=list[CameraOut])
def list_cameras() -> list[CameraOut]:
    return [_out(c) for c in edge_service.list_cameras()]


@router.post("/cameras", response_model=CameraOut, status_code=201)
def create_camera(req: CameraIn) -> CameraOut:
    try:
        record = edge_service.create_camera(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _out(record)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str) -> CameraOut:
    record = edge_service.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: str, req: CameraIn) -> CameraOut:
    try:
        record = edge_service.update_camera(camera_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.post("/cameras/{camera_id}/enabled", response_model=CameraOut)
def set_enabled(camera_id: str, req: EnableIn) -> CameraOut:
    record = edge_service.set_enabled(camera_id, req.enabled)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    return _out(record)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: str) -> None:
    if not edge_service.delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="camera not found")


def _probe(url: str, transport: str) -> dict:
    data = probe_stream(url, rtsp_transport=transport).to_dict()
    if data.get("error"):
        data["error"] = REDACTOR.redact(data["error"])
    return data


@router.post("/cameras/test")
def test_unsaved_camera(req: CameraIn) -> dict:
    profile = get_profile(req.profile)
    if not profile.requires_host:
        return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
                "note": f"{profile.label} has no stream to probe."}
    try:
        url = profile.build_url(
            host=req.host, username=req.username or None, password=req.password or None,
            port=req.port, channel=req.channel, quality=req.stream_quality,
            path=req.stream_path or None,
        )
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    REDACTOR.register(req.password)
    return _probe(url, req.rtsp_transport)


@router.post("/cameras/{camera_id}/test")
def test_saved_camera(camera_id: str) -> dict:
    record = edge_service.get_camera(camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail="camera not found")
    profile = get_profile(record.profile)
    if not profile.requires_host:
        return {"ok": True, "stage": "ok", "error": None, "masked_url": "",
                "note": f"{profile.label} has no stream to probe."}
    try:
        url = edge_service.feed_url(camera_id)
    except CameraConfigError as exc:
        return {"ok": False, "stage": "url", "error": str(exc), "masked_url": ""}
    return _probe(url, record.rtsp_transport)


# ── model / inference ─────────────────────────────────────────────────────────


@router.get("/model", response_model=ModelSettings)
def get_model() -> ModelSettings:
    return edge_service.get_model_settings()


@router.put("/model", response_model=ModelSettings)
def put_model(req: ModelSettings) -> ModelSettings:
    return edge_service.put_model_settings(req)


@router.get("/model/guard")
def model_guard() -> dict:
    return {
        "guard": edge_service.guard.to_dict() if edge_service.guard else None,
        "constrained_allowed": edge_service.constrained_allowed(),
        "json_schema": edge_service.model_settings.json_schema,
    }


@router.post("/model/guard")
def rerun_model_guard() -> dict:
    result = edge_service.run_guard()
    return {"guard": result.to_dict(), "constrained_allowed": edge_service.constrained_allowed()}


@router.get("/inference", response_model=InferenceSettings)
def get_inference() -> InferenceSettings:
    return edge_service.get_inference_settings()


@router.put("/inference", response_model=InferenceSettings)
def put_inference(req: InferenceSettings) -> InferenceSettings:
    return edge_service.put_inference_settings(req)
